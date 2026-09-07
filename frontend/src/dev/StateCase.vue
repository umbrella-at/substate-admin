<script setup lang="ts">
/** One block, in one state, with a service behind it that answers the way this case needs. */

/* THE REAL SCREEN, NOT A COPY OF ITS MARKUP. A page that redrew each state by hand would be a
   second implementation of the thing it claims to show, and the two would drift apart exactly
   when it mattered — decision 227's rule, applied to a picture instead of a measurement. */

/* So the case swaps the service and the cache underneath the screen and mounts the screen itself.
   Its own QueryClient per case, or one case's answer would be served to the next from the cache. */

import { QueryClient } from '@tanstack/vue-query'
import { provide } from 'vue'

import type { ApiClient } from '@/api/client'
import { apiClientKey } from '@/api/provide'

const { label, note, service } = defineProps<{
  label: string
  /** What this case is worth looking at for, when the picture alone does not say. */
  note?: string | undefined
  service: Partial<ApiClient>
}>()

provide(apiClientKey, defineService())

/* The string the library injects under when no id is given. Provided here rather than installed on
   the application, which is what makes it a per-case cache. */
provide('VUE_QUERY_CLIENT', new QueryClient({ defaultOptions: { queries: { retry: false } } }))

function defineService(): ApiClient {
  return {
    // A method this case did not think about must not resolve to `undefined` and be called: that
    // is a TypeError in a screen, which reads as the screen being broken rather than the case.
    ...(new Proxy(
      {},
      {
        get: (_target, name: string) => () =>
          new Promise(() => {
            void name
          }),
      },
    ) as ApiClient),
    ...service,
  } as ApiClient
}
</script>

<template>
  <section class="flex flex-col gap-2">
    <header class="flex flex-col gap-1">
      <h3 class="font-numeric text-dense text-text-secondary">{{ label }}</h3>
      <p v-if="note !== undefined" class="max-w-reading text-caption text-text-muted">{{ note }}</p>
    </header>
    <div class="overflow-hidden rounded-panel border border-border-strong">
      <slot />
    </div>
  </section>
</template>
