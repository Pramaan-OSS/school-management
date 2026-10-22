// One local port for pages and the application's realtime server.
import http from 'node:http'
import { createGzip } from 'node:zlib'

const target = url => url.startsWith('/socket.io/') ? 9000 : 8081
const proxyHeaders = request => ({
  ...request.headers,
  // Same-origin polling GETs omit Origin; the event server requires it.
  origin: request.headers.origin || `http://${request.headers.host}`,
  'x-forwarded-for': request.socket.remoteAddress,
  'x-forwarded-proto': 'http',
})
const server = http.createServer((request, response) => {
  const upstream = http.request({
    hostname: '127.0.0.1', port: target(request.url),
    path: request.url, method: request.method, headers: proxyHeaders(request),
  }, incoming => {
    const headers = { ...incoming.headers }
    const compress = request.method === 'GET' && request.url.startsWith('/assets/') &&
      incoming.statusCode === 200 && /\bgzip\b/.test(request.headers['accept-encoding'] || '') &&
      /javascript|text\/css|image\/svg\+xml/.test(headers['content-type'] || '') &&
      !headers['content-encoding'] && !request.headers.range
    if (compress) {
      delete headers['content-length']
      headers['content-encoding'] = 'gzip'
      headers.vary = [headers.vary, 'Accept-Encoding'].filter(Boolean).join(', ')
    }
    incoming.on('error', () => response.destroy())
    response.writeHead(incoming.statusCode, headers)
    if (compress) incoming.pipe(createGzip()).pipe(response)
    else incoming.pipe(response)
  })
  upstream.on('error', () => {
    if (!response.headersSent) response.writeHead(503, { 'Content-Type': 'text/plain' })
    response.end('School Management is starting. Please try again shortly.')
  })
  request.on('aborted', () => upstream.destroy())
  request.pipe(upstream)
})
server.on('upgrade', (request, socket, head) => {
  if (!request.url.startsWith('/socket.io/')) { socket.destroy(); return }
  const upstream = http.request({ hostname: '127.0.0.1', port: 9000,
    path: request.url, headers: proxyHeaders(request) })
  upstream.on('upgrade', (response, peer, peerHead) => {
    socket.write(`HTTP/1.1 ${response.statusCode} ${response.statusMessage}\r\n`)
    for (const [key, value] of Object.entries(response.headers)) socket.write(`${key}: ${value}\r\n`)
    socket.write('\r\n')
    if (head.length) peer.write(head)
    if (peerHead.length) socket.write(peerHead)
    peer.pipe(socket); socket.pipe(peer)
    peer.on('error', () => socket.destroy())
    socket.on('error', () => peer.destroy())
    socket.on('close', () => peer.destroy())
  })
  upstream.on('error', () => socket.destroy())
  upstream.on('response', () => socket.destroy())
  upstream.end()
})
server.listen(8000, '0.0.0.0')
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => process.exit(0)))
