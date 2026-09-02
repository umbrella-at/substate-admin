<script setup lang="ts">
/**
 * The six things that can be done to one subscription.
 *
 * WHICH ONES ASK FIRST. An operation is confirmed when a person cannot reverse its effect with
 * another operation on this card AND the consequence is not already stated by what they typed.
 * That gives a dialog to cancel, start and redeem, and none to payment, change of plan and
 * programme — each answer with a reason in the engine rather than a feeling about the verb.
 *
 *   cancel     no un-cancel; the consequence is a date the operator never typed
 *   start      `_begin_cycle` wipes the promo code, the pending plan and any remaining access
 *   redeem     a redemption is spent and the storage has no way to return one
 *   payment    idempotent on its reference, and the amount is in front of them
 *   change     calling it again with the current plan drops the pending one — it undoes itself
 *   programme  calling it again with another programme moves only future accruals
 *
 * PERMISSION DECIDES WHETHER A CONTROL IS DRAWN; STATE DECIDES WHETHER IT IS DISABLED. A button
 * somebody may never press is not offered — the guard would refuse it anyway. A button that is
 * theirs but would do nothing in this state is drawn and disabled with the reason beside it,
 * because "you cannot pay for a cancelled subscription" is a fact about this subscriber worth
 * reading, and a missing control says nothing at all.
 *
 * WHAT THE ANSWER SAYS COMES FROM THE ENGINE, NOT FROM THE BUTTON. Three payment outcomes are
 * successes that changed nothing — a duplicate reference, a short payment, a payment on a
 * cancelled record — so the notice is rendered from the events that came back. A notice written
 * from the button would say "Payment recorded" over a card that had not moved.
 */

import { toTypedSchema } from '@vee-validate/zod'
import { useQuery } from '@tanstack/vue-query'
import { useForm } from 'vee-validate'
import { computed, ref } from 'vue'
import { z } from 'zod'

import {
  ApiError,
  type OperationPath,
  type PlanSummary,
  type ReferralProgramSummary,
  type SubscriberDetail,
} from '@/api/client'
import { useApiClient } from '@/api/provide'
import AppButton from '@/components/AppButton.vue'
import AppChoiceField from '@/components/AppChoiceField.vue'
import AppConfirm from '@/components/AppConfirm.vue'
import AppField from '@/components/AppField.vue'
import AppNotice from '@/components/AppNotice.vue'
import { useSubscriberOperation } from '@/composables/useSubscriber'
import { CHANGED_NOTHING, moment, money, sentence } from '@/domain/events'
import { canStartNewSubscription, paymentWouldApply } from '@/domain/subscription'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ detail: SubscriberDetail }>()

const auth = useAuthStore()
const client = useApiClient()
const row = computed(() => props.detail.subscriber)
const userId = computed(() => row.value.userId)

const { mutateAsync, isPending } = useSubscriberOperation(userId)

const mayWrite = computed(() => auth.can('subscribers.write'))
const mayAssign = computed(() => auth.can('referrals.write'))

/** The catalogues the two choices are made from. Cached for the session: five plans and two
 *  programmes do not change while somebody is looking at a card. */
const { data: plans } = useQuery<PlanSummary[]>({
  queryKey: ['plans'],
  queryFn: ({ signal }) => client.plans(signal),
  staleTime: Infinity,
  enabled: mayWrite,
})
const { data: programs } = useQuery<ReferralProgramSummary[]>({
  queryKey: ['referral-programs'],
  queryFn: ({ signal }) => client.referralPrograms(signal),
  staleTime: Infinity,
  enabled: mayAssign,
})

const planOptions = computed(() =>
  (plans.value ?? []).map((plan) => ({ value: plan.id, label: plan.id })),
)
const programOptions = computed(() =>
  (programs.value ?? []).map((program) => ({
    value: program.id,
    label: `${program.id} — ${program.percent}% ${
      program.accrual === 'every_payment' ? 'on every payment' : 'on the first payment'
    }`,
  })),
)

// ------------------------------------------------------------------------------------------
// The one answer, and the one way a refusal reaches a field.
// ------------------------------------------------------------------------------------------

type Role = 'success' | 'warning' | 'danger'
const notice = ref<{ role: Role; lines: string[] } | null>(null)

const UNREACHABLE = 'The service could not be reached. The subscription was not changed.'

interface Attempt {
  operation: OperationPath
  body?: unknown
  /** What to say when the engine accepted the call and emitted nothing. Three of the six can do
   *  that legally, and "nothing happened" is not the same sentence as "it worked". */
  otherwise: string
  /** Whether emitting nothing means it worked. It does for a programme assignment, which the
   *  engine records and publishes no event for; it does not for a second cancellation. */
  otherwiseRole: Role
  /** The form whose input a refusal belongs to, if the refusal names one. */
  onField?: (field: string, message: string) => void
}

async function run(attempt: Attempt): Promise<void> {
  notice.value = null
  try {
    const result = await mutateAsync({ operation: attempt.operation, body: attempt.body ?? {} })
    // Green over "Nothing changed" is a contradiction the eye reads before the words. A duplicate
    // reference, a short payment and a payment on a cancelled record are all 200s that moved
    // nothing, and the colour has to come from what the engine said rather than from the status.
    const moved = result.events.some((event) => !CHANGED_NOTHING.has(event.type))
    notice.value =
      result.events.length === 0
        ? { role: attempt.otherwiseRole, lines: [attempt.otherwise] }
        : { role: moved ? 'success' : 'warning', lines: result.events.map(sentence) }
  } catch (failure) {
    if (!(failure instanceof ApiError)) {
      notice.value = { role: 'danger', lines: [UNREACHABLE] }
      return
    }
    // The envelope names the input a refusal is about, which is the whole reason it carries a
    // field — and when it does, the sentence goes THERE and nowhere else. A banner repeating the
    // same words above the same form is one refusal read twice, and the login page's rule is the
    // same one: a form says what is wrong in one place.
    if (failure.field !== null && attempt.onField !== undefined) {
      attempt.onField(failure.field, failure.message)
      return
    }
    notice.value = { role: 'danger', lines: [failure.message] }
  }
}

// ------------------------------------------------------------------------------------------
// Record a payment. No dialog: idempotent on its reference, and the amount is in front of them.
// ------------------------------------------------------------------------------------------

/** Minor units, as the engine counts them, from what a person typed. `5` and `5.00` are 500. */
function minorUnits(typed: string): number {
  return Math.round(Number(typed) * 100)
}

const amountShape = z
  .string()
  .trim()
  .regex(/^\d+(\.\d{1,2})?$/u, 'An amount, like 5.00.')
  .refine((typed) => minorUnits(typed) > 0, 'An amount greater than zero.')

const payment = useForm({
  validationSchema: toTypedSchema(
    // Not `.optional()`: an optional field makes its ref `string | undefined`, and a text
    // input bound to undefined is an input whose value the form cannot write back. Empty is
    // what "not given" looks like in a text field, and the submit turns it into null.
    z.object({ amount: amountShape, reference: z.string().trim().max(128) }),
  ),
  initialValues: { amount: (props.detail.plan.price / 100).toFixed(2), reference: '' },
})
const amount = payment.defineField('amount')
const reference = payment.defineField('reference')

const onPayment = payment.handleSubmit((values) =>
  run({
    operation: 'payment',
    body: {
      amount: minorUnits(values.amount),
      reference: values.reference === '' ? null : values.reference,
    },
    otherwise: 'The payment was recorded and the subscription did not move.',
    otherwiseRole: 'warning',
    onField: (field, message) => payment.setFieldError(field as 'amount', message),
  }),
)

// ------------------------------------------------------------------------------------------
// Change plan. No dialog: calling it again with the current plan drops the pending one.
// ------------------------------------------------------------------------------------------

const changePlan = useForm({
  validationSchema: toTypedSchema(z.object({ planId: z.string().min(1, 'Choose a plan.') })),
  initialValues: { planId: props.detail.subscriber.planId },
})
const nextPlan = changePlan.defineField('planId')

const onChangePlan = changePlan.handleSubmit((values) =>
  run({
    operation: 'change-plan',
    body: { planId: values.planId },
    otherwise: `Already on ${values.planId}, with no change waiting.`,
    otherwiseRole: 'warning',
    onField: (field, message) => changePlan.setFieldError(field as 'planId', message),
  }),
)

// ------------------------------------------------------------------------------------------
// Redeem a promo code. A dialog: a redemption is spent and nothing can return it.
// ------------------------------------------------------------------------------------------

const redeem = useForm({
  validationSchema: toTypedSchema(
    z.object({ promoCode: z.string().trim().min(1, 'A promo code.').max(64) }),
  ),
  initialValues: { promoCode: '' },
})
const promoCode = redeem.defineField('promoCode')
const redeeming = ref(false)

const onRedeem = redeem.handleSubmit(() => {
  redeeming.value = true
})

async function confirmRedeem(): Promise<void> {
  const code = redeem.values.promoCode ?? ''
  await run({
    operation: 'redeem',
    body: { promoCode: code },
    otherwise: `${code} was redeemed.`,
    otherwiseRole: 'success',
    onField: (field, message) => redeem.setFieldError(field as 'promoCode', message),
  })
  redeeming.value = false
}

// ------------------------------------------------------------------------------------------
// Assign a referral programme. No dialog: only future accruals move, and calling it again moves
// them back.
// ------------------------------------------------------------------------------------------

const assign = useForm({
  validationSchema: toTypedSchema(
    z.object({ programId: z.string().min(1, 'Choose a programme.') }),
  ),
  initialValues: { programId: props.detail.referralProgramId ?? '' },
})
const programId = assign.defineField('programId')

const onAssign = assign.handleSubmit((values) =>
  run({
    operation: 'referral-program',
    body: { programId: values.programId },
    // This one emits nothing at all, ever: the engine records the assignment and publishes no
    // event, so the card is the only evidence and this sentence is the whole answer.
    otherwise: `${userId.value} is now paid on the ${values.programId} programme.`,
    otherwiseRole: 'success',
    onField: (field, message) => assign.setFieldError(field as 'programId', message),
  }),
)

// ------------------------------------------------------------------------------------------
// Cancel. A dialog: no un-cancel, and the consequence is a date nobody typed.
// ------------------------------------------------------------------------------------------

const cancelling = ref(false)

const cancelConsequence = computed(() => {
  const until = row.value.accessUntil
  if (row.value.state === 'trial') {
    return `The trial ends on ${moment(until ?? null)} as planned, and nothing will renew after it.`
  }
  return `Access runs to ${moment(until ?? null)} and then stops. Renewal will not be attempted.`
})

async function confirmCancel(): Promise<void> {
  await run({
    operation: 'cancel',
    body: {},
    otherwise: 'This subscription was already cancelled.',
    otherwiseRole: 'warning',
  })
  cancelling.value = false
}

// ------------------------------------------------------------------------------------------
// Start a new subscription. A dialog: `_begin_cycle` wipes what is left of the old one.
// ------------------------------------------------------------------------------------------

const restart = useForm({
  validationSchema: toTypedSchema(
    z.object({
      planId: z.string().min(1, 'Choose a plan.'),
      promoCode: z.string().trim().max(64),
    }),
  ),
  initialValues: { planId: props.detail.subscriber.planId, promoCode: '' },
})
const restartPlan = restart.defineField('planId')
const restartPromo = restart.defineField('promoCode')
const restarting = ref(false)

const onRestart = restart.handleSubmit(() => {
  restarting.value = true
})

/** What starting a new subscription will actually do to this record.
 *
 *  It branches on whether a trial was ever granted, which is why `trialStartedAt` is on the wire:
 *  a record that never had one gets the new plan's trial free, and one that did starts expired and
 *  waiting for money. A dialog that could not tell those apart would have to guess. */
const restartConsequence = computed(() => {
  const fresh = props.detail.trialStartedAt === null || props.detail.trialStartedAt === undefined
  const chosen = (plans.value ?? []).find((plan) => plan.id === restart.values.planId)
  const trial =
    fresh && chosen !== undefined && chosen.trialDays > 0
      ? ` ${chosen.id} starts with ${chosen.trialDays} free days.`
      : ' It starts unpaid, waiting for a first payment.'
  return `This clears the promo code and any pending plan change.${trial}`
})

async function confirmRestart(): Promise<void> {
  const code = restart.values.promoCode ?? ''
  await run({
    operation: 'subscribe',
    body: { planId: restart.values.planId, promoCode: code === '' ? null : code },
    otherwise: 'A new subscription was started.',
    otherwiseRole: 'success',
    onField: (field, message) => restart.setFieldError(field as 'planId', message),
  })
  restarting.value = false
}

// ------------------------------------------------------------------------------------------
// What this state allows.
// ------------------------------------------------------------------------------------------

const canPay = computed(() => paymentWouldApply(row.value.state))
const canRestart = computed(() => canStartNewSubscription(row.value.state))
/** Cancelling a cancelled subscription does nothing, and cancelling an expired one is undone by
 *  the next tick — it sets a boundary that has already passed. Both are drawn and refused. */
const canCancel = computed(() => row.value.state !== 'cancelled' && row.value.state !== 'expired')

const unavailable = computed(() => {
  if (row.value.state === 'cancelled') {
    return 'This subscription is cancelled: a payment against it is filed and applies to nothing, and a plan change would never be read. Start a new subscription instead.'
  }
  if (row.value.state === 'expired') {
    return 'This subscription has ended. A payment starts a new paid period; there is nothing left to cancel.'
  }
  return null
})

/** The one filled element on this screen: the operation that would actually change something in
 *  the state this subscriber is in. On a cancelled record that is not the payment. */
const primary = computed<OperationPath>(() => (canPay.value ? 'payment' : 'subscribe'))
</script>

<template>
  <section v-if="mayWrite || mayAssign" class="rounded-card bg-surface-1 p-4">
    <h2 class="text-heading text-text-primary">Operations</h2>

    <p v-if="unavailable !== null" class="mt-3 max-w-reading text-dense text-text-muted">
      {{ unavailable }}
    </p>

    <AppNotice
      v-if="notice !== null"
      :role="notice.role"
      :assertive="notice.role === 'danger'"
      class="mt-4"
    >
      <p v-for="line in notice.lines" :key="line">{{ line }}</p>
    </AppNotice>

    <div class="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-2">
      <!-- Record a payment -->
      <form v-if="mayWrite" class="flex flex-col gap-4" @submit="onPayment">
        <h3 class="text-ui text-text-secondary">Record a payment</h3>
        <AppField
          v-model="amount[0].value"
          label="Amount"
          numeric
          :disabled="!canPay"
          :help="`The plan costs ${money(detail.plan.price)} ${detail.plan.currency}.`"
          :error="payment.errors.value.amount"
        />
        <AppField
          v-model="reference[0].value"
          label="Reference"
          optional
          numeric
          :disabled="!canPay"
          help="A payment already on file under this reference is not recorded twice."
          :error="payment.errors.value.reference"
        />
        <div>
          <AppButton
            type="submit"
            :variant="primary === 'payment' ? 'filled' : 'outlined'"
            :disabled="!canPay"
            :busy="isPending"
          >
            Record a payment
          </AppButton>
        </div>
      </form>

      <!-- Change plan -->
      <form v-if="mayWrite" class="flex flex-col gap-4" @submit="onChangePlan">
        <h3 class="text-ui text-text-secondary">Change plan</h3>
        <AppChoiceField
          v-model="nextPlan[0].value"
          label="Plan"
          :options="planOptions"
          :disabled="row.state === 'cancelled'"
          help="Takes effect at the next payment. Choose the current plan again to undo it."
          :error="changePlan.errors.value.planId"
        />
        <div>
          <AppButton
            type="submit"
            variant="outlined"
            :disabled="row.state === 'cancelled'"
            :busy="isPending"
          >
            Change plan
          </AppButton>
        </div>
      </form>

      <!-- Redeem a promo code -->
      <form v-if="mayWrite" class="flex flex-col gap-4" @submit="onRedeem">
        <h3 class="text-ui text-text-secondary">Redeem a promo code</h3>
        <AppField
          v-model="promoCode[0].value"
          label="Promo code"
          numeric
          help="A redemption is spent when this succeeds, and nothing returns it."
          :error="redeem.errors.value.promoCode"
        />
        <div>
          <AppButton type="submit" variant="outlined" :busy="isPending">Redeem code</AppButton>
        </div>
      </form>

      <!-- Assign a referral programme -->
      <form v-if="mayAssign" class="flex flex-col gap-4" @submit="onAssign">
        <h3 class="text-ui text-text-secondary">Assign a referral programme</h3>
        <AppChoiceField
          v-model="programId[0].value"
          label="Programme"
          :options="programOptions"
          placeholder="Not assigned"
          help="Only future accruals move. What has already been paid out is history."
          :error="assign.errors.value.programId"
        />
        <div>
          <AppButton type="submit" variant="outlined" :busy="isPending">
            Assign programme
          </AppButton>
        </div>
      </form>

      <!-- Cancel -->
      <div v-if="mayWrite" class="flex flex-col gap-4">
        <h3 class="text-ui text-text-secondary">Cancel subscription</h3>
        <p class="text-caption text-text-muted">
          Access continues to the end of the paid period. There is no un-cancel.
        </p>
        <div>
          <AppButton
            variant="outlined"
            :disabled="!canCancel"
            :busy="isPending"
            @click="cancelling = true"
          >
            Cancel subscription
          </AppButton>
        </div>
      </div>

      <!-- Start a new subscription. Drawn only where the engine would accept it: in the three live
           states it is refused with ALREADY_SUBSCRIBED, and a control that is always refused is a
           control that teaches people to ignore refusals. -->
      <form v-if="mayWrite && canRestart" class="flex flex-col gap-4" @submit="onRestart">
        <h3 class="text-ui text-text-secondary">Start a subscription</h3>
        <AppChoiceField
          v-model="restartPlan[0].value"
          label="Plan"
          :options="planOptions"
          :error="restart.errors.value.planId"
        />
        <AppField
          v-model="restartPromo[0].value"
          label="Promo code"
          optional
          numeric
          :error="restart.errors.value.promoCode"
        />
        <div>
          <AppButton
            type="submit"
            :variant="primary === 'subscribe' ? 'filled' : 'outlined'"
            :busy="isPending"
          >
            Start a subscription
          </AppButton>
        </div>
      </form>
    </div>

    <AppConfirm
      v-model:open="cancelling"
      action="Cancel subscription"
      dismiss="Keep subscription"
      :title="cancelConsequence"
      :busy="isPending"
      @confirm="confirmCancel"
    />

    <AppConfirm
      v-model:open="redeeming"
      action="Redeem code"
      dismiss="Leave it"
      :title="`${redeem.values.promoCode} can be redeemed once. This cannot be undone.`"
      :busy="isPending"
      @confirm="confirmRedeem"
    />

    <AppConfirm
      v-model:open="restarting"
      action="Start a subscription"
      dismiss="Leave it as it is"
      :title="restartConsequence"
      :busy="isPending"
      @confirm="confirmRestart"
    />
  </section>
</template>
