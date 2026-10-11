import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'dist-*', '.vite', '.vite-test-cache-*']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      'react-hooks/set-state-in-effect': 'off',
    },
  },
  {
    files: ['**/*.test.{js,jsx}', 'test/**/*.{js,jsx}'],
    languageOptions: {
      globals: globals.node,
    },
  },
  {
    files: ['src/features/schoolCalendar/components/SchoolCalendarWorkspace.jsx'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
])
