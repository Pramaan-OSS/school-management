import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { chromium } from 'playwright'

const base = process.env.BASE_URL || 'http://localhost:3037'
const root = process.env.SCHOOL_CHECK_ROOT || '.'
const shots = path.join(root, '.scratch/shots')
const password = fs.readFileSync(path.join(root, '.runtime/local-admin-password'), 'utf8').trim()
const mode = process.argv[2] || 'fake'
fs.mkdirSync(shots, { recursive: true })
process.env.TMPDIR = path.resolve(root, '.scratch/browser-tmp')
fs.mkdirSync(process.env.TMPDIR, { recursive: true })
const browser = await chromium.launch({ headless: true })
let checks = 0
const check = (name, value) => { assert.ok(value, name); checks++; console.log('PASS ' + name) }
async function login(page, user, secret) {
  await page.goto(base + '/login', { waitUntil: 'domcontentloaded' })
  await page.fill('#login_email', user)
  await page.fill('#login_password', secret)
  await page.locator('button[type="submit"]').first().click()
  await page.waitForURL(url => !url.pathname.includes('/login'), { timeout: 60000 })
}
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
  await context.route('**/*', route => {
    const url = new URL(route.request().url())
    return ['localhost', '127.0.0.1'].includes(url.hostname) ? route.continue() : route.abort()
  })
  if (mode === 'fake') {
    assert.ok(process.env.CHECKOUT, 'Set CHECKOUT to the seeded Payment Record name')
    const page = await context.newPage()
    await login(page, 'ada@example.com', 'portal-pass-123')
    const returned = page.waitForResponse(r => r.url().includes('billing.get_checkout_status'))
    await page.goto(base + '/student-portal/fees?checkout=' + process.env.CHECKOUT, { waitUntil: 'domcontentloaded' })
    const payload = await (await returned).json()
    check('return checks the saved checkout on the server', /not available yet/i.test(JSON.stringify(payload)))
    await page.getByText('Fee payments are not available yet.', { exact: true }).first().waitFor()
    check('return displays the plain unavailable message', true)
    await page.getByRole('button', { name: 'Pay Now', exact: true }).first().waitFor()
    check('fee rows render after returning', true)
    await page.screenshot({ path: path.join(shots, 'fees-return-page.png'), fullPage: true })
    await page.getByRole('button', { name: 'Pay Now', exact: true }).first().click()
    const dialog = page.getByRole('dialog')
    await dialog.waitFor()
    const fields = dialog.locator('input')
    for (let i = 0; i < await fields.count(); i++) {
      const input = fields.nth(i)
      if (await input.isEnabled() && !(await input.inputValue())) {
        await input.fill((await input.getAttribute('type')) === 'email' ? 'ada@example.com' : '+919999999999')
      }
    }
    const checkout = page.waitForResponse(r => r.url().includes('billing.create_checkout'))
    await page.getByRole('button', { name: 'Proceed to Payment', exact: true }).click()
    check('unavailable checkout does not report success', /not available yet/i.test(await (await checkout).text()))
    check('fee page contains no vendor names', !/razorpay|stripe|checkout\.js/i.test(await page.textContent('body')))
    await page.screenshot({ path: path.join(shots, 'fees-pay-result.png'), fullPage: true })
    await context.clearCookies()
  }
  const admin = await context.newPage()
  await login(admin, 'Administrator', password)
  await admin.goto(base + '/app/education-settings', { waitUntil: 'domcontentloaded' })
  const button = admin.getByRole('button', { name: 'Check Payment Account', exact: true })
  await button.waitFor({ timeout: 30000 })
  check('payment settings actions are present', await button.isVisible())
  await admin.getByText('Portal Settings', { exact: true }).click()
  check('settings have no vendor key fields', !/razorpay|key id|key secret|api secret/i.test(await admin.textContent('body')))
  const status = admin.waitForResponse(r => r.url().includes('billing.refresh_payment_account_status'))
  await button.click()
  const result = await (await status).text()
  if (mode === 'nokey') {
    check('no-key response gives the setup message', /Add PRAMAAN_API_KEY to \.env/.test(result))
    await admin.getByText('Add PRAMAAN_API_KEY to .env', { exact: true }).first().waitFor()
    check('no-key message is visible on screen', true)
  } else {
    check('fake payment account is pending', JSON.parse(result).message.status === 'pending')
    await admin.locator('[data-fieldname="payment_account_status"]').getByText('Pending setup', { exact: true }).waitFor()
    check('settings display the saved account state', true)
  }
  await admin.screenshot({ path: path.join(shots, mode === 'nokey' ? 'no-key-message.png' : 'education-settings.png'), fullPage: true })
  console.log(`${checks} checks passed (${mode})`)
} finally {
  await browser.close()
}
