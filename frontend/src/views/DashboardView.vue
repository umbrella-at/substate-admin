<script setup lang="ts">
/**
 * The one protected route.
 *
 * What it shows is deliberately small — the address someone signed in as, the role they hold, and
 * the permission codes that role grants. That is the literal proof that `/api/auth/me`, the role
 * table and the permission join all work, which is the only claim this round is entitled to make.
 *
 * Why it reads `/api/auth/me` through TanStack Query when the auth store already holds the answer:
 * the store's copy was taken once, before the application mounted, and it is session state — what
 * the router guard decides with. This panel is displaying SERVER state, which can be stale, can
 * fail to load and can be retried, and the four states below are real here rather than decorative.
 * A screen that fakes them from data it already has learns nothing, and the fifth screen — where
 * they matter and nobody has written them yet — is where that shows up.
 */

import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError, type MeResponse } from '@/api/client'
import { useApiClient } from '@/api/provide'
import AppButton from '@/components/AppButton.vue'
import AppNotice from '@/components/AppNotice.vue'
import PermissionChip from '@/components/PermissionChip.vue'
import SkeletonBlock from '@/components/SkeletonBlock.vue'
import { signOut } from '@/session'
import { useAuthStore } from '@/stores/auth'

const client = useApiClient()
const auth = useAuthStore()
const router = useRouter()
const queryClient = useQueryClient()

const {
  data: me,
  isPending,
  isError,
  error,
  isFetching,
  refetch,
} = useQuery<MeResponse>({
  queryKey: ['auth', 'me'],
  queryFn: ({ signal }) => client.me(signal),
  // Switched off the moment the session ends. `queryClient.clear()` empties the cache, and an
  // observer still mounted over an empty cache refetches at once — which would fire a request
  // with no token during sign-out, take the 401, and land the person on the login page under a
  // "your session ended" banner that describes something they did on purpose.
  enabled: computed(() => auth.isAuthenticated),
})

// The store took its copy before the application mounted. This is a fresher one, so a role edited
// while the tab was open takes effect on this load rather than the next.
watch(me, (fresh) => {
  if (fresh !== undefined) auth.adopt(fresh)
})

const UNREACHABLE = 'The service could not be reached.'

/** What to put on screen when the load failed. A 401 never arrives here — the client's session
 *  hook has already navigated by then — so this is a 5xx, a rate limit, or no network at all. */
const failure = computed(() => {
  const cause = error.value
  if (cause instanceof ApiError && cause.status < 500 && cause.message !== '') return cause.message
  return UNREACHABLE
})

const permissions = computed(() => me.value?.permissions ?? [])

const lastSignIn = computed(() => {
  const at = me.value?.user.lastLoginAt
  if (at === null || at === undefined) return null
  const parsed = new Date(at)
  if (Number.isNaN(parsed.getTime())) return null
  // The reader's own locale and timezone. The API speaks UTC ISO-8601 and this is the one place
  // that is turned into a wall clock, because it is the only place a person reads it.
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
    parsed,
  )
})

const signingOut = ref(false)

async function onSignOut(): Promise<void> {
  if (signingOut.value) return
  signingOut.value = true
  try {
    await signOut(client, queryClient)
    await router.replace({ name: 'login' })
  } finally {
    signingOut.value = false
  }
}
</script>

<template>
  <div class="min-h-screen">
    <header
      class="flex items-center justify-between gap-4 border-b border-border bg-surface-1 px-6 py-3"
    >
      <span class="text-heading text-text-primary">substate</span>
      <!-- Not filled. docs/design.md allows one filled element per screen and spends it on the
           screen's primary operation; this screen has none, so signing out — which is the last
           thing anyone here means to do — must not be the loudest thing on it. -->
      <AppButton :busy="signingOut" variant="outlined" @click="onSignOut">
        {{ signingOut ? 'Signing out…' : 'Sign out' }}
      </AppButton>
    </header>

    <main class="p-6">
      <h1 class="text-title text-text-primary">Dashboard</h1>

      <section class="mt-6 max-w-reading rounded-panel border border-border bg-surface-1 p-6">
        <h2 class="text-heading text-text-primary">Your session</h2>

        <!-- LOADING. The shape of what is coming, not a spinner in the middle of the page: two
             fields and a row of chips, in the places they will occupy, so nothing jumps when the
             answer lands. -->
        <template v-if="isPending">
          <p class="sr-only" role="status">Loading your session.</p>
          <div class="mt-4 grid gap-4">
            <div class="grid gap-2">
              <SkeletonBlock class="h-3 w-1/5" />
              <SkeletonBlock class="h-4 w-1/2" />
            </div>
            <div class="grid gap-2">
              <SkeletonBlock class="h-3 w-1/5" />
              <SkeletonBlock class="h-4 w-2/5" />
            </div>
            <div class="grid gap-2">
              <SkeletonBlock class="h-3 w-1/5" />
              <SkeletonBlock class="h-4 w-1/3" />
            </div>
            <div class="grid gap-2">
              <SkeletonBlock class="h-3 w-1/5" />
              <div class="flex flex-wrap gap-2">
                <SkeletonBlock class="h-6 w-1/4" />
                <SkeletonBlock class="h-6 w-1/3" />
                <SkeletonBlock class="h-6 w-1/5" />
                <SkeletonBlock class="h-6 w-1/4" />
              </div>
            </div>
          </div>
        </template>

        <!-- ERROR. What happened and what to do about it. Not an apology, and not "something went
             wrong": the person cannot act on a sentence that does not say what failed. -->
        <template v-else-if="isError">
          <AppNotice class="mt-4" assertive>{{ failure }}</AppNotice>
          <p class="mt-3 text-ui text-text-secondary">
            Your session is still valid — only this panel failed to load.
          </p>
          <AppButton class="mt-4" :busy="isFetching" variant="outlined" @click="refetch()">
            {{ isFetching ? 'Trying…' : 'Try again' }}
          </AppButton>
        </template>

        <!-- DATA. -->
        <template v-else-if="me">
          <dl class="mt-4 grid gap-4">
            <div>
              <dt class="text-caption text-text-muted">Signed in as</dt>
              <dd class="mt-1 text-ui text-text-primary">{{ me.user.email }}</dd>
            </div>
            <div>
              <dt class="text-caption text-text-muted">Role</dt>
              <dd class="mt-1 flex flex-wrap items-baseline gap-2">
                <span class="text-ui text-text-primary">{{ me.role.name }}</span>
                <!-- Mono: the code is an identifier, and identifiers are compared character by
                     character rather than read. -->
                <span class="text-dense font-numeric text-text-secondary">{{ me.role.code }}</span>
              </dd>
            </div>
            <div>
              <dt class="text-caption text-text-muted">Last sign-in</dt>
              <dd class="mt-1 text-ui font-numeric text-text-primary">
                <template v-if="lastSignIn !== null">{{ lastSignIn }}</template>
                <span v-else class="font-ui text-text-muted">This is the first one.</span>
              </dd>
            </div>
            <div>
              <dt class="text-caption text-text-muted">Permissions</dt>

              <!-- EMPTY. Reachable, and not a hypothetical: a role with no permissions granted yet
                   is an ordinary row in the roles table, and the person holding it can sign in
                   perfectly well and see exactly this. So it says what to do about it rather than
                   "no data" — which would describe the screen instead of the situation. -->
              <dd v-if="permissions.length === 0" class="mt-1">
                <p class="text-ui text-text-secondary">
                  The {{ me.role.name }} role grants nothing yet, so every page but this one is
                  closed. An administrator can add permissions to it.
                </p>
              </dd>

              <dd v-else class="mt-2 flex flex-wrap gap-2">
                <PermissionChip v-for="code in permissions" :key="code" :code="code" />
              </dd>
            </div>
          </dl>
        </template>
      </section>
    </main>
  </div>
</template>
