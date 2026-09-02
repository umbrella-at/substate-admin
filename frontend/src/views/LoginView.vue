<script setup lang="ts">
/**
 * The only page in this application a stranger may see.
 *
 * Everything here is about what the page is allowed to SAY. The backend answers an unknown
 * address, a wrong password and a deactivated account with byte-identical 401s, and it goes to
 * some trouble to do so — it verifies a dummy hash when no user exists, and it checks `is_active`
 * only after the argon2 work, so that all three paths cost the same milliseconds. All of that is
 * undone by a login page that says "no account with that email" in one case and "wrong password"
 * in another. So there is one sentence for the whole family of refusals, and it is the API's own.
 *
 * The other two cases are genuinely different situations and get their own sentences: being rate
 * limited is something waiting fixes, and an unreachable service is not a claim about the password
 * at all. Telling someone their password is wrong when the server never saw it is the worst
 * failure this page can have, because they will change a password that was correct.
 */

import { computed, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useApiClient } from '@/api/provide'
import AppButton from '@/components/AppButton.vue'
import AppNotice from '@/components/AppNotice.vue'
import AppInput from '@/components/AppInput.vue'
import { safeNext } from '@/router'
import { useAuthStore } from '@/stores/auth'

const client = useApiClient()
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const email = ref('')
const password = ref('')
const busy = ref(false)

/** What kind of refusal is on screen, not just its text. The wording and whether the fields
 *  themselves are marked invalid both follow from this, and they must not disagree. */
type Refusal = 'credentials' | 'validation' | 'rate-limited' | 'unreachable'
const refusal = ref<Refusal | null>(null)
const message = ref('')

/** Set by the session teardown when a signed-in person was returned here. Without it the login
 *  page simply reappears, and reappearing for no visible reason reads as a bug. */
const expired = computed(() => route.query['expired'] === '1')

/** Only the two field-level refusals paint the borders. Being rate limited or being unable to
 *  reach the service says nothing whatsoever about what was typed. */
const fieldsInvalid = computed(
  () => refusal.value === 'credentials' || refusal.value === 'validation',
)

const ERROR_ID = 'login-error'

/** In flight only. Abandoned if this page is navigated away from, so a slow answer cannot land on
 *  a component that no longer exists and set state nobody will see. */
let inFlight: AbortController | null = null
onBeforeUnmount(() => inFlight?.abort())

const UNREACHABLE = 'The service could not be reached. Nothing was sent — try again in a moment.'
const RATE_LIMITED = 'Too many attempts. Wait a few minutes and try again.'

function describe(cause: unknown): { refusal: Refusal; message: string } {
  // Not an ApiError at all: a dropped connection, DNS, a request that never completed. The server
  // has no opinion here because the server was never reached.
  if (!(cause instanceof ApiError)) return { refusal: 'unreachable', message: UNREACHABLE }

  if (cause.status === 429) {
    // The API's own sentence already says that waiting helps, and it is written against the real
    // window. It also sends `Retry-After`, which this client does not surface (see the report):
    // rather than invent a countdown from a number nobody read, the honest thing is "a few
    // minutes", which is what the limiter's window actually is.
    return {
      refusal: 'rate-limited',
      message: cause.code === 'RATE_LIMITED' && cause.message !== '' ? cause.message : RATE_LIMITED,
    }
  }

  if (cause.status === 422) {
    return { refusal: 'validation', message: 'Enter a complete email address and a password.' }
  }

  if (cause.status === 401) {
    // The one sentence. Unknown address, wrong password, disabled account — the server refuses to
    // tell them apart and so does this page.
    return { refusal: 'credentials', message: 'Email or password is incorrect.' }
  }

  // A 5xx, or anything else the catalogue does not cover. The API's own 500 text names the request
  // id, which is the most it can say without leaking a cause — and it is the wrong sentence on the
  // one page a stranger reaches, where the useful thing to say is that the service is not
  // answering rather than how to find the failure in a journal they cannot read.
  return { refusal: 'unreachable', message: UNREACHABLE }
}

async function submit(): Promise<void> {
  // The second submit. Enter is easy to press twice and a slow network makes it tempting; two
  // logins in flight would be two refresh families for one device, and the second answer would
  // overwrite the first. Refused here rather than by disabling the button, because a button that
  // greys out and comes back is docs/design.md's flinch.
  if (busy.value) return

  refusal.value = null
  message.value = ''

  // Answered here rather than by the server. The login limiter counts every attempt that reaches
  // it, including the empty ones, so submitting a blank form would spend part of a real person's
  // five tries on a request that cannot succeed. Native browser validation would also catch this,
  // but it would say it in the browser's voice next to a page that has exactly one.
  if (email.value.trim() === '' || password.value === '') {
    refusal.value = 'validation'
    message.value = 'Enter your email address and password.'
    return
  }

  busy.value = true

  const controller = new AbortController()
  inFlight = controller

  try {
    const token = await client.login(email.value.trim(), password.value, controller.signal)
    client.setAccessToken(token.accessToken)
    auth.adopt(await client.me(controller.signal))

    // `next` is attacker-supplied text. `safeNext` accepts only a path on this site, so a link to
    // `/login?next=https://evil.example` is an open redirect with a credential prompt in front of
    // it and this is the line that refuses to be one.
    await router.replace(safeNext(route.query['next']) ?? '/')
  } catch (cause) {
    // The page is already gone, or a newer attempt cancelled this one. Reporting a failure would
    // be reporting the navigation that just succeeded.
    if (controller.signal.aborted) return
    const described = describe(cause)
    refusal.value = described.refusal
    message.value = described.message
    // The password field is cleared and the email is not: retyping an address that was correct is
    // an annoyance, and leaving a password on screen after a failure is a shoulder-surfing risk
    // for a credential that has now been shown to be worth guessing at.
    password.value = ''
  } finally {
    if (inFlight === controller) inFlight = null
    busy.value = false
  }
}
</script>

<template>
  <main class="grid min-h-screen place-items-center p-6">
    <!-- The panel is what the inputs are recessed into. Without it their surface-0 fill would meet
         the surface-0 page and each field would survive as a rectangle of border. -->
    <form
      class="w-full max-w-form rounded-panel border border-border bg-surface-1 p-6"
      novalidate
      @submit.prevent="submit"
    >
      <h1 class="text-title text-text-primary">Sign in</h1>
      <p class="mt-2 text-ui text-text-secondary">The substate admin panel.</p>

      <p
        v-if="expired"
        class="mt-4 rounded-control border border-warning-border bg-warning-bg px-3 py-2 text-ui text-warning-text"
        role="status"
      >
        Your session ended. Sign in again to carry on where you were.
      </p>

      <div class="mt-6 grid gap-4">
        <AppInput
          v-model="email"
          autocomplete="username"
          :autofocus="true"
          :described-by="message === '' ? undefined : ERROR_ID"
          :invalid="fieldsInvalid"
          label="Email"
          required
          type="email"
        />
        <AppInput
          v-model="password"
          autocomplete="current-password"
          :described-by="message === '' ? undefined : ERROR_ID"
          :invalid="fieldsInvalid"
          label="Password"
          required
          type="password"
        />
      </div>

      <!-- role="alert" so the sentence is spoken when it appears, rather than sitting there for
           anyone who happens to move the caret back over the form. -->
      <AppNotice v-if="message !== ''" :id="ERROR_ID" class="mt-4" assertive>
        {{ message }}
      </AppNotice>

      <!-- The one filled element on this screen. Its colours do not change while it waits; the
           label does, and aria-busy says the same thing to a screen reader. -->
      <AppButton class="mt-6 w-full" :busy="busy" type="submit" variant="filled">
        {{ busy ? 'Signing in…' : 'Sign in' }}
      </AppButton>
    </form>
  </main>
</template>
