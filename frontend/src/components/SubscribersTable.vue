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
 *
 * NOT EVERY COLUMN IS SORTABLE, AND THE TWO THAT ARE NOT ARE THE CATEGORIES.
 *
 * State and Plan carry no arrow. An arrow is a direction over a quantity — it promises the column
 * runs from small to large — and neither of these is one. The arrow over State used to deliver the
 * alphabet, ACTIVE before CANCELLED before EXPIRED, which is an order over the letters of the
 * words and over nothing an administrator came here for; the arrow over Plan would have had to
 * invent one outright.
 *
 * Both are filtered from the panel above the table, and their headers are plain text. They were
 * briefly links to that panel, which was worse than doing nothing: the jump scrolled the page a
 * hundred pixels, put nothing new on screen, and read as a control that had broken. The filters
 * are in plain sight a finger's width above; a header that leads to them answers a question
 * nobody had.
 *
 * The state order that IS worth having lives beside those filters, written out as "sort by
 * urgency", because it is a name and not a direction.
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
import { computed, h } from 'vue'
import type { RouteLocationRaw } from 'vue-router'

import StateChip from '@/components/StateChip.vue'
import {
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
 * `Intl.RelativeTimeFormat` does the wording and the plural. A hand-written version of this is
 * twenty lines that agree with the rest of the formatting on the day they are written and diverge
 * on the first edit.
 *
 * `numeric: 'always'`, so there are no idioms — "1 day ago" rather than "yesterday", "1 month
 * ago" rather than "last month". Two reasons, and the second is the one that decides it. An idiom
 * is a calendar claim laid over arithmetic that is not calendar: elapsed÷24h is not a count of
 * days on a wall, so forty-seven hours would read as "yesterday" when the calendar calls it the
 * day before. And this is a column, read down: "yesterday" between "23 hours ago" and "2 days ago"
 * is the row the eye stops on, and stopping is the cost. The series matters more than any single
 * row reading naturally, because the reader is scanning rather than reading.
 *
 * THE BUCKETS ARE SIZED SO THAT EVERY ONE OF THEM STARTS AT 1, and the table below is what makes
 * that free rather than a compromise. `YEAR` is both the limit the months bucket stops at and the
 * unit the years bucket divides by, so the two cannot drift apart: whatever a month is worth, a
 * year is worth twelve of them, and the first count out of every bucket is exactly one. Nothing
 * here ever renders "today", "this month" or "this year", which is what `numeric: 'auto'` does
 * with a count of zero and how a row eleven months old would come to claim the current year.
 *
 * An earlier version of this comment claimed that invariant forced a thirty-day month, and cost
 * "five days of drift". Both were wrong. It forces nothing — the mean month works and holds every
 * boundary — and a thirty-day month did not drift by five days but over-reported by a whole unit
 * near every anniversary: 720 days read as "2 years ago" against a true one year eleven months,
 * and 3,600 days as "10 years ago" against nine years ten months. A phrase that says "ago" is a
 * floor, and a floor that rounds up is simply wrong.
 *
 * The month is therefore 30.436875 days, which is 365.2425 ÷ 12 — the Gregorian mean. The one
 * thing it costs: a gap of exactly thirty days now reads "30 days ago" rather than "last month",
 * because the days bucket runs to the real length of a month rather than to a round number.
 *
 */
const RELATIVE = new Intl.RelativeTimeFormat('en', { numeric: 'always' })

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
/** The Gregorian mean month, 365.2425 ÷ 12. Not thirty: see above. */
const MONTH = 30.436875 * DAY
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

/** The one row that is not "N units ago", and the only string here `Intl` does not produce. A
 *  count of seconds would be a precision this data does not have, and `format(0, 'second')` is
 *  "now", which reads as a claim that something is happening. A timestamp in the future — a clock
 *  askew on either end — lands here too, which is the least wrong thing to say about it. */
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
  columnHelper.accessor('accessUntil', {
    // Not "Expires". A subscription has three boundaries and only one is true at a time — a trial
    // ends at `trialEndsAt`, a courtesy period at `graceEndsAt`, everything else at `expiresAt` —
    // and a column named for one field while showing whichever is current is a column that lies
    // about itself. `substate` computes which; this says so.
    header: 'Access until',
    cell: (context) => formatDate(context.getValue()),
  }),
  columnHelper.accessor('lastActiveAt', {
    header: 'Last activity',
    // Ordinary text, left aligned, no mono. The other date column is a fixed-width figure meant to
    // be compared down the column; this is a phrase, and setting a phrase in a monospace and
    // pushing it to the right edge invites a comparison the words do not support.
    cell: (context) => {
      const raw = context.getValue()
      // Absent and unreadable are not the same thing, and only one of them is a fact about the
      // person. "Never" says they have not once turned up; an em dash says this cell has nothing
      // in it. Collapsing the two would let a malformed timestamp — a defect on the way here —
      // arrive as a confident claim about somebody's behaviour.
      if (raw === null || raw === undefined) {
        return h('span', { class: 'text-text-muted' }, 'Never')
      }
      const at = toDate(raw)
      if (at === null) return '—'
      return h('span', { title: exactly(at) }, formatSince(at, Date.now()))
    },
  }),
])

/** Which headers offer an order. Deliberately narrower than the sortable fields: `state` can be
 *  sorted, but not from here — see the note above. */
const SORTABLE_HEADERS = new Set<string>(['displayName', 'accessUntil', 'lastActiveAt'])

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

/** Only for the columns that offer an order from here. A category header announcing "none" would
 *  be telling a screen reader it is an unsorted sortable column, which is a different claim from
 *  not being sortable at all. */
type AriaSort = 'ascending' | 'descending' | 'none'

/** What `aria-sort` means is "the table is currently ordered by this column", which is a fact
 *  about the table rather than about whether this header offers the control. So State carries it
 *  whenever the urgency order is on, even though the order is turned on elsewhere — and Plan never
 *  carries it at all, because Plan can never be the column the table is ordered by. Marking Plan
 *  "none" would say it is a sortable column that happens to be unsorted. */
function ariaSort(field: string): AriaSort | undefined {
  if (props.sort.field === field) return props.sort.descending ? 'descending' : 'ascending'
  return SORTABLE_HEADERS.has(field) ? 'none' : undefined
}

/** Named, not drawn. The table is ordered by state and the header has to say so, but an arrow
 *  would say it in the one vocabulary this column does not have. */
const ORDERED_BY_URGENCY = computed(() => props.sort.field === 'state')
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
              v-if="SORTABLE_HEADERS.has(header.column.id)"
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
            <!-- A category, or a column whose order is set elsewhere. Plain text, because there
                 is nothing here to click and nothing here should look as though there is. -->
            <FlexRender
              v-else
              :render="header.column.columnDef.header"
              :props="header.getContext()"
            />

            <!-- After the chain, never inside it. A v-if between a v-else-if and its v-else breaks
                 the pair, and the v-else then renders unconditionally — which drew every header
                 label twice and passed every test, because the duplicate sits outside the link the
                 tests were reading. -->
            <span
              v-if="header.column.id === 'state' && ORDERED_BY_URGENCY"
              class="ml-2 font-normal text-text-muted"
            >
              {{ props.sort.descending ? 'least urgent first' : 'urgent first' }}
            </span>
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
