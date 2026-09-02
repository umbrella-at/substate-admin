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
import { computed, ref, watch } from 'vue'
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

/** A choice with nothing to choose from is disabled and says so. An empty select that refuses
 *  every submit blames the operator for a request that failed somewhere else. */
const NO_CATALOGUE = 'The plan catalogue could not be read. Reload the page to try again.'
const NO_PROGRAMMES = 'The programme list could not be read. Reload the page to try again.'
const plansMissing = computed(() => planOptions.value.length === 0)
const programsMissing = computed(() => programOptions.value.length === 0)
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
  /** Put a refusal under the input it is about. Returns false when this form has no such input,
   *  which sends the sentence to the banner instead of dropping it. */
  onField?: (field: string, message: string) => boolean
}

async function run(attempt: Attempt): Promise<void> {
  // One operation at a time. `handleSubmit` does not refuse a second submit and neither does the
  // mutation, so without this a double press is two POSTs — and for the one operation that is not
  // idempotent that is two redemptions of one code.
  if (isPending.value) return
  notice.value = null
  try {
    const result = await mutateAsync({ operation: attempt.operation, body: attempt.body ?? {} })
    // Green over "Nothing changed" is a contradiction the eye reads before the words. ANY of the
    // three makes the answer a warning, rather than none of them: `payment.underpaid` and
    // `payment.unmatched` both arrive beside a `payment.recorded`, so asking whether every event
    // moved nothing painted the two outcomes this rule exists for in the colour of a success.
    const stalled = result.events.some((event) => CHANGED_NOTHING.has(event.type))
    notice.value =
      result.events.length === 0
        ? { role: attempt.otherwiseRole, lines: [attempt.otherwise] }
        : { role: stalled ? 'warning' : 'success', lines: result.events.map(sentence) }
  } catch (failure) {
    if (!(failure instanceof ApiError)) {
      notice.value = { role: 'danger', lines: [UNREACHABLE] }
      return
    }
    // The envelope names the input a refusal is about, which is the whole reason it carries a
    // field — and when it does, the sentence goes THERE and nowhere else. A banner repeating the
    // same words above the same form is one refusal read twice, and the login page's rule is the
    // same one: a form says what is wrong in one place.
    // `onField` reports whether it recognised the name. The envelope's field comes from the
    // backend's FIELD_FOR, which names inputs these forms declare — but a refusal naming one they
    // do not would otherwise vanish, so the banner is the fallback rather than the alternative.
    const landed =
      failure.field !== null &&
      attempt.onField !== undefined &&
      attempt.onField(failure.field, failure.message)
    if (landed) return
    notice.value = { role: 'danger', lines: [failure.message] }
  }
}

/**
 * Put a refusal under the input it names, and say whether there was one.
 *
 * VeeValidate types a field path as a literal union of the form's own keys, so a name that arrives
 * over the wire cannot be one without a cast. The cast is made here, once, guarded by a check the
 * types cannot make: the field has to be a key of this form's values, or the caller is told no and
 * shows the sentence in the banner instead of losing it.
 */
function under(
  form: { values: Record<string, unknown>; setFieldError: (path: never, message: string) => void },
  field: string,
  message: string,
): boolean {
  if (!Object.hasOwn(form.values, field)) return false
  form.setFieldError(field as never, message)
  return true
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

/** What the next payment will actually be priced against.
 *
 *  `apply_payment` charges `self._plan(pending_plan_id or plan_id)`, so a subscription with a
 *  change waiting is priced on the plan it is moving TO. Prefilling the current plan's price would
 *  have made a scheduled upgrade underpay by default, which is the one mistake this prefill exists
 *  to prevent. */
const duePlan = computed(() => {
  const pending = props.detail.subscriber.pendingPlanId
  const found = pending === null ? undefined : (plans.value ?? []).find((p) => p.id === pending)
  return found ?? props.detail.plan
})

const payment = useForm({
  validationSchema: toTypedSchema(
    // Not `.optional()`: an optional field makes its ref `string | undefined`, and a text
    // input bound to undefined is an input whose value the form cannot write back. Empty is
    // what "not given" looks like in a text field, and the submit turns it into null.
    z.object({ amount: amountShape, reference: z.string().trim().max(128) }),
  ),
  initialValues: { amount: (props.detail.plan.price / 100).toFixed(2), reference: '' },
  // Kept in step with the catalogue: the pending plan's price is only known once /plans answers.
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
    onField: (field, message) => under(payment, field, message),
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
    onField: (field, message) => under(changePlan, field, message),
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
  // Trimmed here as well as in the schema. Zod's `.trim()` shapes what `handleSubmit` hands over,
  // and this path reads the raw model instead — so ` LAUNCH20 ` would have been sent with its
  // spaces and refused as an unknown code.
  const code = (redeem.values.promoCode ?? '').trim()
  await run({
    operation: 'redeem',
    body: { promoCode: code },
    otherwise: `${code} was redeemed.`,
    otherwiseRole: 'success',
    onField: (field, message) => under(redeem, field, message),
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
    onField: (field, message) => under(assign, field, message),
  }),
)

// ------------------------------------------------------------------------------------------
// Cancel. A dialog: no un-cancel, and the consequence is a date nobody typed.
// ------------------------------------------------------------------------------------------

const cancelling = ref(false)

/**
 * What cancelling will actually do to THIS subscription.
 *
 * Not `accessUntil`, which is where this was wrong. In GRACE that field is the end of the
 * courtesy, and cancelling does not keep it: `cancel` sets the state and leaves `expires_at`
 * alone, so a cancelled record's access runs to the paid boundary — which in GRACE has already
 * passed. The dialog promised a week that the press would take away.
 */
const cancelConsequence = computed(() => {
  const card = row.value
  if (card.state === 'trial') {
    const ends = moment(card.trialEndsAt ?? null)
    return `The trial ends on ${ends} as planned, and nothing will renew after it.`
  }
  if (card.state === 'grace') {
    return `The paid period ended on ${moment(card.expiresAt ?? null)}, so access stops today rather than at the end of the grace period. Renewal will not be attempted.`
  }
  return `Access runs to ${moment(card.expiresAt ?? null)} and then stops. Renewal will not be attempted.`
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
  const cleared = 'This clears the promo code and any pending plan change.'
  // Silence rather than a guess when the catalogue has not arrived. `chosen === undefined` was
  // read as "this plan has no trial", so a failed /plans made the dialog assert the opposite of
  // what the press would do for somebody who has never had one.
  if (chosen === undefined) return cleared
  if (fresh && chosen.trialDays > 0) {
    return `${cleared} ${chosen.id} starts with ${chosen.trialDays} free days.`
  }
  return `${cleared} It starts unpaid, waiting for a first payment.`
})

async function confirmRestart(): Promise<void> {
  const code = (restart.values.promoCode ?? '').trim()
  await run({
    operation: 'subscribe',
    body: { planId: restart.values.planId, promoCode: code === '' ? null : code },
    otherwise: 'A new subscription was started.',
    otherwiseRole: 'success',
    onField: (field, message) => under(restart, field, message),
  })
  restarting.value = false
}

// ------------------------------------------------------------------------------------------
// What this state allows.
// ------------------------------------------------------------------------------------------

/** The sentence under the amount, and the value in it. Both follow the plan the engine will
 *  charge against rather than the one the subscription is on today. */
const dueHelp = computed(() => {
  const plan = duePlan.value
  const scheduled = plan.id === props.detail.plan.id ? '' : ` (${plan.id}, scheduled)`
  return `The plan costs ${money(plan.price)} ${plan.currency}${scheduled}.`
})

watch(duePlan, (plan) => {
  // Only while nobody has typed. Overwriting an amount somebody entered because a catalogue
  // arrived is the panel taking the keyboard away.
  if (!payment.meta.value.dirty) payment.setFieldValue('amount', (plan.price / 100).toFixed(2))
})

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
          :help="dueHelp"
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
            {{ isPending ? 'Recording the payment…' : 'Record a payment' }}
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
          :disabled="row.state === 'cancelled' || plansMissing"
          :help="
            plansMissing
              ? NO_CATALOGUE
              : 'Takes effect at the next payment. Choose the current plan again to undo it.'
          "
          :error="changePlan.errors.value.planId"
        />
        <div>
          <AppButton
            type="submit"
            variant="outlined"
            :disabled="row.state === 'cancelled' || plansMissing"
            :busy="isPending"
          >
            {{ isPending ? 'Changing the plan…' : 'Change plan' }}
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
          <AppButton type="submit" variant="outlined" :busy="isPending">{{
            isPending ? 'Redeeming the code…' : 'Redeem code'
          }}</AppButton>
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
          :disabled="programsMissing"
          :help="
            programsMissing
              ? NO_PROGRAMMES
              : 'Only future accruals move. What has already been paid out is history.'
          "
          :error="assign.errors.value.programId"
        />
        <div>
          <AppButton type="submit" variant="outlined" :disabled="programsMissing" :busy="isPending">
            {{ isPending ? 'Assigning the programme…' : 'Assign programme' }}
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
            {{ isPending ? 'Cancelling the subscription…' : 'Cancel subscription' }}
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
          :disabled="plansMissing"
          :help="plansMissing ? NO_CATALOGUE : undefined"
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
            :disabled="plansMissing"
            :busy="isPending"
          >
            {{ isPending ? 'Starting the subscription…' : 'Start a subscription' }}
          </AppButton>
        </div>
      </form>
    </div>

    <AppConfirm
      v-model:open="cancelling"
      action="Cancel subscription"
      busy-action="Cancelling the subscription…"
      dismiss="Keep subscription"
      :title="cancelConsequence"
      :busy="isPending"
      @confirm="confirmCancel"
    />

    <AppConfirm
      v-model:open="redeeming"
      action="Redeem code"
      busy-action="Redeeming the code…"
      dismiss="Leave it"
      :title="`${(redeem.values.promoCode ?? '').trim()} can be redeemed once. This cannot be undone.`"
      :busy="isPending"
      @confirm="confirmRedeem"
    />

    <AppConfirm
      v-model:open="restarting"
      action="Start a subscription"
      busy-action="Starting the subscription…"
      dismiss="Leave it as it is"
      :title="restartConsequence"
      :busy="isPending"
      @confirm="confirmRestart"
    />
  </section>
</template>
