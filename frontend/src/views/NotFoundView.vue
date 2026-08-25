<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <main class="grid min-h-screen place-items-center p-6">
    <div class="max-w-reading text-center">
      <h1 class="text-title text-text-primary">That page is not here</h1>
      <p class="mt-2 text-ui text-text-secondary">
        The address may have changed, or it may never have existed.
      </p>
      <RouterLink
        class="mt-6 inline-block rounded-control border border-border-strong px-4 py-2 text-ui text-text-secondary hover:border-accent-text hover:text-text-primary"
        to="/"
      >
        Go to the dashboard
      </RouterLink>
    </div>
  </main>
</template>
