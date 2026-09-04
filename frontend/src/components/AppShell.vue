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

import { computed } from 'vue'
import { useRoute } from 'vue-router'

import ClockControl from '@/components/ClockControl.vue'
import { useWorldClock } from '@/composables/useWorldClock'
import type { PermissionCode } from '@/domain/permissions'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()

/* READ HERE, NOT IN THE CONTROL, because the control is drawn only for whoever may press it.
   `support` and `viewer` hold no `demo.control` — so once anybody winds the base world, their
   Last active column measures against their own browser and reads "just now" for everybody. */
useWorldClock()

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
    <nav class="w-sidebar shrink-0 border-r border-border bg-surface-1 p-4" aria-label="Sections">
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
    </nav>

    <div class="min-w-0 flex-1">
      <slot />
    </div>
  </div>
</template>
