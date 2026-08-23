/**
 * Renderer entry point. The foundation package ships a minimal
 * placeholder; the real screens (Home, Ingest, Organize, etc.)
 * land in Package 7 of the implementation plan.
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
/*
 * The CinePrompt type pair, bundled rather than fetched.
 *
 * The packaged renderer loads over `file://` behind `font-src 'self'`, and
 * the app has to work with no network at all -- an offload runs in a
 * basement with a card reader, not next to a CDN. Vite emits these faces
 * into `dist/renderer/assets`, so they resolve from the app bundle.
 *
 * Archivo ships as a single variable face covering the whole 100-900 range,
 * which is what lets styles.css ask for 550 and 650 without shipping a file
 * per weight. Plex Mono is static, so only the weights the mono treatments
 * actually use are pulled in: 400 for values, 500 for engraved legends, and
 * 600 for the places a mono glyph carries emphasis -- the stat-tile figures,
 * the stage markers, the severity stamps, the confirm-dialog title, and the
 * engaged position of a segmented control. Without the 600 face Chromium
 * synthesises it, and a faux-bold monospace at 26px is visibly smeared.
 * Latin only; no italics are used.
 */
import '@fontsource-variable/archivo/wght.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@fontsource/ibm-plex-mono/latin-500.css';
import '@fontsource/ibm-plex-mono/latin-600.css';
import { App } from './App.js';
import './styles.css';

const container = document.getElementById('root');
if (!container) {
  throw new Error('root container missing');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
