// Resource error callbacks still reject their returned promise.
export async function submitCheckout(checkout, onSuccess, onError) {
  try {
    await checkout.submit({}, { onSuccess })
  } catch (error) {
    onError(error)
  }
}
