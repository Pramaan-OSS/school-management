<template>
  <div>
    <Dialog
      :options="{
        title: 'Pay Fees',
        actions: [{ label: 'Save', variant: 'solid' }],
      }"
      :modelValue="modelValue"
      @update:modelValue="emits('update:modelValue', $event)"
    >
      <template #body-content>
        <div class="flex flex-col gap-4">
          <p v-if="needsPaymentSetup" role="alert" class="rounded border p-3 text-sm">
            Connect your payments account first.
            <a href="/app/payments-account" class="underline">Open Payments account (administrators)</a>
          </p>
          <section v-if="transferState" aria-live="polite" class="rounded border p-3">
            <p>{{ transferLabels[transferState.status] || 'Check status' }}</p>
            <p v-if="transferState.reference">Quote this reference: <strong>{{ transferState.reference }}</strong></p>
            <dl v-for="(value, key) in transferState.bank || {}" :key="key">
              <dt>{{ bankLabels[key] || key }}</dt><dd>{{ Array.isArray(value) ? value.join(', ') : value }}</dd>
            </dl>
          </section>
          <FormControl v-model="bankCountry" label="Receiving bank country (two-letter code, required for EUR)" />
          <p v-if="approval">{{ approval.action === 'cancel' ? 'Cancel this transfer request? Money already received will not be moved.' : 'Create bank instructions for this fee?' }}</p>
          <Button v-if="approval" label="Confirm bank transfer action" @click="confirmTransfer" :loading="transferBusy" />
          <Button v-if="approval" label="Go back" @click="approval = null" />
          <div v-for="section in allFields" :key="section.section">
            <div class="grid grid-cols-2 gap-4">
              <div
                v-for="field in section.fields"
                :key="field.name"
                :class="field.hidden && 'hidden'"
              >
                <div class="mb-2 text-sm text-gray-600">{{ field.label }}</div>
                <FormControl
                  v-if="
                    field.name === 'mobile_number' || field.name === 'email'
                  "
                  :type="field.type"
                  v-model="billingDetails[field.name]"
                  :placeholder="field.placeholder"
                  :disabled="field.readonly"
                  @change="validateFields()"
                />
                <FormControl
                  v-else
                  :type="field.type"
                  v-model="billingDetails[field.name]"
                  :placeholder="field.placeholder"
                  :disabled="field.readonly"
                  @change="validateFields()"
                />
                <ErrorMessage
                  v-if="field.name === 'email' && !isEmailPresent"
                  message="Email is Required"
                  class="pt-2"
                />
              </div>
            </div>
          </div>
        </div>
      </template>
      <template #actions="{ close }">
        <div class="flex flex-wrap gap-2">
          <Button v-if="transferState?.status !== 'paid'" label="Pay by bank transfer" @click="openTransfer" :loading="transferBusy" />
          <Button v-if="transferState && transferState.status !== 'not_created'" label="Refresh transfer status" @click="transferAction('status')" :loading="transferBusy" />
          <Button v-if="transferState && ['awaiting_payment', 'partially_paid'].includes(transferState.status)" label="Cancel transfer request" @click="transferAction('cancel')" :loading="transferBusy" />
          <Button
            v-if="transferState?.status !== 'paid'"
            class="w-48 h-7"
            variant="solid"
            @click="openCheckout(close)"
            icon-left="external-link"
            :loading="checkout.loading"
            label="Proceed to Payment"
          />
        </div>
      </template>
    </Dialog>
  </div>
</template>
<script setup>
import { reactive, ref, watch } from 'vue'
import { FormControl, Dialog, createResource, ErrorMessage } from 'frappe-ui'
import { createToast } from '../utils'
import { submitCheckout } from '../utils/checkout.mjs'

const props = defineProps({
  modelValue: {
    type: Boolean,
    required: false,
  },
  student: {
    type: Object,
    required: true,
  },
  row: {
    type: Object,
    required: true,
  },
})
const emits = defineEmits(['update:modelValue', 'success'])

const transferState = ref(null)
const bankCountry = ref('')
const approval = ref(null)
const transferBusy = ref(false)
const transferLabels = {not_created: 'No bank transfer request yet', awaiting_payment: 'Awaiting payment', partially_paid: 'Partially paid', paid: 'Paid', cancelled: 'Cancelled', expired: 'Expired'}
const bankLabels = {holder: 'Account holder', bankName: 'Bank', iban: 'IBAN', bic: 'BIC', country: 'Country', accountNumber: 'Account number', routingNumber: 'Routing number', sortCode: 'Sort code', swiftCode: 'SWIFT code', networks: 'Networks'}
const transferRequest = createResource({url: 'education.education.bank_transfer.transfer'})
watch(() => props.row.invoice, () => { transferState.value = null; approval.value = null })
async function transferAction(operation, confirmation) {
  transferBusy.value = true
  try {
    const data = await transferRequest.submit({docname: props.row.invoice, operation, confirmation, bank_country: bankCountry.value})
    if (data.confirmation) approval.value = data
    else {
      const wasPaid = transferState.value?.status === 'paid'
      transferState.value = data; approval.value = null
      if (data.status === 'paid' && !wasPaid) emits('success')
    }
  } catch (error) { showError(error) }
  finally { transferBusy.value = false }
}
async function openTransfer() {
  await transferAction('status')
  if (transferState.value?.status === 'not_created') await transferAction('create')
}
async function confirmTransfer() {
  if (!approval.value) return
  await transferAction('confirm', approval.value.confirmation)
}

const checkout = createResource({
  url: 'education.education.billing.create_checkout',
  makeParams() {
    return {
      doctype: 'Sales Invoice',
      docname: props.row.invoice,
      billing_details: billingDetails,
    }
  },
})

async function openCheckout(close) {
  if (!billingDetails.email) {
    validateFields()
    return
  }
  await submitCheckout(checkout, (data) => {
    if (data && data.checkoutUrl) {
      window.location.href = data.checkoutUrl
    } else {
      showError()
    }
  }, showError)
}

function validateFields() {
  if (billingDetails.email) {
    isEmailPresent.value = true
  } else {
    isEmailPresent.value = false
  }
}

function showError(err) {
  let message =
    (err && err.messages && err.messages[0]) || 'Something went wrong'
  if (message.includes('/app/payments-account')) {
    needsPaymentSetup.value = true
    message = 'Connect your payments account first.'
  }
  createToast({
    message: message,
    icon: 'x',
    iconClasses: 'text-red-600',
  })
}

const isEmailPresent = ref(true)
const needsPaymentSetup = ref(false)

const billingDetails = reactive({
  program: props.row.program || '',
  student: props.student.student_name || '',
  amount: props.row.amount || '',
  id: props.student.name || '',
  mobile_number: '',
  email: props.student.student_email_id || '',
  address_line_1: props.student.address_line_1 || '',
  address_line_2: props.student.address_line_2 || '',
  city: props.student.city || '',
  state: props.student.state || '',
  country: props.student.country || '',
  pincode: props.student.pincode || '',
})

const allFields = [
  {
    section: 'Student Details',
    fields: [
      {
        label: 'Student',
        name: 'student',
        type: 'data',
        readonly: true,
      },
      {
        label: 'Student',
        name: 'id',
        type: 'data',
        readonly: true,
      },
      {
        label: 'Amount',
        name: 'amount',
        type: 'data',
        readonly: true,
      },
      {
        label: 'Program',
        name: 'program',
        type: 'data',
        readonly: true,
      },
      {
        label: 'Mobile Number (optional)',
        name: 'mobile_number',
        type: 'data',
      },
      {
        label: 'Email',
        name: 'email',
        type: 'data',
      },
    ],
  },
  {
    section: 'Student Address',
    fields: [
      {
        label: 'Address Line 1',
        name: 'address_line_1',
        type: 'data',
      },
      {
        label: 'Address Line 2',
        name: 'address_line_2',
        type: 'data',
      },
      {
        label: 'City',
        name: 'city',
        type: 'data',
      },
      {
        label: 'State',
        name: 'state',
        type: 'data',
      },
      {
        label: 'Country',
        name: 'country',
        type: 'data',
      },
      {
        label: 'Pincode',
        name: 'pincode',
        type: 'data',
      },
    ],
  },
]
</script>
