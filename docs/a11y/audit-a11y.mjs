#!/usr/bin/env node
// C-1 (#95) accessibility audit over CDP against the built Electron renderer.
//
// This is NOT a VoiceOver run. It records (a) Chromium's accessibility tree —
// the tree Chromium hands the platform accessibility API — (b) DOM/ARIA
// attributes, (c) real keyboard traversal and the computed focus ring at each
// stop. See the written record for what that does and does not prove.
//
// usage: node audit-a11y.mjs [cdpPort] [outDir]
// Boot the built renderer first with:
//   FERRY_RENDERER_URL=file://$PWD/dist/renderer/index.html \
//     node_modules/.bin/electron . --remote-debugging-port=9222
import { writeFileSync, mkdirSync } from 'node:fs';

const port = process.argv[2] ?? '9222';
const outDir = process.argv[3] ?? './a11y-out';
const mode = process.argv[4] ?? 'all';
mkdirSync(outDir, { recursive: true });

const ROUTES = [
  { name: 'dashboard', hash: '#/home' },
  { name: 'transfers-empty', hash: '#/transfers' },
  { name: 'transfers-plan', hash: '#/transfers?inv=1&plan=a11y-fake-plan' },
  { name: 'activity', hash: '#/activity' },
  { name: 'projects', hash: '#/projects' },
  { name: 'assets', hash: '#/asset' },
  { name: 'destinations', hash: '#/destinations' },
  { name: 'presets', hash: '#/presets' },
  { name: 'environment', hash: '#/onboarding' },
  { name: 'settings', hash: '#/settings' },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const res = await fetch(`http://127.0.0.1:${port}/json/list`);
const page = (await res.json()).find((t) => t.type === 'page');
if (!page) throw new Error('no page target');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => {
  ws.addEventListener('open', r, { once: true });
  ws.addEventListener('error', j, { once: true });
});
let id = 0;
const pending = new Map();
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const p = pending.get(m.id);
    pending.delete(m.id);
    m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result);
  }
});
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const i = ++id;
    pending.set(i, { resolve, reject });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
const evalJs = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails.exception));
  return r.result.value;
};

await send('Runtime.enable');
await send('Page.enable');
await send('Accessibility.enable');
await send('Emulation.setDeviceMetricsOverride', {
  width: 1280,
  height: 800,
  deviceScaleFactor: 1,
  mobile: false,
});

// ---- keyboard helpers ------------------------------------------------------
const VK = { Tab: 9, ArrowDown: 40, ArrowUp: 38, ArrowLeft: 37, ArrowRight: 39, Enter: 13 };
async function tapKey(key, { shift = false } = {}) {
  const base = {
    key,
    code: key,
    windowsVirtualKeyCode: VK[key],
    nativeVirtualKeyCode: VK[key],
    modifiers: shift ? 8 : 0,
  };
  await send('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...base });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', ...base });
  await sleep(90);
}
async function focused() {
  return evalJs(`(() => {
    const a = document.activeElement || document.body;
    const s = getComputedStyle(a);
    return {
      tag: a.tagName,
      role: a.getAttribute && a.getAttribute('role'),
      label: a.getAttribute && (a.getAttribute('aria-label') || a.getAttribute('aria-labelledby')),
      text: (a.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 70),
      cls: typeof a.className === 'string' ? a.className : (a.className && a.className.baseVal) || '',
      current: a.getAttribute && a.getAttribute('aria-current'),
      selected: a.getAttribute && a.getAttribute('aria-selected'),
      disabled: a.hasAttribute && a.hasAttribute('disabled'),
      tabindex: a.tabIndex,
      outlineColor: s.outlineColor,
      outlineWidth: s.outlineWidth,
    };
  })()`);
}
async function tabTraversal(maxStops = 70) {
  await evalJs('document.activeElement && document.activeElement.blur && document.activeElement.blur()');
  const stops = [];
  for (let i = 0; i < maxStops; i++) {
    await tapKey('Tab');
    const f = await focused();
    const sig = JSON.stringify([f.tag, f.cls, f.label, f.text, f.current]);
    if (stops.length > 0 && sig === stops[stops.length - 1].sig) break; // wrapped / stuck
    stops.push({ ...f, sig });
    if (f.tag === 'BODY') break;
  }
  return stops;
}

async function axTree() {
  const { nodes } = await send('Accessibility.getFullAXTree');
  const propOf = (n, name) => n.properties?.find((p) => p.name === name)?.value?.value;
  const interesting = new Set([
    'navigation',
    'main',
    'complementary',
    'banner',
    'contentinfo',
    'heading',
    'tablist',
    'tab',
    'tabpanel',
    'table',
    'row',
    'columnheader',
    'rowheader',
    'cell',
    'list',
    'listitem',
    'group',
    'radiogroup',
    'radio',
    'checkbox',
    'switch',
    'progressbar',
    'status',
    'alert',
    'alertdialog',
    'dialog',
    'button',
    'link',
    'textbox',
    'searchbox',
    'combobox',
    'listbox',
    'option',
    'separator',
    'toolbar',
  ]);
  const out = [];
  for (const n of nodes) {
    if (n.ignored) continue;
    const role = n.role?.value ?? '?';
    if (!interesting.has(role)) continue;
    const name = (n.name?.value ?? '').trim();
    out.push({
      role,
      name: name.replace(/\s+/g, ' ').slice(0, 110),
      current: propOf(n, 'current'),
      selected: propOf(n, 'selected'),
      disabled: propOf(n, 'disabled'),
      checked: propOf(n, 'checked'),
      expanded: propOf(n, 'expanded'),
      live: propOf(n, 'live'),
      atomic: propOf(n, 'atomic'),
      relevant: propOf(n, 'relevant'),
      valuetext: propOf(n, 'valuetext'),
      level: propOf(n, 'level'),
      invalid: propOf(n, 'invalid'),
      parentId: n.parentId,
    });
  }
  return out;
}

async function domAudit() {
  return evalJs(`(() => {
    const attr = (el, a) => el.getAttribute(a);
    const txt = (el) => (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 90);
    const liveSelectors = '[aria-live], [role=alert], [role=status], [role=log], [aria-busy]';
    return {
      title: document.title,
      h1: [...document.querySelectorAll('h1')].map(txt),
      liveRegions: [...document.querySelectorAll(liveSelectors)].map((el) => ({
        tag: el.tagName, cls: typeof el.className === 'string' ? el.className : '',
        role: attr(el, 'role'), ariaLive: attr(el, 'aria-live'), busy: attr(el, 'aria-busy'),
        label: attr(el, 'aria-label'), text: txt(el),
      })),
      nav: [...document.querySelectorAll('nav[aria-label], [role=navigation]')].map((n) => ({
        label: attr(n, 'aria-label'),
        groups: [...n.querySelectorAll('.nav__group')].map((g) => ({
          label: attr(g, 'aria-label'),
          heading: txt(g.querySelector('.nav__group-label') || { textContent: '' }),
          hidden: g.querySelector('.nav__group-label')?.getAttribute('aria-hidden'),
          items: [...g.querySelectorAll('.nav__item')].map((b) => ({
            name: b.textContent.trim(), current: attr(b, 'aria-current'), tabindex: b.tabIndex,
          })),
        })),
      })),
      tabs: [...document.querySelectorAll('[role=tablist]')].map((tl) => ({
        label: attr(tl, 'aria-label'),
        items: [...tl.querySelectorAll('[role=tab]')].map((t) => ({
          name: t.textContent.trim().replace(/\\s+/g, ' '),
          selected: attr(t, 'aria-selected'), disabled: t.hasAttribute('disabled'),
          tabindex: t.tabIndex, controls: attr(t, 'aria-controls'),
        })),
      })),
      chips: [...document.querySelectorAll('.chip')].slice(0, 12).map((c) => ({
        cls: c.className, text: txt(c),
        glyphHidden: c.querySelector('svg')?.getAttribute('aria-hidden'),
      })),
      banners: [...document.querySelectorAll('.banner')].map((b) => ({
        cls: b.className, role: attr(b, 'role'), label: txt(b.querySelector('.banner__label') || { textContent: '' }),
        text: txt(b), glyphHidden: b.querySelector('svg')?.getAttribute('aria-hidden'),
      })),
      tables: [...document.querySelectorAll('table')].map((t) => ({
        label: attr(t, 'aria-label'),
        headers: [...t.querySelectorAll('thead th')].map((th) => ({ text: txt(th), scope: attr(th, 'scope'), id: attr(th, 'id') })),
        firstRow: [...(t.querySelector('tbody tr')?.querySelectorAll('td') || [])].map((td) => ({
          name: txt(td), headers: attr(td, 'headers'),
          buttonLabels: [...td.querySelectorAll('button')].map((b) => attr(b, 'aria-label') || b.textContent.trim()),
          progressLabels: [...td.querySelectorAll('[role=progressbar]')].map((p) => ({ label: attr(p, 'aria-label'), valueText: attr(p, 'aria-valuetext'), now: attr(p, 'aria-valuenow') })),
        })),
      })),
      focusables: document.querySelectorAll('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])').length,
    };
  })()`);
}

const report = {};
for (const route of ROUTES) {
  const path = route.hash.split('?')[0];
  if (mode !== 'all' && !mode.includes(route.name)) continue;
  await evalJs(`window.location.hash = ${JSON.stringify(route.hash)}`);
  await sleep(1600);
  await evalJs('document.fonts.ready');
  await sleep(200);
  const dom = await domAudit();
  const ax = await axTree();
  const focusStops = await tabTraversal();
  report[route.name] = { hash: route.hash, dom, ax, focusStops };
  writeFileSync(`${outDir}/${route.name}.json`, JSON.stringify(report[route.name], null, 2));
  console.error(`audited ${route.name}: ${ax.length} ax nodes, ${focusStops.length} focus stops`);
}

// ---- interaction probes ----------------------------------------------------
async function navArrows() {
  await evalJs(`window.location.hash = '#/home'`);
  await sleep(1200);
  await evalJs(`document.querySelector('.nav__item--active')?.focus()`);
  const seq = [];
  for (let i = 0; i < 10; i++) {
    await tapKey('ArrowDown');
    seq.push(await focused());
  }
  return seq;
}
async function tabArrows() {
  await evalJs(`window.location.hash = '#/transfers?inv=1&plan=a11y-fake-plan'`);
  await sleep(1600);
  await evalJs(`document.querySelector('.tabs__item--active')?.focus()`);
  const seq = [];
  for (let i = 0; i < 6; i++) {
    await tapKey('ArrowRight');
    seq.push(await focused());
  }
  return seq;
}
// Escape check on the confirm dialog is a static markup check; no dialog is
// open on these routes. Recorded as not-exercised instead.

const interactions = {};
if (mode === 'all' || mode.includes('nav')) interactions.navArrows = await navArrows();
if (mode === 'all' || mode.includes('tabs')) interactions.tabArrows = await tabArrows();
writeFileSync(`${outDir}/interactions.json`, JSON.stringify(interactions, null, 2));
console.error('interactions captured');
ws.close();
