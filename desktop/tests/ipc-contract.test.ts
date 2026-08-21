/**
 * IPC contract tests. The TypeScript types in `shared/ipc-schema.ts`
 * and `shared/ipc-methods.ts` are one side of the contract; the
 * pydantic models in `src/media_mate/service/protocol.py` are the
 * other. These tests prove the TypeScript side parses and emits
 * frames that round-trip through the same code paths the sidecar
 * will receive.
 *
 * The matching Python tests live in
 * `tests/test_service_protocol.py`. When the protocol changes,
 * BOTH tests must be updated in the same commit.
 */
import { describe, expect, it } from 'vitest';
import {
  decodeFrame,
  encodeFrame,
  PROTOCOL_VERSION,
  type Frame,
  type RequestFrame,
  type ResponseFrame,
  type EventFrame,
  type ErrorFrame,
} from '../shared/ipc-schema.js';
import { PROTOCOL_VERSION as VERSION_FROM_VERSION_MODULE } from '../shared/version.js';

describe('protocol version', () => {
  it('is exported from both modules to the same value', () => {
    expect(PROTOCOL_VERSION).toBe(VERSION_FROM_VERSION_MODULE);
    expect(PROTOCOL_VERSION).toBe(1);
  });
});

describe('frame encoding', () => {
  it('round-trips a request frame', () => {
    const request: RequestFrame = {
      jsonrpc: '2.0',
      v: PROTOCOL_VERSION,
      kind: 'request',
      id: 'abc-123',
      method: 'project.list',
      params: {},
    };
    const wire = encodeFrame(request);
    expect(wire.endsWith('\n')).toBe(true);
    const decoded = decodeFrame(wire);
    expect(decoded).toEqual(request);
  });

  it('round-trips a response frame', () => {
    const response: ResponseFrame = {
      jsonrpc: '2.0',
      v: PROTOCOL_VERSION,
      kind: 'response',
      id: 'abc-123',
      result: { projects: [] },
    };
    const decoded = decodeFrame(encodeFrame(response));
    expect(decoded).toEqual(response);
  });

  it('round-trips an event frame', () => {
    const event: EventFrame = {
      jsonrpc: '2.0',
      v: PROTOCOL_VERSION,
      kind: 'event',
      method: 'sidecar.ready',
      params: { timestamp: '2026-08-12T17:30:00Z' },
    };
    const decoded = decodeFrame(encodeFrame(event));
    expect(decoded).toEqual(event);
  });

  it('round-trips an error frame', () => {
    const error: ErrorFrame = {
      jsonrpc: '2.0',
      v: PROTOCOL_VERSION,
      kind: 'error',
      id: 'abc-123',
      error: { code: 'invalid_params', message: 'missing name' },
    };
    const decoded = decodeFrame(encodeFrame(error));
    expect(decoded).toEqual(error);
  });
});

describe('frame decoding', () => {
  it('returns null on empty line', () => {
    expect(decodeFrame('')).toBeNull();
    expect(decodeFrame('   ')).toBeNull();
  });

  it('returns null on invalid JSON', () => {
    expect(decodeFrame('{not json')).toBeNull();
  });

  it('returns null on missing jsonrpc field', () => {
    expect(
      decodeFrame(JSON.stringify({ v: 1, kind: 'request', id: 'x', method: 'a', params: {} })),
    ).toBeNull();
  });

  it('returns null on version mismatch', () => {
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

  it('returns null on unknown kind', () => {
    const bad = JSON.stringify({
      jsonrpc: '2.0',
      v: PROTOCOL_VERSION,
      kind: 'bogus',
      id: 'x',
    });
    expect(decodeFrame(bad)).toBeNull();
  });

  it('returns null on missing request id', () => {
    const bad = JSON.stringify({
      jsonrpc: '2.0',
      v: PROTOCOL_VERSION,
      kind: 'request',
      method: 'a',
      params: {},
    });
    expect(decodeFrame(bad)).toBeNull();
  });

  it('returns null on missing response result', () => {
    const bad = JSON.stringify({
      jsonrpc: '2.0',
      v: PROTOCOL_VERSION,
      kind: 'response',
      id: 'x',
    });
    expect(decodeFrame(bad)).toBeNull();
  });
});

describe('NDJSON framing', () => {
  it('multiple frames are line-delimited', () => {
    const frames: Frame[] = [
      {
        jsonrpc: '2.0',
        v: PROTOCOL_VERSION,
        kind: 'event',
        method: 'sidecar.ready',
        params: { timestamp: '2026-08-12T17:30:00Z' },
      },
      {
        jsonrpc: '2.0',
        v: PROTOCOL_VERSION,
        kind: 'response',
        id: 'xyz',
        result: { projects: [] },
      },
    ];
    const wire = frames.map(encodeFrame).join('');
    const lines = wire.split('\n').filter((l) => l.length > 0);
    expect(lines).toHaveLength(2);
    for (const line of lines) {
      expect(decodeFrame(line)).not.toBeNull();
    }
  });
});
