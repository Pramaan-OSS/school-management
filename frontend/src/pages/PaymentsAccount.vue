<template><div ref="root" /></template>
<script setup>
// Route adapter only; the drop-in component owns setup, theming and lifecycle.
import { ref, onMounted, onBeforeUnmount } from 'vue'
import '../../../education/public/js/payment_account.js'
const root = ref(null)
let panel
onMounted(() => {
  panel = new window.PaymentsAccountPanel(root.value, { api: async (method, args = {}) => {
    const response = await fetch('/api/method/education.education.payment_account.' + method, {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Frappe-CSRF-Token': window.csrf_token },
      body: JSON.stringify(args),
    })
    if (!response.ok) throw new Error('Account unavailable')
    return (await response.json()).message
  } })
})
onBeforeUnmount(() => panel?.dispose())
</script>
