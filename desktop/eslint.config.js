/**
 * Flat config (ESLint 10).
 *
 * Originally a flat port of `.eslintrc.cjs` (ESLint 9), which the eslintrc
 * format made unusable past ESLint 8. That port was like-for-like: same
 * parser, same shared configs, same rule overrides, verified per file with
 * `eslint --print-config`.
 *
 * ESLint 10 landed by dropping `eslint-plugin-react`. Its latest release
 * (7.37.5) peers `eslint <=9.7` and no newer one is queued, so holding the
 * upgrade waited on nothing. It is also largely class-component era and
 * irrelevant here, and its two largest recommended rules
 * (`react-in-jsx-scope`, `prop-types`) were already switched off below.
 *
 * `eslint-plugin-react-hooks` stays — `rules-of-hooks` and
 * `exhaustive-deps` are the valuable ones. `@eslint-react/eslint-plugin`
 * (TypeScript-first) replaces what is genuinely lost, notably
 * `jsx-key` -> `@eslint-react/no-missing-key`, which TypeScript does not
 * catch. See the work order B-4a and #121.
 */
import js from '@eslint/js';
import globals from 'globals';
import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import eslintReact from '@eslint-react/eslint-plugin';
import reactHooks from 'eslint-plugin-react-hooks';

export default [
  // `ignorePatterns` in the old config. Flat config drops the implicit
  // `**/` prefix, so directories need the trailing `**`.
  {
    ignores: ['dist/**', 'node_modules/**', 'release/**', 'sidecar/**', '**/*.cjs'],
  },

  js.configs.recommended,

  {
    files: ['**/*.ts', '**/*.tsx', '**/*.cts'],
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
      '@eslint-react': eslintReact,
      'react-hooks': reactHooks,
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
      ...reactHooks.configs.recommended.rules,
      // The TypeScript variant: it turns off the rules TypeScript already
      // covers, so this adds JSX-correctness checks (no-missing-key among
      // them) without duplicating the compiler.
      ...eslintReact.configs['recommended-typescript'].rules,

      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
];
