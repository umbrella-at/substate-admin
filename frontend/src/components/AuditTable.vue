<script setup lang="ts">
/**
 * One page of the audit.
 *
 * Five columns and no payload column. What was asked for is rendered as the value it was — a plan
 * id, a code, an amount and its reference — rather than as the object it arrived in: a
 * per-action-shaped object in a table cell is the column that gets truncated to `{"planId": "an…`,
 * which is what the layout rules exist to prevent.
 *
 * The operator's email is set in the UI face, not mono. Typography reserves the mono cut for what
 * is compared down a column — money, dates, ids — and what an eye matches on an address is its
 * `name@domain` shape, which a monospace flattens into a wall over three hundred rows.
 *
 * Both identity cells filter rather than navigate. "Everything this operator did" and "everything
 * done to this subscriber" are the two questions this screen is opened with, and answering them
 * from the row is cheaper than a control that has to be told which operator exists.
 */

import type { AuditEntry } from '@/api/client'
import { ACTION_LABEL, requested } from '@/domain/audit'
import { instant } from '@/domain/events'

defineProps<{
  rows: AuditEntry[]
  /** A newer page is on its way. The rows below are real and one question out of date, which is
   *  what the other two tables in this application also say rather than emptying themselves. */
  busy?: boolean
  /** The world this panel is looking at, or null while the service has not said. A row from
   *  another world names a subscriber who no longer exists, and a row whose world is not yet known
   *  is not known to be either — so both get the id as text and neither gets a link. */
  liveWorld: string | null
}>()

defineEmits<{ filterActor: [string]; filterTarget: [string] }>()
</script>

<template>
  <div class="overflow-x-auto rounded-panel border border-border">
    <table class="w-full border-collapse text-ui" :aria-busy="busy === true">
      <thead>
        <tr class="border-b border-border bg-surface-2">
          <th scope="col" class="px-4 py-3 text-left text-caption font-medium text-text-secondary">
            When
          </th>
          <th scope="col" class="px-4 py-3 text-left text-caption font-medium text-text-secondary">
            Who
          </th>
          <th scope="col" class="px-4 py-3 text-left text-caption font-medium text-text-secondary">
            Action
          </th>
          <th scope="col" class="px-4 py-3 text-left text-caption font-medium text-text-secondary">
            Subscriber
          </th>
          <th scope="col" class="px-4 py-3 text-left text-caption font-medium text-text-secondary">
            Result
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.id"
          class="border-b border-border last:border-b-0 hover:bg-surface-1"
        >
          <td class="px-4 py-3 align-top font-numeric text-dense tabular-nums text-text-muted">
            {{ instant(row.occurredAt) }}
          </td>
          <td class="px-4 py-3 align-top">
            <!-- Not accent-coloured: accent is what a link looks like, and this narrows the page
                 rather than navigating. The underline on hover and on focus is the affordance. -->
            <button
              type="button"
              class="rounded-control text-text-primary hover:underline focus-visible:underline"
              @click="$emit('filterActor', row.actor.id)"
            >
              {{ row.actor.email }}
            </button>
          </td>
          <td class="px-4 py-3 align-top text-text-primary">
            {{ ACTION_LABEL[row.action] }}
            <span v-if="requested(row) !== ''" class="font-numeric text-dense text-text-muted">
              · {{ requested(row) }}
            </span>
          </td>
          <td class="px-4 py-3 align-top font-numeric text-dense">
            <!-- A link only into the world this panel is looking at. Rows outlive the world they
                 name — the base world is rebuilt at every restart — and a link into a world that
                 is gone answers 404 to somebody who followed it in good faith. -->
            <RouterLink
              v-if="row.worldId === liveWorld"
              :to="{ name: 'subscriber', params: { userId: row.targetId } }"
              class="rounded-control text-accent-text hover:underline focus-visible:underline"
            >
              {{ row.targetId }}
            </RouterLink>
            <button
              v-else
              type="button"
              class="rounded-control text-text-secondary hover:text-text-primary"
              :title="
                liveWorld === null
                  ? 'Which world this panel is showing is not known yet'
                  : `Recorded in world ${row.worldId}, which is not the one on screen`
              "
              @click="$emit('filterTarget', row.targetId)"
            >
              {{ row.targetId }}
            </button>
          </td>
          <td class="px-4 py-3 align-top">
            <!-- Nothing at all when it worked. A column of "ok" down three hundred rows is three
                 hundred words nobody reads, and the rows worth finding are the other ones. -->
            <span
              v-if="row.outcome === 'refused'"
              class="font-numeric text-caption text-danger-text"
            >
              {{ row.errorCode }}
            </span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
