/**
 * What time it is in the world on screen, which is not what time it is here. A world runs on real
 * time with an offset laid over it, and every relative time this panel prints is a subtraction
 * from it.
 */

/* MEASURED AGAINST THE BROWSER'S CLOCK INSTEAD, A WOUND-FORWARD WORLD READS AS A FULL ONE. Wind a
   month forward and every carried-forward `lastActiveAt` is up to a month in the browser's
   future. */

/* `formatSince` then sees a negative elapsed time and answers "just now" for all of them, while
   the backend reports a third of them as quiet: two screens over one world, disagreeing. */

/* TWO HALVES, AND THE SPLIT IS WHAT KEEPS THE LEAF COMPONENTS TESTABLE. `useWorldClock` is the
   query, mounted once in the frame; `useWorldNow` is the ticking number, which a table cell reads
   without a query client, an API client or a provider around it. */

import { useQuery } from '@tanstack/vue-query'
import { computed, onScopeDispose, ref, watch } from 'vue'

import type { ClockReading } from '@/api/client'
import { useApiClient } from '@/api/provide'
import { useAuthStore } from '@/stores/auth'

/** One second. The relative phrases change by the minute at best, so this is not for them — it is
 *  the panel's own clock reading, which a person watching it expects to move. */
const BEAT_MS = 1_000

/** Module-level, so a table of twelve rows and the panel in the sidebar share one interval and one
 *  value rather than each running a timer that says something very slightly different. */
const beat = ref(Date.now())
const offsetMs = ref(0)
let timer: ReturnType<typeof setInterval> | undefined
let holders = 0

function start(): void {
  holders += 1
  // Read on arrival rather than waited for. Without this the first render of anything that mounts
  // shows a value up to a beat old — and in a test, one from before the clock was set.
  beat.value = Date.now()
  timer ??= setInterval(() => {
    beat.value = Date.now()
  }, BEAT_MS)
}

function stop(): void {
  holders -= 1
  if (holders > 0 || timer === undefined) return
  clearInterval(timer)
  timer = undefined
}

/** Model time, ticking, as milliseconds since the epoch. Zero offset until a reading arrives,
 *  which is the browser's own clock — right for every world nobody has wound, and wrong for the
 *  moment before the answer lands. The alternative is a table with no times in it at all. */
export function useWorldNow() {
  start()
  onScopeDispose(stop)
  return computed(() => beat.value + offsetMs.value)
}

/** Forget the offset. A session ending takes the world with it, and the next one may be the base
 *  world at zero — an offset left behind would date every row on the first screen after it. */
export function forgetWorldClock(): void {
  offsetMs.value = 0
}

export function useWorldClock() {
  const client = useApiClient()
  const auth = useAuthStore()

  const query = useQuery<ClockReading>({
    queryKey: ['clock'],
    queryFn: ({ signal }) => client.clock(signal),
    // Guarded like every other query mounted in the frame: `queryClient.clear()` at the end of a
    // session refetches whatever is still observing, and a request with no token behind it turns
    // a deliberate ending into a session-expired banner.
    enabled: computed(() => auth.isAuthenticated),
    // The offset moves only when somebody winds it, and whoever does invalidates this key.
    staleTime: Number.POSITIVE_INFINITY,
  })

  watch(
    query.data,
    (reading) => {
      if (reading !== undefined) offsetMs.value = reading.offsetSeconds * 1000
    },
    { immediate: true },
  )

  return {
    ...query,
    now: useWorldNow(),
    offsetMs: computed(() => offsetMs.value),
    isSandbox: computed(() => query.data.value?.isSandbox ?? false),
  }
}
