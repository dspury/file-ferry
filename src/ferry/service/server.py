"""JSON-RPC server for the sidecar.

The foundation cut implements the request/response loop and the
event emission. The actual method handlers are wired in by the
``application`` package; until they exist, every method returns
``method_not_found``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import IO, NoReturn

from ferry.service import PROTOCOL_VERSION
from ferry.service.protocol import (
    ErrorFrame,
    Frame,
    RequestFrame,
    RpcError,
    decode_frame,
    encode_frame,
)


class SidecarServer:
    """A minimal JSON-RPC server over stdio.

    The server reads newline-delimited JSON frames from ``stdin`` and
    writes responses to ``stdout``. Asynchronous events can be emitted
    via :meth:`send_event` from another thread or task.
    """

    def __init__(self, db_path: object | None = None) -> None:
        self._db_path = db_path
        self._handlers: dict[str, Callable[[RequestFrame], object]] = {}
        self._out: IO[str] | None = None

    def register(self, method: str, handler: Callable[[RequestFrame], object]) -> None:
        """Register a method handler."""
        self._handlers[method] = handler

    def run(self, stdin: IO[str], stdout: IO[str]) -> int:
        """Run the server until EOF on stdin. Returns the exit code."""
        self._out = stdout
        for line in stdin:
            frame = decode_frame(line)
            if frame is None:
                self._write_error("", "parse_error", "unparseable frame")
                continue
            if frame.kind != "request":
                # Events and unsolicited responses are not expected on stdin.
                continue
            self._dispatch(frame)
        return 0

    def run_once(self, stdin: IO[str], stdout: IO[str]) -> int:
        """Run the server for a single request/response round. Returns the exit code."""
        self._out = stdout
        line = stdin.readline()
        if not line:
            return 0
        frame = decode_frame(line)
        if frame is None:
            self._write_error("", "parse_error", "unparseable frame")
            return 0
        if frame.kind != "request":
            return 0
        self._dispatch(frame)
        return 0

    def send_event(self, method: str, params: dict[str, object]) -> None:
        """Emit an asynchronous event frame."""
        if self._out is None:
            return
        self._out.write(encode_frame(_make_event(method, params)))
        self._out.flush()

    def _dispatch(self, frame: RequestFrame) -> None:
        handler = self._handlers.get(frame.method)
        if handler is None:
            self._write_error(frame.id, "method_not_found", f"unknown method: {frame.method}")
            return
        try:
            result = handler(frame)
        except _RpcError as exc:
            self._write_error(frame.id, exc.code, exc.message, exc.data)
        except Exception as exc:
            self._write_error(frame.id, "internal_error", str(exc))
        else:
            self._write_response(frame.id, result)

    def _write_response(self, request_id: str, result: object) -> None:
        if self._out is None:
            return
        from ferry.service.protocol import ResponseFrame  # local import to avoid cycle

        self._out.write(
            encode_frame(
                ResponseFrame(
                    jsonrpc="2.0",
                    v=PROTOCOL_VERSION,
                    kind="response",
                    id=request_id,
                    result=result,
                )
            )
        )
        self._out.flush()

    def _write_error(
        self,
        request_id: str,
        code: str,
        message: str,
        data: dict[str, object] | None = None,
    ) -> None:
        if self._out is None:
            return
        self._out.write(
            encode_frame(
                ErrorFrame(
                    jsonrpc="2.0",
                    v=PROTOCOL_VERSION,
                    kind="error",
                    id=request_id,
                    error=RpcError(code=code, message=message, data=data),  # type: ignore[arg-type]
                )
            )
        )
        self._out.flush()


class _RpcError(Exception):
    """An exception that maps to a typed RPC error response."""

    def __init__(self, code: str, message: str, data: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def rpc_error(code: str, message: str, data: dict[str, object] | None = None) -> NoReturn:
    """Raise an ``_RpcError`` from a handler."""
    raise _RpcError(code, message, data)


def _make_event(method: str, params: dict[str, object]) -> Frame:
    from ferry.service.protocol import EventFrame

    return EventFrame(
        jsonrpc="2.0",
        v=PROTOCOL_VERSION,
        kind="event",
        method=method,
        params=params,
    )
