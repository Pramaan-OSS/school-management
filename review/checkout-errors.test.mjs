import test from 'node:test'
import assert from 'node:assert/strict'
import { submitCheckout } from '../frontend/src/utils/checkout.mjs'

test('a refused checkout produces one message without rejecting the click', async () => {
  const refusal = new Error('Fee payments are not available yet.')
  const messages = []
  const fake = { async submit() { throw refusal } }
  await assert.doesNotReject(submitCheckout(fake, () => assert.fail('No checkout was created'), error => messages.push(error)))
  assert.deepEqual(messages, [refusal])
})

test('an accepted checkout reaches the redirect callback once', async () => {
  const result = { checkoutUrl: 'https://checkout.school.test/pay' }
  const redirects = []
  const fake = { async submit(params, { onSuccess }) { onSuccess(result) } }
  await submitCheckout(fake, data => redirects.push(data.checkoutUrl), () => assert.fail('Checkout succeeded'))
  assert.deepEqual(redirects, [result.checkoutUrl])
})
