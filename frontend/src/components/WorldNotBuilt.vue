<script setup lang="ts">
/**
 * What a screen shows in place of its data when the demonstration world was not built.
 *
 * ONE COMPONENT RATHER THAN ONE SENTENCE PER SCREEN. The subscriber table is the first screen this
 * happens to and it will not be the last: every analytics view reads the same world and would meet
 * the same emptiness. Written into each of them, the explanation would be four sentences that
 * disagree with each other within a round.
 *
 * It is not on every screen, though. The dashboard reads the session and nothing else, so it works
 * exactly as well with no world behind it, and telling somebody there that something is broken
 * would be a screen lying in the other direction. A screen shows this where its own data would
 * have been, or it does not show it at all.
 *
 * THE WORDING NAMES WHAT HAPPENED AND WHAT TO DO. It does not apologise and it does not say
 * something went wrong, because neither tells the reader anything they can act on. The distinction
 * this has to carry is the whole reason it exists: empty because there is nothing, against empty
 * because the thing that fills it did not run.
 *
 * "Reload" is honest about what it does. A reload does not rebuild the world — the world is built
 * when the service starts — so this offers to look again rather than promising a repair.
 */

import AppButton from '@/components/AppButton.vue'

function reload(): void {
  globalThis.location.reload()
}
</script>

<template>
  <div class="flex max-w-reading flex-col items-start gap-3 py-8">
    <h2 class="text-heading text-text-primary">The demonstration world was not built.</h2>
    <p class="text-ui text-text-secondary">
      There is nothing here because the run that fills this world did not finish, not because the
      world is empty. Signing in, permissions and the rest of the panel are unaffected.
    </p>
    <p class="text-ui text-text-secondary">
      The world is rebuilt every time the service starts, so this usually clears itself. Reload to
      see whether it has.
    </p>
    <AppButton variant="outlined" @click="reload">Reload</AppButton>
  </div>
</template>
