<script setup lang="ts">
/**
 * What is true about this subscriber right now.
 *
 * THE BOUNDARY ROWS ARE THE ONES THIS STATE HAS. An `ACTIVE` subscription has no grace end — not
 * an unknown one, none — so there is no row for it, and `boundaries()` is what makes that a type
 * rather than a promise: its union carries `graceEndsAt` on one arm only, so writing it anywhere
 * else does not compile.
 *
 * The em dash appears in exactly one place, and it is the same place the subscriber table already
 * uses it: a subscription that ended without a payment ever being made. Everywhere else an absent
 * value is a relation this subscriber does not have — no promo code, nobody who referred them —
 * and those rows keep their place and say `—` too, because the question applies and the answer is
 * nothing. A row that is not drawn means the question does not apply. Two absences, two marks.
 */

import { computed } from 'vue'

import type { SubscriberDetail } from '@/api/client'
import AppFact from '@/components/AppFact.vue'
import StateChip from '@/components/StateChip.vue'
import { exactly, formatSince } from '@/domain/elapsed'
import { moment, money } from '@/domain/events'
import { boundaries, boundaryRows } from '@/domain/subscription'

const props = defineProps<{ detail: SubscriberDetail }>()

const row = computed(() => props.detail.subscriber)

const dates = computed(() => boundaries(row.value))
const rows = computed(() => {
  const found = dates.value
  return found === null ? [] : boundaryRows(found)
})

/** The plan, priced. The currency label lives on the plan and the engine never reads it, so this
 *  is the one place on the card that may print it — an amount in a feed row has no currency in its
 *  payload and does not pretend to.
 *
 *  The period is written out rather than assembled from a count and a unit: `every 1 months` is
 *  what that assembly produces for the plan four subscribers in five are on. */
const price = computed(() => {
  const plan = props.detail.plan
  const unit = plan.periodUnit === 'days' ? 'day' : 'month'
  const every = plan.periodCount === 1 ? `every ${unit}` : `every ${plan.periodCount} ${unit}s`
  return `${money(plan.price)} ${plan.currency} ${every}`
})

/** The one duration on this card, and it keeps the phrasing the table's column argued for: the
 *  question is whether this person has been seen lately, and a date makes the reader subtract. */
const activity = computed(() => {
  const raw = row.value.lastActiveAt
  if (raw === null || raw === undefined) return { phrase: 'Never', exact: undefined }
  const at = new Date(raw)
  if (Number.isNaN(at.getTime())) return { phrase: '—', exact: undefined }
  return { phrase: formatSince(at, Date.now()), exact: exactly(at) }
})

const DASH = '—'
</script>

<template>
  <section class="rounded-card bg-surface-1 p-4">
    <header class="flex flex-wrap items-center gap-3">
      <h1 class="text-title text-text-primary">{{ row.displayName }}</h1>
      <StateChip :state="row.state" />
      <span class="font-numeric text-caption text-text-muted">{{ row.userId }}</span>
    </header>

    <!-- The panel and the service disagree: this state always has these dates and this row
         arrived without them. Said rather than drawn around, because a card that silently omits
         the dates reads as a subscriber with none. -->
    <p v-if="dates === null" class="mt-4 text-ui text-text-secondary">
      This subscription's dates could not be read. Reload the page; if it persists, the panel and
      the service disagree about what this state contains.
    </p>

    <dl v-else class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
      <AppFact v-for="boundary in rows" :key="boundary.label" :label="boundary.label" numeric>
        {{ moment(boundary.at) }}
      </AppFact>

      <AppFact label="Plan" numeric>{{ row.planId }}</AppFact>
      <AppFact label="Price">{{ price }}</AppFact>

      <AppFact v-if="row.pendingPlanId" label="Next plan" numeric>
        {{ row.pendingPlanId }}
      </AppFact>

      <AppFact label="Promo code" numeric>{{ detail.promoCode ?? DASH }}</AppFact>

      <AppFact label="Referred by" numeric>
        {{ detail.referrerId ?? DASH }}
        <!-- The programme that person is paid on, not this subscriber's. Two facts about two
             different people, and the field names used to disagree about which. -->
        <span v-if="detail.referrerProgramId" class="text-text-muted">
          · {{ detail.referrerProgramId }}
        </span>
      </AppFact>

      <AppFact label="Referral programme" numeric>
        {{ detail.referralProgramId ?? DASH }}
      </AppFact>

      <AppFact label="Last activity">
        <span :title="activity.exact">{{ activity.phrase }}</span>
      </AppFact>
    </dl>
  </section>
</template>
