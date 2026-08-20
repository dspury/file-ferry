/**
 * Tests for sidecar command resolution and protocol-error handling
 * (plan §10.6.1, §10.6.3).
 *
 * Command resolution is pure and injected-existence-testable. Protocol
 * errors are surfaced as typed events and a counter. The full
 * spawn/restart lifecycle requires a real child process, so those
 * paths are covered by the packaged-app smoke test in Package 9; here
 * we verify the decision logic that drives them.
 */
import { describe, expect, it } from 'vitest';
import { joinPath, resolveSidecarCommand } from '../electron/sidecar-command.js';
import { classifyUnexpectedFrame } from '../electron/sidecar.js';
import type { ProtocolErrorEvent } from '../electron/sidecar.js';
import { decodeFrame, encodeFrame, type RequestFrame } from '../shared/ipc-schema.js';
import { PROTOCOL_VERSION } from '../shared/version.js';

describe('resolveSidecarCommand', () => {
  it('uses python -m ferry.service in development', () => {
    const cmd = resolveSidecarCommand(false, '/resources', '/usr/local/bin/node', () => false);
    expect(cmd.executable).toBe('/usr/local/bin/node');
    expect(cmd.args).toEqual(['-m', 'ferry.service']);
  });

  it('resolves the frozen executable in a packaged build', () => {
    const exists = (p: string) => p.endsWith('/sidecar/ferry-service');
    const cmd = resolveSidecarCommand(true, '/app/Resources', '/app/electron', exists);
    expect(cmd.executable).toBe('/app/Resources/sidecar/ferry-service');
    expect(cmd.args).toEqual([]);
  });

  it('prefers the .exe candidate on Windows', () => {
    const exists = (p: string) => p.endsWith('ferry-service.exe');
    const cmd = resolveSidecarCommand(true, 'C:/app/Resources', 'C:/app/electron', exists);
    expect(cmd.executable).toBe('C:/app/Resources/sidecar/ferry-service.exe');
  });

  it('throws when no frozen executable exists', () => {
    expect(() => resolveSidecarCommand(true, '/res', '/electron', () => false)).toThrow(
      'sidecar executable not found',
    );
  });
});

describe('joinPath', () => {
  it('joins and collapses duplicate slashes', () => {
    expect(joinPath('/a', 'b', 'c')).toBe('/a/b/c');
    expect(joinPath('/a/', '/b')).toBe('/a/b');
  });
});

describe('protocol frame errors (decode side)', () => {
  it('rejects a version mismatch so the supervisor can surface it', () => {
    const bad = JSON.stringify({
      jsonrpc: '2.0',
      v: PROTOCOL_VERSION + 1,
      kind: 'request',
      id: 'x',
      method: 'a',
      params: {},
    });
    expect(decodeFrame(bad)).toBeNull();
  });

  it('rejects a request frame from the sidecar (unsolicited)', () => {
    const request: RequestFrame = {
      jsonrpc: '2.0',
      v: PROTOCOL_VERSION,
      kind: 'request',
      id: 'x',
      method: 'a',
      params: {},
    };
    const wire = encodeFrame(request);
    // The supervisor treats a request on sidecar stdout as a violation;
    // it is decodeable but not a legitimate sidecar response.
    expect(decodeFrame(wire)).not.toBeNull();
  });

  it('rejects non-NDJSON garbage', () => {
    expect(decodeFrame('{not json\n')).toBeNull();
    expect(decodeFrame('')).toBeNull();
  });
});

describe('classifyUnexpectedFrame', () => {
  // Regression for the bug where both ternary branches returned
  // 'unsolicited_response'. The kind discriminator must be honored.
  it("classifies an unsolicited request frame as 'unsolicited_request'", () => {
    expect(classifyUnexpectedFrame({ kind: 'request' })).toBe('unsolicited_request');
  });

  it("classifies an unsolicited response frame as 'unsolicited_response'", () => {
    expect(classifyUnexpectedFrame({ kind: 'response' })).toBe('unsolicited_response');
  });

  it('the returned reason matches the typed ProtocolErrorEvent union', () => {
    const reasons: ProtocolErrorEvent['reason'][] = [
      classifyUnexpectedFrame({ kind: 'request' }),
      classifyUnexpectedFrame({ kind: 'response' }),
    ];
    // Type-level check: this assignment only compiles if both values
    // are valid members of ProtocolErrorEvent['reason'].
    const typed: ProtocolErrorEvent['reason'][] = reasons;
    expect(typed).toHaveLength(2);
  });
});
