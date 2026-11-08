import js from '@eslint/js'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: globals.browser },
    plugins: { react, 'react-hooks': reactHooks },
    settings: { react: { version: 'detect' } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // User-facing strings live in src/i18n/es.ts, never inline (CONTRIBUTING.md).
      'react/jsx-no-literals': ['error', { noStrings: true, ignoreProps: true }],
      // jsx-no-literals skips props, but these props are read by people.
      'no-restricted-syntax': [
        'error',
        {
          selector:
            'JSXAttribute[name.name=/^(aria-label|aria-description|aria-placeholder|alt|title|placeholder)$/] > Literal',
          message: 'User-facing attribute text belongs in src/i18n/es.ts.',
        },
      ],
    },
  },
  {
    files: ['**/*.test.{ts,tsx}', 'src/test/**'],
    rules: { 'react/jsx-no-literals': 'off', 'no-restricted-syntax': 'off' },
  },
)
