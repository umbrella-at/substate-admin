/**
 * ESLint, flat config.
 *
 * This lints; it does not type-check. `vue-tsc --build` is the separate `typecheck` script, and
 * keeping the two apart is what makes a red job readable: eslint failing is a rule to argue with,
 * vue-tsc failing is a type that is wrong. The type-aware eslint presets would blur that line and
 * would also demand that every file linted here belong to a tsconfig project — which the e2e
 * specs and these root-level config files deliberately do not.
 *
 * `src/api/schema.d.ts` is ignored because it is generated: `npm run types` writes it from
 * backend/openapi.json, and a lint finding in it could only be fixed by hand, in a file the next
 * regeneration overwrites.
 */

import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import { globalIgnores } from 'eslint/config'
import pluginVue from 'eslint-plugin-vue'

export default defineConfigWithVueTs(
  {
    name: 'substate-admin/files',
    files: ['**/*.ts', '**/*.mts', '**/*.tsx', '**/*.vue'],
  },

  globalIgnores([
    'dist/**',
    'coverage/**',
    // Playwright's output, and the traces CI uploads when a scenario fails.
    'playwright-report/**',
    'test-results/**',
    'src/api/schema.d.ts',
  ]),

  // `flat/essential`, not `flat/recommended`. The tiers above essential are largely a formatter
  // in rule form — where an attribute wraps, whether a void element self-closes — and there is no
  // Prettier in this project to settle those. A lint run that fails on a line break teaches people
  // to pass `--max-warnings` something, and then it catches nothing at all. Essential is the tier
  // whose findings are bugs: a missing `:key`, a mutated prop, a `v-if` racing a `v-for`.
  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,

  {
    name: 'substate-admin/rules',
    rules: {
      // Single-word component names are fine for views (`Dashboard.vue` is not a custom element
      // it could collide with), but every component in this project is named for what it is, so
      // the rule stays on and the exceptions are argued one at a time.
      'vue/multi-word-component-names': 'error',

      // An unused binding is either a leftover or a mistake, and both want deleting. The
      // underscore prefix is the way to say "required by the signature, unused on purpose" —
      // the same convention tsconfig's noUnusedParameters uses.
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
    },
  },
)
