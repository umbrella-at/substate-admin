<script setup lang="ts">
/**
 * Who operates this panel, and what each role lets them do. Two questions on one screen because
 * a role is only interesting for the people on it, and the count is beside every role.
 */

/* Every control here is drawn from a permission rather than from a role code, so a role edited
   in this very screen takes effect without a release of the frontend. */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'

import { type RoleDetail, type RolesResponse, type UserListResponse } from '@/api/client'
import { failureText } from '@/api/failure'
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
  if (selected.value === null && all[0] !== undefined) {
    // A delete lands here: it clears the selection, the list shrinks, and this picks the first
    // survivor. That is the write moving the selection again, not somebody choosing a role.
    movedByAWrite = outcome.value !== null
    selected.value = all[0].id
  }
})

const role = computed<RoleDetail | undefined>(() =>
  items.value.find((each) => each.id === selected.value),
)

const failure = failureText

async function reload(): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: ['roles'] })
  // ADOPTED, not invalidated. The operator may have just edited the role they hold, and the store
  // is what the nav, the guard and every write control decide from — and nothing on this screen
  // observes that cache entry, so invalidating it refetched nothing.
  auth.adopt(await queryClient.fetchQuery({ queryKey: ['auth', 'me'], queryFn: () => client.me() }))
}

const save = useMutation({
  mutationFn: (body: { id: string; name: string; permissions: string[] }) =>
    client.replaceRole(body.id, { name: body.name, permissions: body.permissions }),
  onSuccess: async () => {
    answered('Role saved.')
    await reload()
  },
})

const remove = useMutation({
  mutationFn: (id: string) => client.deleteRole(id),
  onError: refused,
  onSuccess: async () => {
    answered('Role deleted.')
    // The list is about to lose a role, so the watcher that picks the first survivor will move
    // the selection a second time. Latched here and in that watcher, not once.
    movedByAWrite = true
    selected.value = null
    await reload()
  },
})

const create = useMutation({
  mutationFn: (body: { code: string; name: string }) =>
    client.createRole({ ...body, permissions: [] }),
  onSuccess: async (made: RoleDetail) => {
    answered('Role created.')
    creating.value = false
    draftCode.value = ''
    draftName.value = ''
    movedByAWrite = true
    selected.value = made.id
    await reload()
  },
})

/** What the last write did, in the words of the button that did it. */

/* Three writes had no answer at all: a delete removed a name, a save changed nothing visible, a
   create closed a form. `Save role` has to come back as `Role saved`. */

/* HELD, NOT DERIVED. Read off `isSuccess`, two of the three sentences were erased before a frame
   could show them: the watchers below reset the mutation that had just succeeded — one when the
   form closed, one when the list lost a role and the selection moved to the survivor. */
const outcome = ref<{ role: 'success' | 'danger'; text: string } | null>(null)

function answered(text: string): void {
  outcome.value = { role: 'success', text }
}

function refused(cause: unknown): void {
  outcome.value = { role: 'danger', text: failure(cause) }
}

/* A refusal belongs to the role it was refused on, and an answer to the write that produced it.
   Left standing, the previous role's failure appeared over the next one. */
watch(selected, () => {
  if (movedByAWrite) {
    movedByAWrite = false
    return
  }
  outcome.value = null
  save.reset()
})

/** Set by a write that moves the selection itself, so the reset above does not erase the sentence
 *  that write has just produced. */
let movedByAWrite = false

/* And to the form that produced it: an emptied form reopened wearing the last attempt's refusal.
   The answer is not reset here — closing the form is how a successful create ends. */
watch(creating, () => {
  create.reset()
  attemptedNewRole.value = false
})

/** Whether `Create role` has been pressed on this form. An empty code is not a refusal to report
 *  before anybody has asked for anything — and it was not one afterwards either, so the button
 *  named for what would happen did nothing and said nothing. */
const attemptedNewRole = ref(false)

const newRoleError = computed(() => {
  if (create.error.value !== null) return failure(create.error.value)
  const parsed = roleForm.safeParse({ code: draftCode.value, name: draftName.value })
  if (parsed.success) return undefined
  if (draftCode.value === '' && !attemptedNewRole.value) return undefined
  return parsed.error.issues[0]?.message
})

function onSave(body: { name: string; permissions: string[] }): void {
  const id = role.value?.id
  outcome.value = null
  if (id !== undefined) save.mutate({ id, ...body })
}

function onRemove(): void {
  const id = role.value?.id
  outcome.value = null
  if (id !== undefined) remove.mutate(id)
}

function submitNew(): void {
  attemptedNewRole.value = true
  outcome.value = null
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

        <!-- The shape of the table below: a header line and four rows at its own `py-2`. -->
        <template v-if="users.isPending.value">
          <p class="sr-only" role="status">Loading the operators</p>
          <div class="py-2"><SkeletonBlock class="h-3 max-w-form" /></div>
          <div v-for="line in 4" :key="line" class="py-2">
            <SkeletonBlock class="h-4 max-w-reading" />
          </div>
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

        <!-- The shape of what is coming here is a wrap of pill buttons over a permission list,
             not four full-width bars: that was the operator table's shape on the wrong panel. -->
        <template v-if="roles.isPending.value">
          <p class="sr-only" role="status">Loading the roles</p>
          <div class="flex flex-wrap gap-2">
            <SkeletonBlock v-for="pill in 4" :key="pill" class="h-8 w-12" />
          </div>
          <SkeletonBlock class="h-4 max-w-reading" />
          <SkeletonBlock class="h-4 max-w-reading" />
        </template>

        <template v-else-if="roles.isError.value">
          <AppNotice assertive>{{ failure(roles.error.value) }}</AppNotice>
          <div>
            <AppButton variant="outlined" @click="() => void roles.refetch()">Try again</AppButton>
          </div>
        </template>

        <template v-else>
          <!-- Where the result of a write appears, because the panel is what owns all three
               buttons. A refusal about the values stays beside the fields it is about. -->
          <AppNotice
            v-if="outcome !== null"
            :role="outcome.role"
            :assertive="outcome.role === 'danger'"
          >
            {{ outcome.text }}
          </AppNotice>

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

          <p v-if="items.length === 0" class="max-w-reading text-ui text-text-secondary">
            There are no roles yet. Create one, and everyone it is given to may do what it grants.
          </p>

          <ul v-else class="flex flex-wrap gap-2">
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
