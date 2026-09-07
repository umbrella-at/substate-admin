<script setup lang="ts">
/**
 * The frame every signed-in screen sits in: a fixed sidebar and the page beside it.
 *
 * The navigation is filtered by permission, not merely disabled. A link to a page the visitor
 * would be refused is an invitation to a locked door, and the router's guard would refuse it
 * anyway — so the interface should not offer it. This is the same rule the guard follows, asked
 * one step earlier.
 *
 * `aria-current` rather than colour alone marks the page being looked at. The highlight is the
 * visible half of that and this is the half a screen reader gets.
 */

import { useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppButton from '@/components/AppButton.vue'
import AppNotice from '@/components/AppNotice.vue'
import ClockControl from '@/components/ClockControl.vue'
import { useApiClient } from '@/api/provide'
import { useWorldClock } from '@/composables/useWorldClock'
import type { PermissionCode } from '@/domain/permissions'
import { signOut } from '@/session'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const client = useApiClient()
const queryClient = useQueryClient()

/* THE WAY OUT IS IN THE FRAME, because the frame is on every screen. It used to be a button on the
   dashboard, so leaving from anywhere else meant navigating somewhere first to find it. */
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

/* READ HERE, NOT IN THE CONTROL, because the control is drawn only for whoever may press it.
   `support` and `viewer` hold no `demo.control` — so once anybody winds the base world, their
   Last active column measures against their own browser and reads "just now" for everybody. */

/* And SAID here for the same reason. A reading that never arrived is a fact about every time on
   the page, and it was announced only inside the control that most operators never see. */
const clock = useWorldClock()

interface Destination {
  name: string
  label: string
  /** Absent means every signed-in visitor may go there. */
  permission?: PermissionCode
  /** Routes that live under this entry and should light it up. A subscriber's card is a page of
   *  the subscriber section, and a menu that goes dark when you open one says it is not. */
  covers?: readonly string[]
}

const DESTINATIONS: Destination[] = [
  { name: 'dashboard', label: 'Dashboard' },
  {
    name: 'subscribers',
    label: 'Subscribers',
    permission: 'subscribers.read',
    covers: ['subscriber'],
  },
  { name: 'analytics', label: 'Analytics', permission: 'analytics.read' },
  { name: 'audit', label: 'Audit', permission: 'audit.read' },
  { name: 'users', label: 'Users and roles', permission: 'users.read' },
]

function isHere(destination: Destination): boolean {
  const current = String(route.name ?? '')
  return current === destination.name || (destination.covers?.includes(current) ?? false)
}

const visible = computed(() =>
  DESTINATIONS.filter(
    (destination) => destination.permission === undefined || auth.can(destination.permission),
  ),
)
</script>

<template>
  <div class="flex min-h-screen">
    <!-- The sidebar shrinks below `sm` rather than holding 240px of a 375px screen, which left
         the content column 135px wide. The links wrap; nothing is hidden behind a menu. -->
    <nav
      class="shrink-0 border-r border-border bg-surface-1 p-4 sm:w-sidebar"
      aria-label="Sections"
    >
      <span class="block px-3 py-2 text-heading text-text-primary">substate</span>
      <ul class="mt-4 flex flex-col gap-1">
        <li v-for="destination in visible" :key="destination.name">
          <RouterLink
            :to="{ name: destination.name }"
            class="block rounded-control px-3 py-2 text-ui text-text-secondary hover:bg-surface-2 hover:text-text-primary"
            :class="isHere(destination) ? 'bg-surface-2 text-text-primary' : ''"
            :aria-current="isHere(destination) ? 'page' : undefined"
          >
            {{ destination.label }}
          </RouterLink>
        </li>
      </ul>

      <!-- Drawn only for whoever may press it, like every link above. A control that is visible
           and refused is an invitation to a locked door. -->
      <ClockControl v-if="auth.can('demo.control')" />

      <!-- Whose session this is, and how to end it. Outlined, not filled: the last thing anybody
           here means to do must not be the loudest thing on the screen. -->
      <div class="mt-6 flex flex-col items-start gap-2 border-t border-border pt-4">
        <p class="px-3 text-caption text-text-muted">{{ auth.user?.email }}</p>
        <AppButton variant="plain" :busy="signingOut" @click="onSignOut">
          {{ signingOut ? 'Signing out…' : 'Sign out' }}
        </AppButton>
      </div>
    </nav>

    <div class="min-w-0 flex-1">
      <!-- Warning rather than danger: the screen still works and every absolute time on it is
           right. What is wrong is the relative ones, and the sentence says which. -->
      <div v-if="clock.isError.value" class="flex flex-col items-start gap-3 px-6 pt-6">
        <AppNotice role="warning">
          This world's clock could not be read, so the times on screen are measured against your own
          rather than against the world's.
        </AppNotice>
        <AppButton variant="outlined" @click="() => void clock.refetch()">Try again</AppButton>
      </div>
      <slot />
    </div>
  </div>
</template>
