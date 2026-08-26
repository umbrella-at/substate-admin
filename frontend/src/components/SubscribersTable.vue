<script setup lang="ts">
/**
 * The subscriber table.
 *
 * Everything the table models — which rows, in what order, on which page — is decided by the API,
 * so this is built with `manualSorting`, `manualPagination` and `manualFiltering` all on. What
 * TanStack Table is here for is column definitions as data: the header, the accessor, whether the
 * column can be sorted and how a cell is drawn all live in one array, and adding a column is one
 * entry rather than an edit in three places that have to agree. Its own sorting and paging models
 * are not used, and turning them on would give the table a second opinion about the order of rows
 * that the server has already settled.
 *
 * Sorting is a link, not a click handler. Each sortable header is a real anchor to the address the
 * click would produce, so the column order can be opened in a new tab, copied, and read by
 * anything that follows links — and the keyboard gets it for free instead of through a handler.
 */

import {
  coreCellsFeature,
  coreColumnsFeature,
  coreHeadersFeature,
  coreRowModelsFeature,
  coreRowsFeature,
  coreTablesFeature,
  createColumnHelper,
  FlexRender,
  useTable,
} from '@tanstack/vue-table'
import { h } from 'vue'
import type { RouteLocationRaw } from 'vue-router'

import StateChip from '@/components/StateChip.vue'
import {
  SORT_FIELDS,
  type SortField,
  type SubscriberSummary,
  type Sort,
} from '@/domain/subscribers'

const props = defineProps<{
  rows: SubscriberSummary[]
  sort: Sort
  /** Where clicking a given column header would lead. Built by the view, which owns the URL. */
  sortHref: (field: SortField) => RouteLocationRaw
  busy: boolean
}>()

/** Core only. The table models nothing here: which rows, in what order and on which page are all
 *  decided by the API, so the sorting, pagination and filtering features are not enabled rather
 *  than enabled and overridden by a `manual*` flag. A feature that is switched on has an opinion
 *  about the order of rows, and there is no second opinion to have. */
const FEATURES = {
  coreCellsFeature,
  coreColumnsFeature,
  coreHeadersFeature,
  coreRowModelsFeature,
  coreRowsFeature,
  coreTablesFeature,
}

const columnHelper = createColumnHelper<typeof FEATURES, SubscriberSummary>()

/** A date as a person would check it: absolute, unambiguous between British and American
 *  readings, and the same width down the column so the eye can compare without reading. An em
 *  dash where there is no date, because "—" reads as "not applicable" while an empty cell reads
 *  as a bug.
 *
 *  Assembled from parts rather than taken whole, for one word. Every day-first English locale
 *  abbreviates September as "Sept" and every other month to three letters, so one row in twelve
 *  is a character wider than the rest and the column stops lining up — which is the entire reason
 *  for choosing a fixed-width form. Month-first locales give "Sep" and cost the unambiguous
 *  order, which is the more expensive thing to lose. */
const DATE = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

/** One place that decides whether there is a date at all, so a null, an empty string and a value
 *  the API should never have sent are handled once rather than in each column. */
function toDate(value: string | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null
  const at = new Date(value)
  return Number.isNaN(at.getTime()) ? null : at
}

function formatDate(value: string | null | undefined): string {
  const at = toDate(value)
  if (at === null) return '—'
  return DATE.formatToParts(at)
    .map((part) => (part.type === 'month' ? part.value.slice(0, 3) : part.value))
    .join('')
}

/* HOW LONG AGO, RATHER THAN WHEN.
 *
 * The activity column answers one question — recently or not — and a bare date makes the reader
 * do the subtraction. "9 days ago" is the answer; "17 Aug 2026" is the raw material for it.
 *
 * `Intl.RelativeTimeFormat` does the wording, including the plural and the idiom: `numeric:
 * 'auto'` is what turns one day into "yesterday" and one month into "last month". A hand-written
 * version of this is twenty lines that agree with the rest of the formatting on the day they are
 * written and diverge on the first edit.
 *
 * THE BUCKETS ARE SIZED SO THAT EVERY ONE OF THEM STARTS AT 1. A month of thirty days and a year
 * of twelve of those, rather than 365 days: with a calendar year the months bucket would end at
 * 360 days while the years bucket divided by 365, and the first value out of it would be zero —
 * which `numeric: 'auto'` renders as "this year" for something eleven months old. The cost is
 * five days of drift in a column that answers "recently or not", and the alternative is either
 * that bug or the calendar arithmetic this exists to avoid.
 */
const RELATIVE = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
const MONTH = 30 * DAY
const YEAR = 12 * MONTH

/** Each row: the elapsed time this bucket stops at, the unit it counts in, and how long that unit
 *  is. Read in order, first match wins. */
const SCALE: readonly (readonly [number, Intl.RelativeTimeFormatUnit, number])[] = [
  [HOUR, 'minute', MINUTE],
  [DAY, 'hour', HOUR],
  [MONTH, 'day', DAY],
  [YEAR, 'month', MONTH],
  [Number.POSITIVE_INFINITY, 'year', YEAR],
]

/** The one string `Intl` will not produce. `format(0, 'second')` is "now", which reads as a claim
 *  that something is happening; the column means "nothing since a moment ago". A timestamp in the
 *  future — a clock askew on either end — lands here too, which is the least wrong thing to say
 *  about it. */
const JUST_NOW = 'just now'

function formatSince(at: Date, now: number): string {
  const elapsed = now - at.getTime()
  if (elapsed < MINUTE) return JUST_NOW
  for (const [limit, unit, step] of SCALE) {
    if (elapsed < limit) return RELATIVE.format(-Math.floor(elapsed / step), unit)
  }
  /* v8 ignore next -- the last bucket has no upper bound, so the loop always returns */
  return JUST_NOW
}

/** The exact moment, for the hover. ISO and UTC: the relative phrase is the answer and this is
 *  the evidence, so it should be unambiguous rather than readable. Milliseconds are dropped —
 *  they are precision this data does not have. UTC like every other date in this table. */
function exactly(at: Date): string {
  return at.toISOString().replace(/\.\d{3}Z$/u, 'Z')
}

// `columns()` rather than a bare array: it keeps each column's own value type instead of widening
// them all to their union, which is what makes `getValue()` typed per column inside the cells.
const columns = columnHelper.columns([
  columnHelper.accessor('displayName', {
    header: 'Subscriber',
    cell: (context) =>
      h('div', { class: 'flex flex-col gap-1' }, [
        h('span', { class: 'text-text-primary' }, context.getValue()),
        h(
          'span',
          { class: 'font-numeric text-caption text-text-muted' },
          context.row.original.userId,
        ),
      ]),
  }),
  columnHelper.accessor('state', {
    header: 'State',
    cell: (context) => h(StateChip, { state: context.getValue() }),
  }),
  columnHelper.accessor('planId', {
    header: 'Plan',
    cell: (context) => h('span', { class: 'font-numeric text-dense' }, context.getValue()),
  }),
  columnHelper.accessor('expiresAt', {
    header: 'Expires',
    cell: (context) => formatDate(context.getValue()),
  }),
  columnHelper.accessor('lastActiveAt', {
    header: 'Last activity',
    // Ordinary text, left aligned, no mono. The other date column is a fixed-width figure meant to
    // be compared down the column; this is a phrase, and setting a phrase in a monospace and
    // pushing it to the right edge invites a comparison the words do not support.
    cell: (context) => {
      const at = toDate(context.getValue())
      if (at === null) {
        // Not an em dash. "Never" is a fact about the person — they have not once turned up —
        // where "—" only says this cell has nothing in it.
        return h('span', { class: 'text-text-muted' }, 'Never')
      }
      return h('span', { title: exactly(at) }, formatSince(at, Date.now()))
    },
  }),
])

const sortable = new Set<string>(SORT_FIELDS)

const table = useTable({
  features: FEATURES,
  columns,
  get data() {
    return props.rows
  },
  // Keyed by the subscriber rather than by position, so a row keeps its identity across a page
  // of new data and Vue reuses the element for the same person instead of the same index.
  getRowId: (row: SubscriberSummary) => row.userId,
})

/** Drawn only for the column actually sorted, so the header row shows one arrow rather than a
 *  row of them with one highlighted. */
function arrow(field: string): string {
  if (props.sort.field !== field) return ''
  return props.sort.descending ? '↓' : '↑'
}

function ariaSort(field: string): 'ascending' | 'descending' | 'none' {
  if (props.sort.field !== field) return 'none'
  return props.sort.descending ? 'descending' : 'ascending'
}
</script>

<template>
  <!-- The horizontal scroll is on the table's own container. A page that scrolls sideways moves
       the filters and the heading off screen along with the columns. -->
  <div class="overflow-x-auto rounded-panel border border-border">
    <table class="w-full border-collapse text-ui" :aria-busy="props.busy">
      <thead>
        <tr class="border-b border-border bg-surface-2">
          <th
            v-for="header in table.getHeaderGroups()[0]?.headers ?? []"
            :key="header.id"
            scope="col"
            class="px-4 py-3 text-left text-caption font-medium text-text-secondary"
            :aria-sort="ariaSort(header.column.id)"
          >
            <RouterLink
              v-if="sortable.has(header.column.id)"
              :to="props.sortHref(header.column.id as SortField)"
              class="inline-flex items-center gap-1 rounded-control hover:text-text-primary"
            >
              <FlexRender
                :render="header.column.columnDef.header"
                :props="header.getContext()"
              />
              <!-- The arrow is decoration; aria-sort on the cell is what a screen reader reads,
                   so this is hidden rather than described twice. -->
              <span aria-hidden="true" class="text-text-muted">
                {{ arrow(header.column.id) }}
              </span>
            </RouterLink>
            <FlexRender
              v-else
              :render="header.column.columnDef.header"
              :props="header.getContext()"
            />
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in table.getRowModel().rows"
          :key="row.id"
          class="border-b border-border last:border-b-0 hover:bg-surface-1"
        >
          <td
            v-for="cell in row.getAllCells()"
            :key="cell.id"
            class="px-4 py-3 align-middle text-text-secondary"
          >
            <FlexRender :render="cell.column.columnDef.cell" :props="cell.getContext()" />
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
