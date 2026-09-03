<script setup lang="ts">
/**
 * One role, and what it grants. A system role is read-only here and refused by the API too: the
 * deploy restores it, so an accepted edit would be undone at the next push.
 */

/* Save and Delete are not drawn without `users.write`. Not disabled — a control nobody may ever
   press is an invitation to a locked door, and the endpoint refuses it anyway. */

import { computed, ref, watch } from 'vue'

import type { PermissionSummary, RoleDetail } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import AppConfirm from '@/components/AppConfirm.vue'
import AppNotice from '@/components/AppNotice.vue'
import { Checkbox } from '@/components/ui/checkbox'
import PermissionChip from '@/components/PermissionChip.vue'
import { bySubject, changed, draftOf, subjectLabel, whyItCannotGo } from '@/domain/roles'

const props = defineProps<{
  role: RoleDetail
  catalogue: readonly PermissionSummary[]
  mayWrite: boolean
  saving: boolean
  deleting: boolean
  failure?: string | undefined
}>()

const emit = defineEmits<{
  save: [{ name: string; permissions: string[] }]
  remove: []
}>()

const draft = ref(draftOf(props.role))
const confirming = ref(false)

// Reset when the selection moves, so the next role does not open holding the last one's edits.
watch(
  () => props.role,
  (role) => {
    draft.value = draftOf(role)
    confirming.value = false
  },
)

const groups = computed(() => bySubject(props.catalogue))
const editable = computed(() => props.mayWrite && !props.role.isSystem)
const dirty = computed(() => changed(props.role, draft.value))
const refusal = computed(() => whyItCannotGo(props.role))

function toggle(code: string, on: boolean): void {
  const next = new Set(draft.value.permissions)
  if (on) next.add(code)
  else next.delete(code)
  draft.value = { ...draft.value, permissions: next }
}

function save(): void {
  emit('save', {
    name: draft.value.name.trim(),
    permissions: [...draft.value.permissions].sort(),
  })
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h3 class="text-heading text-text-primary">{{ role.name }}</h3>
      <span class="text-dense font-numeric text-text-secondary">{{ role.code }}</span>
      <span class="text-caption text-text-muted">
        {{ role.holders === 1 ? '1 person holds it' : `${role.holders} people hold it` }}
      </span>
    </header>

    <AppNotice v-if="failure !== undefined" role="danger" assertive>{{ failure }}</AppNotice>
    <p v-if="refusal !== null" class="max-w-reading text-ui text-text-secondary">{{ refusal }}</p>

    <fieldset v-for="group in groups" :key="group.subject" class="flex flex-col gap-2">
      <legend class="text-caption text-text-muted">{{ subjectLabel(group.subject) }}</legend>
      <label
        v-for="permission in group.codes"
        :key="permission.code"
        class="flex items-start gap-3 text-ui text-text-secondary"
      >
        <Checkbox
          class="mt-1"
          :model-value="draft.permissions.has(permission.code)"
          :disabled="!editable"
          @update:model-value="
            (on: boolean | 'indeterminate') => toggle(permission.code, on === true)
          "
        />
        <span class="flex flex-col items-start gap-1">
          <PermissionChip :code="permission.code" />
          <span class="text-dense text-text-muted">{{ permission.description }}</span>
        </span>
      </label>
    </fieldset>

    <div v-if="editable" class="flex flex-wrap items-center gap-3">
      <AppButton variant="filled" :busy="saving" :disabled="!dirty" @click="save">
        {{ saving ? 'Saving…' : 'Save role' }}
      </AppButton>
      <AppButton v-if="role.holders === 0" variant="outlined" @click="confirming = true">
        Delete role
      </AppButton>
    </div>

    <AppConfirm
      v-model:open="confirming"
      action="Delete role"
      busy-action="Deleting the role…"
      dismiss="Keep role"
      :title="`${role.name} will be gone, and its permissions with it.`"
      :busy="deleting"
      @confirm="emit('remove')"
    />
  </div>
</template>
