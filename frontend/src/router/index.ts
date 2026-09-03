/**
 * Routing and the permission guard.
 *
 * Two rules the rest of the application depends on:
 *
 * DEFAULT CLOSED. A route is protected unless it says otherwise. `requiresAuth` is optional and
 * absent means true, so forgetting the flag leaves a page guarded rather than open — the failure
 * that costs nothing instead of the one that costs everything.
 *
 * PERMISSIONS, NEVER ROLES. The guard asks whether a permission is held, never which role holds
 * it. Roles are rows in a table that an administrator can edit; keying the interface on role codes
 * would mean a role change could only take effect with a frontend release.
 */

import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router'

import type { PermissionCode } from '@/domain/permissions'
import { useAuthStore } from '@/stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    /** Absent means true. Only a page that is safe for a stranger says `false`. */
    requiresAuth?: false
    /** A single permission code the visitor must hold. */
    permission?: PermissionCode
    /** Set by the guard when the visitor is signed in but not allowed here, so the view can
     *  answer at the attempted address instead of bouncing them somewhere else. */
    forbidden?: boolean
  }
}

/** Where to send someone after they sign in.
 *
 *  Only a path on this site is accepted, and the parser that decides is the one the browser will
 *  actually use. Hand-written rules do not hold here: a backslash is a path separator for special
 *  schemes, and tab, newline and carriage return are stripped before parsing — so "/\\/evil.example"
 *  and "/<tab>/evil.example" both resolve to a foreign origin while passing any check that only
 *  looks for a leading "//".
 *
 *  This is the guard on the page that asks for a password, which is where an open redirect is
 *  worth the most to whoever finds one. */
export function safeNext(raw: unknown, origin: string = window.location.origin): string | null {
  if (typeof raw !== 'string' || raw === '') return null
  if (!raw.startsWith('/')) return null
  try {
    const url = new URL(raw, origin)
    if (url.origin !== origin) return null
    return url.pathname + url.search + url.hash
  } catch {
    return null
  }
}

export function intendedPath(to: RouteLocationNormalized): string {
  return to.fullPath
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      meta: { requiresAuth: false },
      component: () => import('@/views/LoginView.vue'),
    },
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
    },
    {
      path: '/subscribers',
      name: 'subscribers',
      meta: { permission: 'subscribers.read' },
      component: () => import('@/views/SubscribersView.vue'),
    },
    {
      path: '/subscribers/:userId',
      name: 'subscriber',
      meta: { permission: 'subscribers.read' },
      component: () => import('@/views/SubscriberView.vue'),
    },
    {
      path: '/analytics',
      name: 'analytics',
      meta: { permission: 'analytics.read' },
      component: () => import('@/views/AnalyticsView.vue'),
    },
    {
      path: '/audit',
      name: 'audit',
      meta: { permission: 'audit.read' },
      component: () => import('@/views/AuditView.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      meta: { requiresAuth: false },
      component: () => import('@/views/NotFoundView.vue'),
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // The opening refresh has to have finished before any decision is made about who this is.
  // Without this wait the first navigation after a reload reads an empty store and redirects a
  // signed-in person to the login page — a bug that looks like "the session did not survive".
  if (!auth.ready) await auth.bootstrap(apiClient())

  const needsAuth = to.meta.requiresAuth !== false

  if (needsAuth && !auth.isAuthenticated) {
    return { name: 'login', query: { next: intendedPath(to) }, replace: true }
  }

  // Someone already signed in has no business on the login page; send them where they were going.
  if (!needsAuth && auth.isAuthenticated && to.name === 'login') {
    return { path: safeNext(to.query['next']) ?? '/', replace: true }
  }

  const permission = to.meta.permission
  if (permission !== undefined && !auth.can(permission)) {
    // Answer at the address that was asked for. A redirect would erase what they tried to reach
    // and turn "you may not" into "that is not here".
    to.meta.forbidden = true
  } else {
    to.meta.forbidden = false
  }

  return true
})

/** Set once at start-up. The guard needs the client, and the client must not import the router. */
let client: import('@/api/client').ApiClient | null = null
export function provideApiClient(instance: import('@/api/client').ApiClient): void {
  client = instance
}
function apiClient(): import('@/api/client').ApiClient {
  if (client === null) throw new Error('the API client was not provided before routing started')
  return client
}
