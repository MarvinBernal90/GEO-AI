/**
 * ==============================================================================
 * LINTER CONFIGURATION (ESLINT FLAT CONFIG)
 * ==============================================================================
 * File: frontend/eslint.config.js
 *
 * Static analysis for Vue 3 SFCs and plain JS modules. Formatting concerns are
 * delegated to Prettier (see .prettierrc); `eslint-config-prettier` must stay
 * last so it disables any ESLint rule that would fight the formatter.
 */
import js from '@eslint/js'
import prettier from 'eslint-config-prettier'
import pluginVue from 'eslint-plugin-vue'
import { defineConfig, globalIgnores } from 'eslint/config'
import globals from 'globals'

export default defineConfig([
  globalIgnores(['dist', 'node_modules']),

  js.configs.recommended,
  ...pluginVue.configs['flat/recommended'],

  {
    files: ['src/**/*.{js,vue}'],
    languageOptions: { globals: globals.browser },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
  {
    files: ['*.config.js'],
    languageOptions: { globals: globals.node },
  },

  prettier,
])
