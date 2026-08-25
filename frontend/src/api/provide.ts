/**
 * How a component gets the API client.
 *
 * There is exactly one client per application, it is created in `main.ts` because that is where the
 * hooks it needs can be wired, and the router already receives it through `provideApiClient`.
 * Components get it through Vue's own injection rather than a module-level singleton: a singleton
 * imported straight from `client.ts` would be shared by every test in the file that touched it, and
 * the first test to sign in would decide what the second one sees.
 */

import { inject, type App, type InjectionKey } from 'vue'

import type { ApiClient } from './client'

export const apiClientKey: InjectionKey<ApiClient> = Symbol('apiClient')

export function installApiClient(app: App, client: ApiClient): void {
  app.provide(apiClientKey, client)
}

export function useApiClient(): ApiClient {
  const client = inject(apiClientKey)
  // Loud rather than optional. A component that silently degraded to "no client" would render an
  // empty dashboard and look like an API problem.
  if (client === undefined) throw new Error('no API client was provided to this application')
  return client
}
