import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import { ApiError, createClient } from '@/api/client'
import { installApiClient } from '@/api/provide'
import App from '@/App.vue'
import { intendedPath, provideApiClient, router } from '@/router'
import { forgetSession } from '@/session'
import { useAuthStore } from '@/stores/auth'
import '@/styles/tokens.css'

const app = createApp(App)
app.use(createPinia())

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A 4xx is an answer, not a hiccup. The server has looked at the request and said no, and
      // asking three more times produces the same no a little later — while the person watches a
      // spinner that is going nowhere and the audit log fills with attempts nobody made.
      // A 5xx or a dropped connection is a different claim: nothing was decided, so try again.
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status < 500) return false
        return failureCount < 2
      },
      // Off on purpose. This panel is read beside a terminal and a chat window, so a refetch on
      // every focus would be a request per alt-tab, and the data on these screens does not change
      // between glances. Freshness is bought where it matters, by invalidating after a write.
      refetchOnWindowFocus: false,
    },
  },
})

const auth = useAuthStore()

/** Set once the application is on screen. Before that, the router's guard is what decides where an
 *  anonymous visitor lands, and a redirect issued from here would race the very first navigation. */
let mounted = false

const client = createClient({
  onSessionLost: () => {
    forgetSession(client, queryClient)
    if (!mounted) return
    const from = router.currentRoute.value
    if (from.name === 'login') return
    // `expired` distinguishes "you were signed in and no longer are" from "you arrived here" —
    // without it the login page reappears with no explanation and reads as a bug in the session.
    void router.replace({
      name: 'login',
      query: { next: intendedPath(from), expired: '1' },
    })
  },
})

provideApiClient(client)
installApiClient(app, client)
app.use(VueQueryPlugin, { queryClient })

// Before `app.use(router)`, and that order is load-bearing. Installing the router starts the first
// navigation immediately, which runs the guard, which finds `auth.ready` false and starts a
// bootstrap of its own — a SECOND `GET /api/auth/me` racing this one on every single page load.
// Both would normally succeed and nobody would notice; the day they disagree, the loser's `clear()`
// signs out a session the winner just adopted.
// Belt and braces over the store's own catch: no future change in there can ever
// cost the mount, because an unmounted page is the one outcome with no way out of it.
await auth.bootstrap(client).catch(() => undefined)

app.use(router)
await router.isReady()
app.mount('#app')
mounted = true
