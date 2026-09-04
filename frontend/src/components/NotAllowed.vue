<script setup lang="ts">
/**
 * What a visitor sees at an address their role does not open. The guard marks the route rather
 * than redirecting, so this answers where they asked instead of turning "you may not" into
 * "that is not here".
 */

/* The permission is named because the way out is somebody else granting it, and a person cannot
   ask for a thing they have not been told the name of. */

import PermissionChip from '@/components/PermissionChip.vue'
import type { PermissionCode } from '@/domain/permissions'

defineProps<{ permission: PermissionCode }>()
</script>

<template>
  <div class="flex max-w-reading flex-col items-start gap-3 p-6">
    <h1 class="text-title text-text-primary">This page is not yours to open.</h1>
    <p class="text-ui text-text-secondary">
      Your role does not grant the permission this page is behind. Nothing is wrong with the page or
      with your session — an administrator can add the permission to your role.
    </p>
    <p class="flex flex-wrap items-baseline gap-2 text-ui text-text-secondary">
      It needs
      <PermissionChip :code="permission" />
    </p>
  </div>
</template>
