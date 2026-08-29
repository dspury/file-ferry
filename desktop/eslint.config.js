/**
 * Flat config (ESLint 9+). Replaces `.eslintrc.cjs`, which the eslintrc
 * format made unusable past ESLint 8.
 *
 * This is a like-for-like port, not a re-think: same parser, same four
 * shared configs, same three rule overrides, same ignores. Effective rule
 * parity with the old config was checked per file with
 * `eslint --print-config` before and after, so nothing was silently
 * dropped or newly enabled -- a migration that quietly loses rules is worse
 * than not migrating.
 *
 * ESLint is pinned to 9.x rather than 10 because `eslint-plugin-react`
 * (7.37.5, its latest) peers on `<=9.7`. See #121.
 */
import js from '@eslint/js';
import globals from 'globals';
import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import reactPlugin from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';

export default [
  // `ignorePatterns` in the old config. Flat config drops the implicit
  // `**/` prefix, so directories need the trailing `**`.
  {
    ignores: ['dist/**', 'node_modules/**', 'release/**', 'sidecar/**', '**/*.cjs'],
  },

  js.configs.recommended,

  {
    files: ['**/*.ts', '**/*.tsx'],
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 2022,
      sourceType: 'module',
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      // The old config's `env: { browser, node, es2022 }`.
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.es2022,
      },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      react: reactPlugin,
      'react-hooks': reactHooks,
    },
    settings: {
      react: { version: 'detect' },
    },
    rules: {
      // `plugin:@typescript-eslint/recommended` in eslintrc form pulled in
      // `eslint-recommended` first, which switches off the 19 core rules
      // that TypeScript already enforces better -- `no-undef` among them.
      // Spreading only `recommended.rules` drops that, and `no-undef` then
      // fires on type-only globals (`React`, `NodeJS`) that tsc resolves
      // fine. Caught by the print-config parity diff, which is what it is
      // there for.
      ...tsPlugin.configs['eslint-recommended'].overrides[0].rules,
      ...tsPlugin.configs.recommended.rules,
      ...reactPlugin.configs.flat.recommended.rules,
      ...reactHooks.configs.recommended.rules,

      // The three overrides carried over verbatim.
      'react/react-in-jsx-scope': 'off',
      'react/prop-types': 'off',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
];
