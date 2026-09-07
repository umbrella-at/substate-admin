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

/** The case's own answers, and a promise that never settles for anything it did not think of. */

/* A PROXY AROUND THE SERVICE, NOT SPREAD INTO AN OBJECT. Spreading a proxy copies the keys of its
   TARGET, so `{...new Proxy({}, {get})}` is `{}` and the trap is never reached — the fallback did
   nothing and a method a case omitted was `undefined`, which is a TypeError inside the screen. */
function defineService(): ApiClient {
  return new Proxy(service, {
    get: (target, name: string) =>
      name in target
        ? (target as Record<string, unknown>)[name]
        : () => new Promise(() => undefined),
  }) as ApiClient
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
