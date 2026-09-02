/**
 * Which controls exist, which of them ask first, and what the answer says.
 *
 * THREE RULES ARE UNDER TEST AND THEY ARE INDEPENDENT. Permission decides whether a control is
 * drawn at all; state decides whether it is disabled; and reversibility decides whether it asks
 * before it acts. Each is asserted by enumerating what is on screen rather than by looking for the
 * control somebody was thinking about — a check that the wanted button is present cannot fail when
 * a button that should not be there is beside it.
 *
 * THE NOTICE IS RENDERED FROM THE ENGINE'S ANSWER. Three payment outcomes are 200s that changed
 * nothing, and a notice written from the button would say "Payment recorded" over a card that had
 * not moved — in green.
 */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type PlanSummary, type SubscriberDetail } from '@/api/client'
import { apiClientKey } from '@/api/provide'
import SubscriberOperations from '@/components/SubscriberOperations.vue'
import type { SubscriptionState } from '@/domain/states'
import { useAuthStore } from '@/stores/auth'

const PLANS: PlanSummary[] = [
  {
    id: 'monthly',
    price: 500,
    currency: 'USD',
    periodUnit: 'months',
    periodCount: 1,
    trialDays: 14,
    graceDays: 5,
  },
  {
    id: 'annual',
    price: 4200,
    currency: 'USD',
    periodUnit: 'months',
    periodCount: 12,
    trialDays: 30,
    graceDays: 7,
  },
]

const PROGRAMS = [
  { id: 'users', percent: 10, accrual: 'first_payment_only' as const },
  { id: 'partners', percent: 30, accrual: 'every_payment' as const },
]

function detail(
  state: SubscriptionState = 'active',
  over: Partial<SubscriberDetail> = {},
): SubscriberDetail {
  return {
    subscriber: {
      userId: 'sub-0001',
      displayName: 'Ada Lovelace',
      state,
      planId: 'monthly',
      accessUntil: '2026-10-16T00:00:00Z',
      expiresAt: '2026-10-16T00:00:00Z',
      trialEndsAt: state === 'trial' ? '2026-09-16T00:00:00Z' : null,
      graceEndsAt: state === 'grace' ? '2026-10-21T00:00:00Z' : null,
      cancelledAt: state === 'cancelled' ? '2026-09-02T00:00:00Z' : null,
      pendingPlanId: null,
      lastActiveAt: null,
      promoCode: null,
      referrerId: null,
    },
    plan: PLANS[0]!,
    promoCode: null,
    referrerId: null,
    referrerProgramId: null,
    referralProgramId: null,
    trialStartedAt: null,
    ...over,
  }
}

const operate = vi.fn()

function client(plans: PlanSummary[] = PLANS) {
  return {
    plans: vi.fn(async () => plans),
    referralPrograms: vi.fn(async () => PROGRAMS),
    operate,
  }
}

async function render(
  options: {
    state?: SubscriptionState
    permissions?: string[]
    detail?: Partial<SubscriberDetail>
    /** The catalogue the panel gets back. Empty stands for a request that failed. */
    plans?: PlanSummary[]
  } = {},
): Promise<ReturnType<typeof mount>> {
  const auth = useAuthStore()
  auth.adopt({
    user: {
      id: 'u-1',
      email: 'operator@example.com',
      isActive: true,
      createdAt: '2026-01-01T00:00:00Z',
      lastLoginAt: null,
    },
    role: { code: 'admin', name: 'Administrator' },
    permissions: options.permissions ?? ['subscribers.write', 'referrals.write'],
    kind: 'user',
    worldId: null,
  })

  // Attached to the document because the confirmation is a portal: Reka teleports it to the body,
  // and a detached mount has no body for it to reach.
  const wrapper = mount(SubscriberOperations, {
    props: { detail: detail(options.state ?? 'active', options.detail ?? {}) },
    attachTo: document.body,
    global: {
      plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
      provide: { [apiClientKey as symbol]: client(options.plans ?? PLANS) },
    },
  })
  await flushPromises()
  mounted = wrapper
  return wrapper
}

/** Every operation heading on screen, in the order it is drawn. */
function offered(wrapper: ReturnType<typeof mount>): string[] {
  return wrapper.findAll('h3').map((each) => each.text())
}

function button(wrapper: ReturnType<typeof mount>, label: string) {
  return wrapper.findAll('button').find((each) => each.text() === label)
}

/** The form under a heading. Submitted on the form rather than on its button: the handler is the
 *  form's, and a test that presses the button is testing event bubbling as well. */
function form(wrapper: ReturnType<typeof mount>, heading: string) {
  return wrapper.findAll('form').find((each) => each.find('h3').text() === heading)
}

/**
 * Wait for something to appear, then assert what did not.
 *
 * AN ABSENCE CANNOT BE WAITED FOR, which is what made the first version of this file flaky — one
 * run in five, on a different test each time. A submit here is several promises and a task deep:
 * VeeValidate validates, the mutation resolves through the query client's own scheduler, and the
 * notice renders. A fixed number of flushes sometimes landed before the end of that chain, and an
 * assertion that nothing had happened yet passed for the wrong reason — or the call arrived inside
 * the NEXT test and read there as the wrong operation having been called.
 *
 * So every test waits for the thing it expects and only then asserts the absence beside it.
 */
async function shown(text: string): Promise<void> {
  await vi.waitFor(() => expect(document.body.textContent ?? '').toContain(text))
}

/** Press the confirming button inside the open dialog.
 *
 *  Scoped to the dialog: the trigger keeps the same name and sits under the scrim, so an unscoped
 *  search finds the button nobody can press. */
async function confirmIn(action: string): Promise<void> {
  const dialog = document.querySelector('[role="alertdialog"]')
  const button = [...(dialog?.querySelectorAll('button') ?? [])].find(
    (each) => each.textContent?.trim() === action,
  )
  expect(button).toBeDefined()
  button?.click()
  await flushPromises()
}

let mounted: ReturnType<typeof mount> | null = null

beforeEach(() => {
  setActivePinia(createPinia())
  operate.mockReset()
})

// Unmounted, not erased. `attachTo: document.body` puts the component's container in the body, and
// clearing the body between tests took that node away from a Vue instance still holding it — every
// later render then failed inside `insertBefore`, which is the second half of why this file was
// flaky. Vue is asked to leave instead.
afterEach(() => {
  mounted?.unmount()
  mounted = null
  document.body.innerHTML = ''
})

describe('which controls exist', () => {
  // Enumerated. `subscribe` is absent in the three live states because the engine refuses it
  // there, and a control that is always refused teaches people to ignore refusals.
  it.each([
    [
      'trial',
      [
        'Record a payment',
        'Change plan',
        'Redeem a promo code',
        'Assign a referral programme',
        'Cancel subscription',
      ],
    ],
    [
      'active',
      [
        'Record a payment',
        'Change plan',
        'Redeem a promo code',
        'Assign a referral programme',
        'Cancel subscription',
      ],
    ],
    [
      'grace',
      [
        'Record a payment',
        'Change plan',
        'Redeem a promo code',
        'Assign a referral programme',
        'Cancel subscription',
      ],
    ],
    [
      'expired',
      [
        'Record a payment',
        'Change plan',
        'Redeem a promo code',
        'Assign a referral programme',
        'Cancel subscription',
        'Start a subscription',
      ],
    ],
    [
      'cancelled',
      [
        'Record a payment',
        'Change plan',
        'Redeem a promo code',
        'Assign a referral programme',
        'Cancel subscription',
        'Start a subscription',
      ],
    ],
  ] as const)('draws exactly what %s can be offered', async (state, headings) => {
    const wrapper = await render({ state })

    expect(offered(wrapper)).toEqual([...headings])
  })

  // A control somebody may never press is not offered: the guard would refuse it anyway, and an
  // invitation to a locked door is worse than no invitation.
  it('draws nothing at all for a visitor who may only read', async () => {
    const wrapper = await render({ permissions: ['subscribers.read'] })

    expect(wrapper.find('section').exists()).toBe(false)
  })

  // The one screen where the permission matrix has three tiers. Support may serve a customer and
  // may not change what a partner earns.
  it('leaves out the programme for somebody who may not change one', async () => {
    const wrapper = await render({ permissions: ['subscribers.write'] })

    expect(offered(wrapper)).toEqual([
      'Record a payment',
      'Change plan',
      'Redeem a promo code',
      'Cancel subscription',
    ])
  })

  it('draws only the programme for somebody who may only do that', async () => {
    const wrapper = await render({ permissions: ['referrals.write'] })

    expect(offered(wrapper)).toEqual(['Assign a referral programme'])
  })
})

describe('what a state refuses', () => {
  // Drawn and disabled rather than hidden: "you cannot pay for a cancelled subscription" is a
  // fact about this subscriber worth reading, and a missing control says nothing at all.
  it('refuses a payment and a plan change on a cancelled subscription, and says why', async () => {
    const wrapper = await render({ state: 'cancelled' })

    expect(button(wrapper, 'Record a payment')?.attributes('disabled')).toBeDefined()
    expect(button(wrapper, 'Change plan')?.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('a payment against it is filed and applies to nothing')
  })

  // Cancelling a cancelled subscription does nothing, and cancelling an expired one is undone by
  // the next tick.
  it.each([
    ['cancelled', true],
    ['expired', true],
    ['active', false],
  ] as const)('disables cancel on %s: %s', async (state, disabled) => {
    const wrapper = await render({ state })

    expect(button(wrapper, 'Cancel subscription')?.attributes('disabled') !== undefined).toBe(
      disabled,
    )
  })

  it('says nothing about what is unavailable when everything is', async () => {
    const wrapper = await render({ state: 'active' })

    expect(wrapper.text()).not.toContain('is cancelled:')
    expect(wrapper.text()).not.toContain('has ended.')
  })
})

describe('which controls ask first', () => {
  // The rule: confirm when the effect cannot be reversed from this card AND the consequence is
  // not already in what the operator typed. Payment, change of plan and programme are reversible
  // or already stated, so they act on the press.
  it.each([
    ['Record a payment', 'payment'],
    ['Change plan', 'change-plan'],
    ['Assign a referral programme', 'referral-program'],
  ])('acts on the press for %s', async (heading, path) => {
    operate.mockResolvedValue({ subscriber: detail(), events: [] })
    // The programme is prefilled from the card, so this form has a value to submit — which is
    // itself the reason the next test exists.
    const wrapper = await render({ detail: { referralProgramId: 'users' } })

    await form(wrapper, heading)?.trigger('submit')

    await vi.waitFor(() => expect(operate).toHaveBeenCalledTimes(1))
    expect(operate.mock.calls[0]?.[1]).toBe(path)
  })

  // The form refuses before the network does. A choice that was never made is not a refusal the
  // service should have to explain.
  it('does not send a programme nobody chose', async () => {
    const wrapper = await render()

    await form(wrapper, 'Assign a referral programme')?.trigger('submit')

    await shown('Choose a programme.')
    expect(operate).not.toHaveBeenCalled()
  })

  // The consequence is per state, and GRACE is where getting it wrong was worst: `accessUntil`
  // there is the end of the courtesy, and cancelling does not keep it — the paid boundary has
  // already passed, so the press ends access today. The dialog used to promise the week it takes.
  it('tells a grace period that cancelling stops access today', async () => {
    const wrapper = await render({ state: 'grace' })

    await button(wrapper, 'Cancel subscription')?.trigger('click')

    await shown('access stops today rather than at the end of the grace period')
  })

  it('sends a cancellation only after the dialog is confirmed', async () => {
    operate.mockResolvedValue({ subscriber: detail(), events: [] })
    const wrapper = await render({ state: 'active' })

    await button(wrapper, 'Cancel subscription')?.trigger('click')
    await shown('Keep subscription')
    expect(operate).not.toHaveBeenCalled()

    await confirmIn('Cancel subscription')

    await vi.waitFor(() => expect(operate).toHaveBeenCalledTimes(1))
    expect(operate.mock.calls[0]?.[1]).toBe('cancel')
  })

  it('sends a new subscription only after the dialog is confirmed', async () => {
    operate.mockResolvedValue({ subscriber: detail(), events: [] })
    const wrapper = await render({ state: 'cancelled' })

    await form(wrapper, 'Start a subscription')?.trigger('submit')
    await shown('Leave it as it is')
    expect(operate).not.toHaveBeenCalled()

    await confirmIn('Start a subscription')

    await vi.waitFor(() => expect(operate).toHaveBeenCalledTimes(1))
    expect(operate.mock.calls[0]?.[1]).toBe('subscribe')
  })

  it('sends a redemption only after the dialog is confirmed, and trims what it sends', async () => {
    operate.mockResolvedValue({ subscriber: detail(), events: [] })
    const wrapper = await render()

    const redeem = form(wrapper, 'Redeem a promo code')
    await redeem?.find('input').setValue('  LAUNCH20  ')
    await redeem?.trigger('submit')
    await shown('can be redeemed once')
    expect(operate).not.toHaveBeenCalled()

    await confirmIn('Redeem code')

    await vi.waitFor(() => expect(operate).toHaveBeenCalledTimes(1))
    // Trimmed. Zod shapes what `handleSubmit` hands over, and this path reads the raw model, so
    // the spaces would have travelled and come back as an unknown code.
    expect(operate.mock.calls[0]?.[2]).toEqual({ promoCode: 'LAUNCH20' })
  })

  // No un-cancel, and the consequence is a date the operator never typed.
  it('asks before cancelling, and names the date', async () => {
    const wrapper = await render()

    await button(wrapper, 'Cancel subscription')?.trigger('click')

    await shown('Access runs to 16 Oct 2026 and then stops.')
    // Never a button labelled `Cancel` on a dialog that cancels: one word for two opposite actions.
    expect(document.body.textContent).toContain('Keep subscription')
    expect(operate).not.toHaveBeenCalled()
  })
})

describe('what the form offers before it is pressed', () => {
  // A description that points at nothing is worse than none: a screen reader follows the id,
  // finds no element and says nothing, so the field reads as having no help at all.
  it('never describes a control by an element that is not there', async () => {
    // On a restartable card, because that is where the only control with neither help nor error
    // is drawn — the plan select on `Start a subscription`. Rendering the default state left the
    // one field that could dangle off the screen, and the first version of this test passed
    // against the defect it was written for.
    const wrapper = await render({ state: 'cancelled' })

    const dangling = wrapper
      .findAll('[aria-describedby]')
      .map((each) => each.attributes('aria-describedby'))
      .filter((id) => id !== undefined && document.getElementById(id) === null)

    expect(dangling).toEqual([])
  })

  // The engine charges `pending_plan_id or plan_id`, so a subscription with a change waiting is
  // priced on the plan it is moving TO. Prefilling the current one made a scheduled upgrade
  // underpay by default — the one mistake this prefill exists to prevent.
  it('prices a scheduled plan change against the plan the engine will charge', async () => {
    const wrapper = await render({
      detail: { subscriber: { ...detail().subscriber, pendingPlanId: 'annual' } },
    })

    const amount = form(wrapper, 'Record a payment')?.find('input')
    expect((amount?.element as HTMLInputElement).value).toBe('42.00')
    expect(form(wrapper, 'Record a payment')?.text()).toContain('42.00 USD (annual, scheduled)')
  })

  it('prices the current plan when no change is waiting', async () => {
    const wrapper = await render()

    const amount = form(wrapper, 'Record a payment')?.find('input')
    expect((amount?.element as HTMLInputElement).value).toBe('5.00')
    expect(form(wrapper, 'Record a payment')?.text()).toContain('The plan costs 5.00 USD.')
  })

  // `chosen === undefined` used to be read as "this plan has no trial", so a catalogue that had
  // not arrived made the dialog assert the opposite of what the press would do for somebody who
  // has never had one.
  it('promises no trial it cannot know about', async () => {
    const wrapper = await render({ state: 'cancelled', plans: [] })

    await form(wrapper, 'Start a subscription')?.trigger('submit')
    await shown('This clears the promo code')

    expect(document.body.textContent).not.toContain('starts unpaid')
    expect(document.body.textContent).not.toContain('free days')
  })

  // Not an empty select that refuses every submit: that blames the operator for a request that
  // failed somewhere else.
  it('disables a choice whose catalogue could not be read, and says so', async () => {
    const wrapper = await render({ plans: [] })

    expect(button(wrapper, 'Change plan')?.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('The plan catalogue could not be read.')
  })
})

describe('what the answer says', () => {
  // Neither `handleSubmit` nor the mutation refuses a second submit, and for the one operation
  // that is not idempotent a double press is two redemptions of one code.
  it('sends one request however many times the button is pressed', async () => {
    let release = (_: unknown) => {}
    operate.mockImplementation(() => new Promise((resolve) => (release = resolve)))
    const wrapper = await render()

    await form(wrapper, 'Record a payment')?.trigger('submit')
    await vi.waitFor(() => expect(operate).toHaveBeenCalledTimes(1))
    await form(wrapper, 'Record a payment')?.trigger('submit')
    await form(wrapper, 'Record a payment')?.trigger('submit')
    // Long enough for a second call to have arrived if one were coming: the first is already in
    // flight, so the thing being waited on is the absence of a second, and that has to be waited
    // out rather than waited for.
    for (let round = 0; round < 6; round += 1) {
      await flushPromises()
      await new Promise((resolve) => setTimeout(resolve, 0))
    }

    expect(operate).toHaveBeenCalledTimes(1)
    release({ subscriber: detail(), events: [] })
  })

  // Disabled means the action is unavailable, and while a cancellation is out `Keep subscription`
  // is exactly that: pressing it closed the dialog while the POST completed, so the name kept
  // nothing.
  it('refuses to dismiss a confirmation while its request is out', async () => {
    let release = (_: unknown) => {}
    operate.mockImplementation(() => new Promise((resolve) => (release = resolve)))
    const wrapper = await render()

    await button(wrapper, 'Cancel subscription')?.trigger('click')
    await shown('Keep subscription')
    await confirmIn('Cancel subscription')
    await vi.waitFor(() => expect(operate).toHaveBeenCalledTimes(1))

    const dismiss = [...document.querySelectorAll('[role="alertdialog"] button')].find(
      (each) => each.textContent?.trim() === 'Keep subscription',
    )
    expect(dismiss?.hasAttribute('disabled')).toBe(true)
    release({ subscriber: detail(), events: [] })
  })

  // The envelope names an input this form does not have — a payment refused for a pending plan
  // the engine no longer knows. Setting an error on a path that is not there loses the sentence.
  it('shows a refusal naming a field this form does not have', async () => {
    operate.mockRejectedValue(
      new ApiError(422, {
        code: 'UNKNOWN_PLAN',
        message: 'No plan is registered under that id.',
        field: 'planId',
      }),
    )
    const wrapper = await render()

    await form(wrapper, 'Record a payment')?.trigger('submit')

    await vi.waitFor(() =>
      expect(wrapper.find('[role="alert"]').text()).toContain('No plan is registered'),
    )
  })

  it('renders the notice from the events the engine emitted', async () => {
    operate.mockResolvedValue({
      subscriber: detail(),
      events: [
        { type: 'payment.recorded', occurredAt: '2026-09-02T05:09:00Z', payload: { amount: 500 } },
        {
          type: 'subscription.activated',
          occurredAt: '2026-09-02T05:09:00Z',
          payload: { planId: 'monthly', expiresAt: '2026-10-16T00:00:00Z' },
        },
      ],
    })
    const wrapper = await render()

    await form(wrapper, 'Record a payment')?.trigger('submit')

    await vi.waitFor(() => expect(wrapper.text()).toContain('A payment of 5.00 was recorded.'))
    expect(wrapper.text()).toContain('Now active. monthly runs to 16 Oct 2026.')
    expect(wrapper.find('[role="status"]').classes()).toContain('bg-success-bg')
  })

  // The outcome this rule was written for, and the one the first version of it got wrong: an
  // underpayment arrives BESIDE a `payment.recorded`, so asking whether any event moved something
  // answered yes and painted the whole thing green. Asking whether any event moved nothing is the
  // question that has the right answer for all three.
  it.each([
    ['a short payment', 'payment.underpaid', { amount: 499, expected: 500 }],
    ['a payment nothing matched', 'payment.unmatched', { amount: 500 }],
  ])(
    'says %s in the colour of a warning, beside the payment it was recorded as',
    async (_name, type, payload) => {
      operate.mockResolvedValue({
        subscriber: detail(),
        events: [
          {
            type: 'payment.recorded',
            occurredAt: '2026-09-02T05:09:00Z',
            payload: { amount: 500 },
          },
          { type, occurredAt: '2026-09-02T05:09:00Z', payload },
        ],
      })
      const wrapper = await render()

      await form(wrapper, 'Record a payment')?.trigger('submit')

      await vi.waitFor(() => expect(wrapper.find('[role="status"]').exists()).toBe(true))
      expect(wrapper.find('[role="status"]').classes()).toContain('bg-warning-bg')
      expect(wrapper.find('[role="status"]').classes()).not.toContain('bg-success-bg')
    },
  )

  // A 200 that changed nothing is not a success, and green over "Nothing changed" is a
  // contradiction the eye reads before the words.
  it('says a duplicate in the colour of a warning', async () => {
    operate.mockResolvedValue({
      subscriber: detail(),
      events: [
        {
          type: 'payment.duplicate',
          occurredAt: '2026-09-02T05:09:00Z',
          payload: { externalId: 'ref-1' },
        },
      ],
    })
    const wrapper = await render()

    await form(wrapper, 'Record a payment')?.trigger('submit')

    await vi.waitFor(() => expect(wrapper.text()).toContain('already on file. Nothing changed.'))
    expect(wrapper.find('[role="status"]').classes()).toContain('bg-warning-bg')
  })

  // The envelope names the input a refusal is about, and the sentence goes there and nowhere
  // else: a banner repeating the same words above the same form is one refusal read twice.
  it('puts a refusal about a value under the input it came from, and only there', async () => {
    operate.mockRejectedValue(
      new ApiError(422, {
        code: 'UNKNOWN_PLAN',
        message: 'No plan is registered under that id.',
        field: 'planId',
      }),
    )
    const wrapper = await render()

    await form(wrapper, 'Change plan')?.trigger('submit')

    await vi.waitFor(() =>
      expect(wrapper.findAll('[role="alert"]').map((each) => each.text())).toEqual([
        'No plan is registered under that id.',
      ]),
    )
  })

  // A refusal about the state of the world belongs above the form: there is no input to put it
  // under, and the operator is being told about the subscription rather than about what they typed.
  it('puts a refusal about the subscription above the form', async () => {
    operate.mockRejectedValue(
      new ApiError(409, {
        code: 'ALREADY_SUBSCRIBED',
        message: 'This subscriber already has a live subscription.',
        field: null,
      }),
    )
    const wrapper = await render({ state: 'expired' })

    await form(wrapper, 'Record a payment')?.trigger('submit')

    await vi.waitFor(() =>
      expect(wrapper.find('[role="alert"]').text()).toContain('already has a live subscription'),
    )
  })
})
