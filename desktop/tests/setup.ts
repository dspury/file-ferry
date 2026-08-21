/**
 * Test setup. The IPC contract tests run in-process — no Electron
 * runtime, no real sidecar. The shared JSON-RPC parser/encoder is
 * pure; the supervisor is exercised with a mock child process.
 */
import { vi } from 'vitest';

vi.useRealTimers();
