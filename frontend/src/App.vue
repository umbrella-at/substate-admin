<script setup lang="ts">
/**
 * The shell goes around the signed-in application and not around the login page.
 *
 * Decided from the route rather than from whether a session exists: a visitor whose token expired
 * while the page was open is still on a protected route for the moment before the guard moves
 * them, and keying this on the session would collapse the frame out from under them mid-navigation
 * — the layout jumping is how a person reads "something broke" rather than "you were signed out".
 */

import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import NotAllowed from '@/components/NotAllowed.vue'
import { TooltipProvider } from '@/components/ui/tooltip'

const route = useRoute()

const framed = computed(() => route.meta.requiresAuth !== false && route.name !== 'not-found')

/** The guard marks a route it refused rather than redirecting, and this is what reads the mark.
 *  Unread, it left a visitor at the address they asked for with nothing on it but the sidebar. */
const refused = computed(() => (route.meta.forbidden === true ? route.meta.permission : undefined))
</script>

<template>
  <!-- One provider for the application. It owns the delay before a tooltip opens and the rule that
       a second one opens at once while the first is still up, and both of those are answers about
       the interface rather than about any single chip. -->
  <TooltipProvider>
    <AppShell v-if="framed">
      <NotAllowed v-if="refused !== undefined" :permission="refused" />
      <RouterView v-else />
    </AppShell>
    <RouterView v-else />
  </TooltipProvider>
</template>
