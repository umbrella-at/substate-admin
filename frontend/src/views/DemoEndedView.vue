<script setup lang="ts">
/**
 * What a visitor sees when their demonstration is over.
 */

/* ONE SCREEN FOR TWO ENDINGS, WHICH FROM HERE ARE THE SAME EVENT. The hour ran out, or a deploy
   restarted the process under them; worlds live in memory, so both mean the same thing and neither
   is recoverable. Inventing a difference would be guessing. */

/* Deliberately not the login page, whose sentence is "sign in again to carry on where you were" —
   advice a visitor cannot take: there was never an account, and the address they were looking at
   belongs to a world that no longer exists. */

import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { useApiClient } from '@/api/provide'
import AppButton from '@/components/AppButton.vue'
import AppNotice from '@/components/AppNotice.vue'
import { useAuthStore } from '@/stores/auth'

const client = useApiClient()
const router = useRouter()
const auth = useAuthStore()

const busy = ref(false)
const refused = ref(false)

async function again(): Promise<void> {
  if (busy.value) return
  busy.value = true
  refused.value = false
  try {
    const session = await client.demoSession()
    client.setDemoToken(session.accessToken)
    auth.adopt(await client.me())
    await router.replace({ name: 'dashboard' })
  } catch {
    // Every reason is the same reason from here: no world was opened. The message says what to
    // do about it rather than which of the two it was.
    refused.value = true
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center p-6">
    <div class="flex w-full max-w-form flex-col items-start gap-4">
      <h1 class="text-title text-text-primary">That demonstration has ended.</h1>
      <p class="text-ui text-text-secondary">
        Everything in it was invented — the subscribers, the payments, the colleagues on the users
        screen — and all of it is gone. A new one takes a moment to build and starts from the same
        nine months of history.
      </p>

      <AppNotice v-if="refused" role="warning">
        No demonstration could be opened just now. They are handed back within the hour, so this is
        worth trying again shortly.
      </AppNotice>

      <div class="flex items-center gap-3">
        <AppButton variant="filled" :busy="busy" @click="again">
          {{ busy ? 'Building a world…' : 'Start another' }}
        </AppButton>
        <RouterLink
          :to="{ name: 'login' }"
          class="text-ui text-text-secondary hover:text-text-primary"
        >
          Sign in instead
        </RouterLink>
      </div>
    </div>
  </div>
</template>
