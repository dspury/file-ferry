/**
 * Tests for the renderer's last-resort render-crash boundary (#97).
 *
 * The boundary itself is a class component — React 18 boundaries have no
 * hook form — but everything about it that can go wrong silently is pure
 * and testable without a DOM: what its derived state holds, and that the
 * fallback it renders is a function of that state. The vitest environment
 * is `node`, so these tests call the class methods directly rather than
 * rendering; the mount behaviour (keyed remount per view) lives in
 * App.tsx and is covered by its own structure.
 */
import { describe, expect, it } from 'vitest';
import { ErrorBoundary } from '../renderer/src/components/ErrorBoundary.js';

describe('ErrorBoundary', () => {
  it('derives a holding state from a render error', () => {
    const error = new Error('Cannot read properties of undefined (reading "split")');
    expect(ErrorBoundary.getDerivedStateFromError(error)).toEqual({ error });
  });

  it('holds the error object itself, so the fallback can show its message', () => {
    const error = new Error('boom');
    const state = ErrorBoundary.getDerivedStateFromError(error);
    // The derived state is total on the error it was given: the same object,
    // message included, which is what the fallback's <code> plate renders.
    expect(state.error).toBe(error);
    if (state.error === null) throw new Error('expected the held error');
    expect(state.error.message).toBe('boom');
  });

  it('starts with no error held, so the first render passes children through', () => {
    // Constructed without props: the initial state is what `render` branches
    // on before React ever calls the derived-state method, and it must be
    // the no-error state or every screen would boot into the fallback.
    // SAFETY: React reads props/state via internal machinery; this test
    // only reads the declared `state` field the class initializes itself.
    const boundary = new ErrorBoundary({ children: null });
    expect(boundary.state).toEqual({ error: null });
  });
});
