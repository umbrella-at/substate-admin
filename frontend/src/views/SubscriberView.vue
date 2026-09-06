<script setup lang="ts">
/**
 * One subscriber: what is true, what can be done, and what has happened.
 *
 * TWO REQUESTS, FOUR STATES EACH, AND THEY ARE NOT THE SAME FOUR. The card comes from the engine
 * and the feed comes from Postgres, so one can be there while the other is not — a card over a
 * failed feed is a screen that still does its job, and a feed under a failed card is a history of
 * somebody the panel cannot describe. They are rendered independently for that reason rather than
 * behind one gate.
 *
 * A 404 IS NOT AN ERROR SCREEN. "There is no such subscriber" and "the request failed" are
 * different answers, and only one of them is worth a retry button. The id is usually in the
 * address bar because somebody edited it or followed a stale link, so the way out is back to the
 * table rather than another attempt at the same thing.
 *
 * The feed's page lives in component state and not in the URL, deliberately. The table's filters
 * are the question somebody wants to send to a colleague; which page of one person's history they
 * had scrolled to is not, and putting it in the address would make the back button walk it.
 */

import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { ApiError } from '@/api/client'
import { failureText } from '@/api/failure'
import AppButton from '@/components/AppButton.vue'
import AppNotice from '@/components/AppNotice.vue'
import SkeletonBlock from '@/components/SkeletonBlock.vue'
import SubscriberFacts from '@/components/SubscriberFacts.vue'
import SubscriberFeed from '@/components/SubscriberFeed.vue'
import SubscriberOperations from '@/components/SubscriberOperations.vue'
import TablePager from '@/components/TablePager.vue'
import { useSubscriber, useSubscriberEvents } from '@/composables/useSubscriber'

const route = useRoute()
const userId = computed(() => String(route.params['userId'] ?? ''))

const card = useSubscriber(userId)

const page = ref(1)
// A different subscriber is a different history, and page four of the last one is not where it
// starts. Watched rather than keyed on the route, so the component is not rebuilt for it.
watch(userId, () => {
  page.value = 1
})

const feed = useSubscriberEvents(userId, page)

const missing = computed(
  () => card.error.value instanceof ApiError && card.error.value.status === 404,
)

const reason = failureText
</script>

<template>
  <section class="flex flex-col gap-4 p-6">
    <!-- No such subscriber. Not the error state: there is nothing to retry, and the way out is the
         table rather than another attempt at an id that does not exist. It is also the one answer
         that takes the history with it: there is nobody here to have one. -->
    <div v-if="missing" class="flex max-w-reading flex-col items-start gap-4">
      <AppNotice role="warning">
        There is no subscriber <code class="font-numeric">{{ userId }}</code> in this world. The
        base world is rebuilt when the service restarts, so a link from before a restart can name
        somebody who is no longer here.
      </AppNotice>
      <AppButton variant="outlined" @click="$router.push({ name: 'subscribers' })">
        Back to subscribers
      </AppButton>
    </div>

    <template v-else>
      <!-- Loading, with nothing to show. The shape of the card that is coming: a header bar and the
           rows it will have, so the page does not resize when they arrive. -->
      <div v-if="card.isPending.value" class="flex flex-col gap-4" aria-busy="true">
        <span class="sr-only">Loading subscriber</span>
        <div class="rounded-card bg-surface-1 p-4">
          <!-- The title bar to come. `max-w-form` rather than a width of its own: the
             spacing scale has no step this wide, and inventing one for a placeholder
             is how a design file stops being where values come from. -->
          <SkeletonBlock class="h-8 max-w-form" />
          <div class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <SkeletonBlock v-for="fact in 6" :key="fact" class="h-8" />
          </div>
        </div>
      </div>

      <div v-else-if="card.isError.value" class="flex flex-col items-start gap-4">
        <AppNotice role="danger" assertive>{{ reason(card.error.value) }}</AppNotice>
        <AppButton variant="outlined" @click="() => void card.refetch()">Try again</AppButton>
      </div>

      <template v-else-if="card.data.value">
        <SubscriberFacts :detail="card.data.value" />
        <SubscriberOperations :detail="card.data.value" />
      </template>

      <!-- Beside the card rather than inside it. The two come from different places — the engine
           and Postgres — so a failed card is a reason to say so above the history, not to take
           the history away as well. -->
      <section class="flex flex-col gap-4">
        <h2 class="text-heading text-text-primary">History</h2>

        <div v-if="feed.isPending.value" class="flex flex-col gap-4" aria-busy="true">
          <span class="sr-only">Loading events</span>
          <!-- The feed's own frame and its own row: four of them at the height the events will
               have, built from the same padding rather than from a number. -->
          <div class="overflow-hidden rounded-panel border border-border">
            <div class="border-b border-border bg-surface-2 px-4 py-3">
              <SkeletonBlock class="h-3 max-w-form" />
            </div>
            <div
              v-for="line in 4"
              :key="line"
              class="border-b border-border px-4 py-3 last:border-b-0"
            >
              <SkeletonBlock class="h-4 max-w-reading" />
            </div>
          </div>
        </div>

        <div v-else-if="feed.isError.value" class="flex flex-col items-start gap-4">
          <AppNotice role="danger">{{ reason(feed.error.value) }}</AppNotice>
          <AppButton variant="outlined" @click="() => void feed.refetch()">Try again</AppButton>
        </div>

        <!-- Empty. Every subscriber in a seeded world has at least the event that created them, so
             this is what a subscriber created through this panel looks like for the first moment,
             and what a world nobody has ticked looks like. It says what would fill it, and names
             no direction: the operations panel is above this on a wide screen, below it on a
             narrow one, and absent entirely for somebody who may only read. -->
        <p v-else-if="feed.total.value === 0" class="max-w-reading text-ui text-text-secondary">
          Nothing has happened to this subscription yet. An operation on this card, or the next time
          the world moves, will appear here.
        </p>

        <!-- Not the same answer. Keyed on the page rather than on the history, this said nothing
             had ever happened and took the pager away with it, one page past the end. -->
        <div v-else-if="feed.rows.value.length === 0" class="flex flex-col items-start gap-3 py-4">
          <p class="max-w-reading text-ui text-text-secondary">
            There is no page {{ page }} of this history. It has {{ feed.total.value }} events on
            {{ feed.pageCount.value }} pages.
          </p>
          <AppButton variant="outlined" @click="page = 1">Back to the first page</AppButton>
        </div>

        <template v-else>
          <div :class="feed.isRefreshing.value ? 'opacity-60 transition-opacity' : ''">
            <SubscriberFeed :rows="feed.rows.value" :busy="feed.isRefreshing.value" />
          </div>
          <TablePager
            :page="page"
            :page-count="feed.pageCount.value"
            :total="feed.total.value"
            :busy="feed.isRefreshing.value"
            noun="event"
            @go="(next: number) => (page = next)"
          />
        </template>
      </section>
    </template>
  </section>
</template>
