/**
 * JSON-RPC 2.0 envelope used by the IPC between Electron main and the
 * Python sidecar. See ADR-0002 for the wire format rationale.
 *
 * Each frame is a single JSON object on one line (NDJSON), terminated
 * by `\n`. The kind field discriminates request / response / event /
 * error in addition to the JSON-RPC standard. Pydantic models on the
 * sidecar enforce the same shape.
 */
import { PROTOCOL_VERSION } from './version.js';

export { PROTOCOL_VERSION };

export type FrameKind = 'request' | 'response' | 'event' | 'error';

export interface RequestFrame<P = unknown> {
  readonly jsonrpc: '2.0';
  readonly v: typeof PROTOCOL_VERSION;
  readonly kind: 'request';
  readonly id: string;
  readonly method: string;
  readonly params: P;
}

export interface ResponseFrame<R = unknown> {
  readonly jsonrpc: '2.0';
  readonly v: typeof PROTOCOL_VERSION;
  readonly kind: 'response';
  readonly id: string;
  readonly result: R;
}

export interface EventFrame<P = unknown> {
  readonly jsonrpc: '2.0';
  readonly v: typeof PROTOCOL_VERSION;
  readonly kind: 'event';
  readonly method: string;
  readonly params: P;
}

export interface ErrorFrame {
  readonly jsonrpc: '2.0';
  readonly v: typeof PROTOCOL_VERSION;
  readonly kind: 'error';
  readonly id: string;
  readonly error: RpcError;
}

export type Frame = RequestFrame | ResponseFrame | EventFrame | ErrorFrame;

export interface RpcError {
  readonly code: RpcErrorCode;
  readonly message: string;
  readonly data?: Record<string, unknown>;
}

/**
 * Stable error codes. The string value is what travels on the wire;
 * the numeric counterpart exists for legacy JSON-RPC clients.
 */
export type RpcErrorCode =
  | 'parse_error'
  | 'invalid_request'
  | 'method_not_found'
  | 'invalid_params'
  | 'schema_invalid'
  | 'version_mismatch'
  | 'internal_error'
  | 'cancelled'
  | 'needs_attention'
  | 'unsafe_state';

export const RPC_ERROR_CODES: Record<RpcErrorCode, number> = {
  parse_error: -32700,
  invalid_request: -32600,
  method_not_found: -32601,
  invalid_params: -32602,
  schema_invalid: -32602,
  version_mismatch: -32001,
  internal_error: -32603,
  cancelled: -32002,
  needs_attention: -32003,
  unsafe_state: -32004,
};

/**
 * Encode a frame as a single newline-terminated JSON line.
 * Throws on circular references or values that JSON cannot serialize.
 */
export function encodeFrame(frame: Frame): string {
  return JSON.stringify(frame) + '\n';
}

/**
 * Decode a single frame from a JSON line. Returns null on JSON parse
 * failure or schema mismatch — the caller should emit a parse_error
 * frame rather than crashing the stream.
 */
export function decodeFrame(line: string): Frame | null {
  const trimmed = line.trim();
  if (trimmed.length === 0) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return null;
  }
  if (!isFrame(parsed)) return null;
  return parsed;
}

function isFrame(value: unknown): value is Frame {
  if (typeof value !== 'object' || value === null) return false;
  const obj = value as Record<string, unknown>;
  if (obj['jsonrpc'] !== '2.0') return false;
  if (obj['v'] !== PROTOCOL_VERSION) return false;
  const kind = obj['kind'];
  if (kind !== 'request' && kind !== 'response' && kind !== 'event' && kind !== 'error') {
    return false;
  }
  if (kind === 'request' || kind === 'response' || kind === 'error') {
    if (typeof obj['id'] !== 'string') return false;
  }
  if (kind === 'request' || kind === 'event') {
    if (typeof obj['method'] !== 'string') return false;
  }
  if (kind === 'response' && !('result' in obj)) return false;
  if (kind === 'error' && !('error' in obj)) return false;
  return true;
}
