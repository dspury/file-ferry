/**
 * Ambient declarations for the stylesheet side-effect imports in `main.tsx`.
 *
 * `vite/client` declares `*.css` as an empty module (`declare module '*.css' {}`),
 * which TypeScript 6 no longer accepts as a target for a side-effect import
 * (TS2882). Declaring them here keeps the imports typed without disabling the
 * check for everything else.
 */
declare module '*.css';
declare module '@fontsource-variable/archivo/wght.css';
declare module '@fontsource/ibm-plex-mono/latin-400.css';
declare module '@fontsource/ibm-plex-mono/latin-500.css';
declare module '@fontsource/ibm-plex-mono/latin-600.css';
