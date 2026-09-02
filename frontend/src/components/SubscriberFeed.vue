<script setup lang="ts">
/**
 * What has happened to this subscriber, newest first.
 *
 * Three cells, and the third is a sentence rather than the payload. The payload's keys differ per
 * type — `{"reason":"grace_ended"}`, `{"amount":500,"expected":2400}` — so showing it raw hands the
 * reader a translation job they will do worse and differently each time. The sentences live in one
 * total record in `domain/events`, which is also what renders the notice after an operation: one
 * vocabulary, used in the two places a person is told what the engine did.
 *
 * The instant is absolute and in the same form as the boundaries on the card above it. This feed
 * is read against those dates — did the payment arrive before the period ended — and "3 months
 * ago" beside "09 Sep 2026" makes the reader do the arithmetic to find out.
 */

import type { SubscriberEventPage } from '@/api/client'
import { instant, sentence } from '@/domain/events'

type Row = SubscriberEventPage['items'][number]

defineProps<{ rows: Row[]; busy: boolean }>()
</script>

<template>
  <div class="overflow-x-auto rounded-panel border border-border">
    <table class="w-full border-collapse text-ui" :aria-busy="busy">
      <caption class="sr-only">
        Events for this subscriber, newest first
      </caption>
      <thead>
        <tr class="border-b border-border bg-surface-2">
          <th scope="col" class="px-4 py-3 text-left text-caption font-medium text-text-secondary">
            When
          </th>
          <th scope="col" class="px-4 py-3 text-left text-caption font-medium text-text-secondary">
            Event
          </th>
          <th scope="col" class="px-4 py-3 text-left text-caption font-medium text-text-secondary">
            What happened
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.id" class="border-b border-border last:border-b-0">
          <td class="px-4 py-3 align-top font-numeric text-dense tabular-nums text-text-muted">
            {{ instant(row.occurredAt) }}
          </td>
          <td class="px-4 py-3 align-top">
            <!-- A fact label, not a state chip: the round shape belongs to the five subscription
                 states and every other pill on screen would spend that recognition. Neutral for the
                 same reason — green already means ACTIVE. -->
            <span
              class="inline-block rounded-control bg-surface-2 px-chip-x py-chip-y font-numeric text-caption text-text-secondary"
            >
              {{ row.type }}
            </span>
          </td>
          <td class="px-4 py-3 align-top text-text-primary">{{ sentence(row) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
