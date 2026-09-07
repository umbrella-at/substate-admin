/** The answers the cases on /dev/states are built from. */

/* Small on purpose: enough rows to show the shape of a state, not a copy of the seeder. What is
   being looked at here is the frame around the data, and a full page of rows hides it. */

import { ApiError } from '@/api/client'
import type {
  AuditPage,
  HealthResponse,
  MeResponse,
  PlanSummary,
  RolesResponse,
  SubscriberDetail,
  SubscriberEventPage,
  SubscriberPage,
  UserListResponse,
} from '@/api/client'

/** A request that never answers. The loading state is the only one with no other way in. */
export const NEVER = () => new Promise<never>(() => {})

/** A refusal the service wrote itself, which is the failure a screen can repeat. */
export const REFUSED = () =>
  Promise.reject(
    new ApiError(503, {
      code: 'INTERNAL_ERROR',
      message: 'The service failed to handle this request. Try again; quote request 4b21e0.',
      field: null,
    }),
  )

export const PLANS: PlanSummary[] = [
  {
    id: 'monthly',
    price: 500,
    currency: 'USD',
    periodUnit: 'months',
    periodCount: 1,
    trialDays: 14,
    graceDays: 5,
  },
]

export function health(seeded = true): HealthResponse {
  return {
    status: 'ok',
    version: '0.1.0',
    commit: 'dev',
    db: true,
    world: { id: 'base', seeded, subscribers: seeded ? 351 : 0, events: seeded ? 3755 : 0 },
  }
}

export function subscribers(count: number, total = count): SubscriberPage {
  const states = ['active', 'trial', 'grace', 'expired', 'cancelled'] as const
  return {
    items: Array.from({ length: count }, (_unused, index) => ({
      userId: `sub-${String(index + 1).padStart(4, '0')}`,
      displayName: ['Ada Lovelace', 'Grace Hopper', 'Alan Turing', 'Karen Spärck Jones'][
        index % 4
      ]!,
      state: states[index % states.length]!,
      planId: 'monthly',
      accessUntil: '2026-10-16T00:00:00Z',
      expiresAt: '2026-10-16T00:00:00Z',
      lastActiveAt: '2026-09-01T09:12:00Z',
    })),
    total,
    page: 1,
    pageSize: 25,
  }
}

export function detail(): SubscriberDetail {
  return {
    subscriber: {
      userId: 'sub-0001',
      displayName: 'Ada Lovelace',
      state: 'grace',
      planId: 'monthly',
      accessUntil: '2026-10-21T00:00:00Z',
      expiresAt: '2026-10-16T00:00:00Z',
      trialEndsAt: null,
      graceEndsAt: '2026-10-21T00:00:00Z',
      cancelledAt: null,
      pendingPlanId: null,
      lastActiveAt: '2026-09-01T09:12:00Z',
      promoCode: null,
      referrerId: null,
    },
    plan: PLANS[0]!,
    promoCode: null,
    referrerId: null,
    referrerProgramId: null,
    referralProgramId: null,
    trialStartedAt: null,
  }
}

export function events(count: number, total = count): SubscriberEventPage {
  const types = ['subscription.created', 'payment.recorded', 'subscription.renewed']
  return {
    items: Array.from({ length: count }, (_unused, index) => ({
      id: `e-${index}`,
      type: types[index % types.length]!,
      occurredAt: '2026-09-02T05:09:00Z',
      payload: { accessUntil: '2026-10-16T00:00:00Z' },
    })),
    total,
    page: 1,
    pageSize: 25,
  }
}

export function audit(count: number): AuditPage {
  return {
    items: Array.from({ length: count }, (_unused, index) => ({
      id: `a-${index}`,
      occurredAt: '2026-09-02T05:09:00Z',
      actor: { id: 'u-1', email: 'operator@example.com' },
      action: 'subscription.payment',
      targetType: 'subscription' as const,
      targetId: 'sub-0001',
      worldId: 'base',
      outcome: 'ok' as const,
      errorCode: null,
      payload: { amount: 500, provider: 'panel', reference: 'ref-1' },
    })),
    total: count,
    page: 1,
    pageSize: 25,
  }
}

export function me(): MeResponse {
  return {
    kind: 'user',
    permissions: ['subscribers.read', 'analytics.read', 'audit.read', 'users.read'],
    role: { code: 'support', name: 'Support' },
    user: {
      id: 'u-1',
      email: 'operator@example.com',
      isActive: true,
      createdAt: '2026-01-01T00:00:00Z',
      lastLoginAt: '2026-09-05T08:00:00Z',
    },
    worldId: null,
  }
}

export function users(count: number): UserListResponse {
  return {
    items: Array.from({ length: count }, (_unused, index) => ({
      id: `u-${index}`,
      email: `operator${index}@example.com`,
      isActive: true,
      createdAt: '2026-01-01T00:00:00Z',
      lastLoginAt: null,
      role: { code: 'support', name: 'Support' },
    })),
    total: count,
    page: 1,
    pageSize: 25,
  }
}

export function roles(count: number): RolesResponse {
  return {
    items: Array.from({ length: count }, (_unused, index) => ({
      id: `r-${index}`,
      code: `role-${index}`,
      name: ['Administrator', 'Support', 'Analysts'][index % 3]!,
      isSystem: index === 0,
      permissions: ['analytics.read'],
      holders: index,
    })),
    permissions: [
      { code: 'analytics.read', description: 'View aggregate analytics.' },
      { code: 'users.read', description: "View the panel's own users and roles." },
    ],
  }
}
