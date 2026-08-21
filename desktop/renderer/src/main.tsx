/**
 * Renderer entry point. The foundation package ships a minimal
 * placeholder; the real screens (Home, Ingest, Organize, etc.)
 * land in Package 7 of the implementation plan.
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
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
