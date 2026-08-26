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

const route = useRoute()

const framed = computed(() => route.meta.requiresAuth !== false && route.name !== 'not-found')
</script>

<template>
  <AppShell v-if="framed">
    <RouterView />
  </AppShell>
  <RouterView v-else />
</template>
