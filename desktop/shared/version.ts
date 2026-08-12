/**
 * Frozen protocol version (per ADR-0002).
 *
 * Both the desktop shell and the Python sidecar declare this version on
 * the first frame. If the major version differs, the lower-version
 * endpoint declines with `version_mismatch` and the desktop surfaces the
 * recovery action.
 *
 * Bumping this constant requires a new ADR.
 */
export const PROTOCOL_VERSION = 1 as const;

export type ProtocolVersion = typeof PROTOCOL_VERSION;
