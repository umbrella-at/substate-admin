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

import { failureText } from '@/api/failure'
import { useApiClient } from '@/api/provide'
import AppButton from '@/components/AppButton.vue'
import AppNotice from '@/components/AppNotice.vue'
import { useAuthStore } from '@/stores/auth'

const client = useApiClient()
const router = useRouter()
const auth = useAuthStore()

const busy = ref(false)

/** Why no world was opened, in the service's own words. It used to be a boolean, and the sentence
 *  it produced asserted one particular cause — every slot taken — for all four of them. */
const refusal = ref('')

const UNBUILT = 'No world could be built just now. The service did not answer; try again shortly.'

async function again(): Promise<void> {
  if (busy.value) return
  busy.value = true
  refusal.value = ''
  try {
    const session = await client.demoSession()
    client.setDemoToken(session.accessToken)
    auth.adopt(await client.me())
    await router.replace({ name: 'dashboard' })
  } catch (cause) {
    // The service's own sentence when it wrote one: every slot taken, too many attempts, or a
    // failure it names. Only silence gets the sentence about silence.
    refusal.value = failureText(cause, UNBUILT)
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

      <AppNotice v-if="refusal !== ''" role="warning">{{ refusal }}</AppNotice>

      <!-- One button, and the second exit is gone: it went to the login page, which is the one
           destination this screen exists to avoid and which its own comment above rejects. -->
      <AppButton variant="filled" :busy="busy" @click="again">
        {{ busy ? 'Building a world…' : 'Start another' }}
      </AppButton>
    </div>
  </div>
</template>
