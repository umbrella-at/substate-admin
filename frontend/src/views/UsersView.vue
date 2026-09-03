<script setup lang="ts">
/**
 * Who operates this panel, and what each role lets them do. Two questions on one screen because
 * a role is only interesting for the people on it, and the count is beside every role.
 */

/* Every control here is drawn from a permission rather than from a role code, so a role edited
   in this very screen takes effect without a release of the frontend. */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'

import { ApiError, type RoleDetail, type RolesResponse, type UserListResponse } from '@/api/client'
import { useApiClient } from '@/api/provide'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import AppNotice from '@/components/AppNotice.vue'
import RoleEditor from '@/components/RoleEditor.vue'
import SkeletonBlock from '@/components/SkeletonBlock.vue'
import TablePager from '@/components/TablePager.vue'
import { roleForm } from '@/domain/roles'
import { useAuthStore } from '@/stores/auth'

const client = useApiClient()
const auth = useAuthStore()
const queryClient = useQueryClient()

const mayWrite = computed(() => auth.can('users.write'))

const page = ref(1)
const PAGE_SIZE = 25

const users = useQuery<UserListResponse>({
  queryKey: computed(() => ['users', page.value]),
  queryFn: ({ signal }) =>
    client.users(
      new URLSearchParams({ page: String(page.value), pageSize: String(PAGE_SIZE) }),
      signal,
    ),
  placeholderData: keepPreviousData,
})

const pageCount = computed(() => {
  const total = users.data.value?.total ?? 0
  return total === 0 ? 0 : Math.ceil(total / PAGE_SIZE)
})

const roles = useQuery<RolesResponse>({
  queryKey: ['roles'],
  queryFn: ({ signal }) => client.roles(signal),
})

const selected = ref<string | null>(null)
const creating = ref(false)
const draftCode = ref('')
const draftName = ref('')

const items = computed(() => roles.data.value?.items ?? [])
const catalogue = computed(() => roles.data.value?.permissions ?? [])

// The first role, once there is one, so the editor is never an empty panel beside a full list.
watch(items, (all) => {
  if (selected.value === null && all[0] !== undefined) selected.value = all[0].id
})

const role = computed<RoleDetail | undefined>(() =>
  items.value.find((each) => each.id === selected.value),
)

const UNREACHABLE = 'The service could not be reached.'

function failure(error: unknown): string {
  if (error instanceof ApiError && error.status < 500 && error.message !== '') return error.message
  return UNREACHABLE
}

async function reload(): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: ['roles'] })
  // The signed-in operator may have just edited their own role, and every control on every screen
  // reads what `/auth/me` last said.
  await queryClient.invalidateQueries({ queryKey: ['auth', 'me'] })
}

const save = useMutation({
  mutationFn: (body: { id: string; name: string; permissions: string[] }) =>
    client.replaceRole(body.id, { name: body.name, permissions: body.permissions }),
  onSuccess: reload,
})

const remove = useMutation({
  mutationFn: (id: string) => client.deleteRole(id),
  onSuccess: async () => {
    selected.value = null
    await reload()
  },
})

const create = useMutation({
  mutationFn: (body: { code: string; name: string }) =>
    client.createRole({ ...body, permissions: [] }),
  onSuccess: async (made: RoleDetail) => {
    creating.value = false
    draftCode.value = ''
    draftName.value = ''
    selected.value = made.id
    await reload()
  },
})

const newRoleError = computed(() => {
  if (create.error.value !== null) return failure(create.error.value)
  const parsed = roleForm.safeParse({ code: draftCode.value, name: draftName.value })
  if (parsed.success || draftCode.value === '') return undefined
  return parsed.error.issues[0]?.message
})

function onSave(body: { name: string; permissions: string[] }): void {
  const id = role.value?.id
  if (id !== undefined) save.mutate({ id, ...body })
}

function onRemove(): void {
  const id = role.value?.id
  if (id !== undefined) remove.mutate(id)
}

function submitNew(): void {
  const parsed = roleForm.safeParse({ code: draftCode.value, name: draftName.value })
  if (!parsed.success) return
  create.mutate(parsed.data)
}
</script>

<template>
  <section class="flex flex-col gap-6 p-6">
    <header class="flex flex-col gap-2">
      <h1 class="text-title text-text-primary">Users and roles</h1>
      <p class="max-w-reading text-ui text-text-secondary">
        Who can open this panel, and what each role lets them do. A role is a set of permissions in
        the database, not a name in the code — which is why editing one takes effect on the next
        request.
      </p>
    </header>

    <div class="grid gap-4 lg:grid-cols-2">
      <section class="flex flex-col gap-4 rounded-panel bg-surface-1 p-4">
        <h2 class="text-heading text-text-primary">Operators</h2>

        <template v-if="users.isPending.value">
          <p class="sr-only" role="status">Loading the operators</p>
          <SkeletonBlock v-for="line in 4" :key="line" class="h-8 w-full" />
        </template>

        <template v-else-if="users.isError.value">
          <AppNotice assertive>{{ failure(users.error.value) }}</AppNotice>
          <div>
            <AppButton variant="outlined" @click="() => void users.refetch()">Try again</AppButton>
          </div>
        </template>

        <p
          v-else-if="(users.data.value?.items.length ?? 0) === 0"
          class="max-w-reading text-ui text-text-secondary"
        >
          Nobody has an account yet. The command line creates the first one.
        </p>

        <template v-else>
          <table class="w-full text-dense">
            <thead>
              <tr class="text-caption text-text-muted">
                <th class="py-2 text-left font-ui">Email</th>
                <th class="py-2 text-left font-ui">Role</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="person in users.data.value?.items ?? []" :key="person.id">
                <td class="py-2 text-text-primary">{{ person.email }}</td>
                <td class="py-2 text-text-secondary">{{ person.role.name }}</td>
              </tr>
            </tbody>
          </table>

          <TablePager
            :page="page"
            :page-count="pageCount"
            :total="users.data.value?.total ?? 0"
            :busy="users.isFetching.value"
            noun="operator"
            plural="operators"
            @go="(next: number) => (page = next)"
          />
        </template>
      </section>

      <section class="flex flex-col gap-4 rounded-panel bg-surface-1 p-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h2 class="text-heading text-text-primary">Roles</h2>
          <AppButton v-if="mayWrite && !creating" variant="outlined" @click="creating = true">
            New role
          </AppButton>
        </div>

        <template v-if="roles.isPending.value">
          <p class="sr-only" role="status">Loading the roles</p>
          <SkeletonBlock v-for="line in 4" :key="line" class="h-8 w-full" />
        </template>

        <template v-else-if="roles.isError.value">
          <AppNotice assertive>{{ failure(roles.error.value) }}</AppNotice>
          <div>
            <AppButton variant="outlined" @click="() => void roles.refetch()">Try again</AppButton>
          </div>
        </template>

        <template v-else>
          <form v-if="creating" class="flex max-w-form flex-col gap-4" @submit.prevent="submitNew">
            <AppInput v-model="draftCode" label="Code" placeholder="analysts" />
            <AppInput v-model="draftName" label="Name" placeholder="Analysts" />
            <AppNotice v-if="newRoleError !== undefined" role="danger">
              {{ newRoleError }}
            </AppNotice>
            <div class="flex items-center gap-3">
              <AppButton type="submit" variant="outlined" :busy="create.isPending.value">
                {{ create.isPending.value ? 'Creating…' : 'Create role' }}
              </AppButton>
              <AppButton variant="plain" @click="creating = false"
                >Keep the roles as they are</AppButton
              >
            </div>
          </form>

          <ul class="flex flex-wrap gap-2">
            <li v-for="each in items" :key="each.id">
              <AppButton
                :variant="each.id === selected ? 'outlined' : 'plain'"
                :aria-pressed="each.id === selected"
                @click="selected = each.id"
              >
                {{ each.name }}
              </AppButton>
            </li>
          </ul>

          <RoleEditor
            v-if="role !== undefined"
            :role="role"
            :catalogue="catalogue"
            :may-write="mayWrite"
            :saving="save.isPending.value"
            :deleting="remove.isPending.value"
            :failure="save.error.value === null ? undefined : failure(save.error.value)"
            @save="onSave"
            @remove="onRemove"
          />
        </template>
      </section>
    </div>
  </section>
</template>
