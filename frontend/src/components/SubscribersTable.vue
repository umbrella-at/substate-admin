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
import { RouterLink, type RouteLocationRaw } from 'vue-router'

import StateChip from '@/components/StateChip.vue'
import { useWorldNow } from '@/composables/useWorldClock'
import { exactly, formatSince } from '@/domain/elapsed'
import { type SortField, type SubscriberSummary, type Sort } from '@/domain/subscribers'

/** The world's clock, not this browser's. A wound-forward world holds activity in the browser's
 *  future, and every one of those cells would otherwise read "just now". */
const now = useWorldNow()

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

// `columns()` rather than a bare array: it keeps each column's own value type instead of widening
// them all to their union, which is what makes `getValue()` typed per column inside the cells.
const columns = columnHelper.columns([
  columnHelper.accessor('displayName', {
    header: 'Subscriber',
    // The name is the link, and the row is not. A whole clickable row swallows selecting text in
    // it, has no keyboard equivalent that is not invented, and cannot be opened in a new tab
    // without a handler that reimplements what an anchor already does.
    cell: (context) =>
      h('div', { class: 'flex flex-col gap-1' }, [
        h(
          RouterLink,
          {
            to: { name: 'subscriber', params: { userId: context.row.original.userId } },
            class: 'rounded-control text-accent-text hover:underline focus-visible:underline',
          },
          () => context.getValue(),
        ),
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
      return h('span', { title: exactly(at) }, formatSince(at, now.value))
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
              <FlexRender :render="header.column.columnDef.header" :props="header.getContext()" />
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
