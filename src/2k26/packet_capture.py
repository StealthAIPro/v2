"""WinDivert-backed packet delay engine."""

from __future__ import annotations

import collections
import ipaddress
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from stats import WelfordStats


LOGGER = logging.getLogger(__name__)


class PacketCaptureError(RuntimeError):
    """Raised when packet interception cannot be started safely."""


class PacketCapture:
    """Intercept UDP packets and release them after configurable delays."""

    DEFAULT_MAX_BUFFERED_PACKETS = 8_192
    DEFAULT_MAX_BUFFERED_BYTES = 16 * 1024 * 1024

    # CourtLink-style shot detection: this is UDP/IP payload length, not the
    # total raw packet length.  A candidate must also be arriving from a
    # non-local source (server -> player).
    SHOT_PAYLOAD_SIZE = 99

    def __init__(
        self,
        filter_str: str = "udp",
        *,
        delay_ms: int = 0,
        shot_delay_ms: int = 0,
        max_buffered_packets: int = DEFAULT_MAX_BUFFERED_PACKETS,
        max_buffered_bytes: int = DEFAULT_MAX_BUFFERED_BYTES,
        handle_factory: Callable[[str], Any] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if max_buffered_packets < 1:
            raise ValueError("max_buffered_packets must be positive")
        if max_buffered_bytes < 1:
            raise ValueError("max_buffered_bytes must be positive")

        self._filter = filter_str
        self._delay_ms = self._clamp_delay(delay_ms)
        self._shot_delay_ms = self._clamp_delay(shot_delay_ms)
        self._max_buffered_packets = max_buffered_packets
        self._max_buffered_bytes = max_buffered_bytes
        self._handle_factory = handle_factory
        self._clock = clock

        self._jitter_buf: collections.deque[tuple[float, Any, int]] = collections.deque()
        self._shot_buf: collections.deque[tuple[float, Any, int]] = collections.deque()
        self._jitter_bytes = 0
        self._shot_bytes = 0
        self._jitter_condition = threading.Condition()
        self._shot_condition = threading.Condition()
        self._send_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._stats = WelfordStats()

        self._stop_event = threading.Event()
        self._capture_exited = threading.Event()
        self._handle: Any | None = None
        self._state = "stopped"
        self._last_error: str | None = None
        self._bypassed_packets = 0
        self._last_bypass_log = 0.0
        self._threads: list[threading.Thread] = []

    @staticmethod
    def _clamp_delay(value: int) -> int:
        return max(0, min(500, int(value)))

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._state == "running" and not self._stop_event.is_set()

    @property
    def threads(self) -> tuple[threading.Thread, ...]:
        return tuple(self._threads)

    @property
    def last_error(self) -> str | None:
        with self._state_lock:
            return self._last_error

    def set_delay(self, ms: int) -> None:
        with self._jitter_condition:
            self._delay_ms = self._clamp_delay(ms)
            self._jitter_condition.notify_all()

    def set_shot_delay(self, ms: int) -> None:
        with self._shot_condition:
            self._shot_delay_ms = self._clamp_delay(ms)
            self._shot_condition.notify_all()

    def start(self) -> None:
        """Open WinDivert and start worker threads."""
        with self._state_lock:
            if self._state == "running":
                return
            if self._state == "stopping":
                raise PacketCaptureError("Packet engine is still stopping.")

            self._stop_event.clear()
            self._capture_exited.clear()
            self._last_error = None

            handle = None
            try:
                factory = self._handle_factory
                if factory is None:
                    import pydivert
                    factory = pydivert.WinDivert
                handle = factory(self._filter)
                handle.open()
            except Exception as exc:
                if handle is not None and getattr(handle, "is_open", True):
                    self._close_handle(handle)
                self._state = "stopped"
                message = self._format_start_error(exc)
                self._last_error = message
                LOGGER.exception("Unable to start WinDivert")
                raise PacketCaptureError(message) from exc

            self._handle = handle
            self._state = "running"
            self._threads = [
                threading.Thread(target=self._capture_loop, daemon=True, name="packet-capture"),
                threading.Thread(target=self._release_loop, args=(False,), daemon=True, name="jitter-release"),
                threading.Thread(target=self._release_loop, args=(True,), daemon=True, name="shot-release"),
            ]
            for thread in self._threads:
                thread.start()

        LOGGER.info("Packet engine started with filter %s", self._filter)

    def stop(self) -> None:
        """Stop workers and reinject every packet still held by the app."""
        with self._state_lock:
            if self._state == "stopped" and self._handle is None:
                return
            self._state = "stopping"
            self._stop_event.set()

        with self._jitter_condition:
            self._jitter_condition.notify_all()
        with self._shot_condition:
            self._shot_condition.notify_all()

        self._capture_exited.wait(timeout=0.15)

        handle = self._handle
        flush_failures = 0
        close_failed = False
        if handle is not None:
            flush_failures = self._flush_buffers(handle)
            close_failed = not self._close_handle(handle)

        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=0.5)

        with self._state_lock:
            self._handle = None
            self._threads = []
            self._state = "stopped"

        LOGGER.info("Packet engine stopped")
        if flush_failures or close_failed:
            details = []
            if flush_failures:
                details.append(f"{flush_failures} buffered packet(s) could not be restored")
            if close_failed:
                details.append("the WinDivert handle did not close cleanly")
            raise PacketCaptureError(
                "Packet engine shutdown was incomplete: " + "; ".join(details) + "."
            )

    def get_stats(self) -> dict[str, int | float | str | None]:
        stats = self._stats.snapshot()
        with self._jitter_condition:
            jitter_depth = len(self._jitter_buf)
        with self._shot_condition:
            shot_depth = len(self._shot_buf)
        with self._state_lock:
            state = self._state
            error = self._last_error
            bypassed = self._bypassed_packets
        return {
            **stats,
            "jitter_depth": jitter_depth,
            "shot_depth": shot_depth,
            "bypassed": bypassed,
            "state": state,
            "error": error,
        }

    def _capture_loop(self) -> None:
        handle = self._handle
        if handle is None:
            self._capture_exited.set()
            return

        try:
            while not self._stop_event.is_set():
                try:
                    packet = handle.recv()
                except Exception as exc:
                    if not self._stop_event.is_set():
                        self._record_runtime_error("Packet capture failed", exc)
                    break

                captured_at = self._clock()
                if self._stop_event.is_set():
                    self._send_packet(handle, packet, captured_at, record_stats=False)
                    break

                packet_size = self._packet_size(packet)
                is_shot = self._is_shot_candidate(packet)
                if not self._queue_packet(
                    captured_at,
                    packet,
                    packet_size,
                    is_shot=is_shot,
                ):
                    self._send_packet(handle, packet, captured_at)
        finally:
            self._capture_exited.set()

    @classmethod
    def _is_shot_candidate(cls, packet: Any) -> bool:
        """Match CourtLink's shot candidate rule without using raw packet size.

        A candidate is traffic coming from a remote/server source whose
        packet.payload is exactly 99 bytes. Outbound/local traffic cannot be a
        shot candidate and therefore never enters the fixed shot-delay queue.
        """
        if not cls._is_remote_source(packet):
            return False
        return cls._payload_size(packet) == cls.SHOT_PAYLOAD_SIZE

    @staticmethod
    def _payload_size(packet: Any) -> int:
        payload = getattr(packet, "payload", None)
        if payload is None:
            return 0
        try:
            return len(payload)
        except TypeError:
            return 0

    @staticmethod
    def _is_remote_source(packet: Any) -> bool:
        """Return True when the packet source is not a local/private address."""
        src = getattr(packet, "src_addr", None)
        if not src:
            return False

        # Use Python's address classification when possible. This covers the
        # RFC1918 ranges plus loopback/link-local/IPv6 local addresses and is a
        # safer version of CourtLink's string-prefix local-address check.
        try:
            address = ipaddress.ip_address(str(src).split("%", 1)[0])
            return not (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_unspecified
                or address.is_multicast
            )
        except ValueError:
            # If an unusual address representation cannot be parsed, fail
            # closed so it cannot accidentally trigger the shot delay.
            return False

    def _queue_packet(
        self,
        captured_at: float,
        packet: Any,
        packet_size: int,
        *,
        is_shot: bool,
    ) -> bool:
        condition = self._shot_condition if is_shot else self._jitter_condition
        buffer = self._shot_buf if is_shot else self._jitter_buf

        with condition:
            delay = self._shot_delay_ms if is_shot else self._delay_ms
            if delay <= 0:
                return False
            buffered_bytes = self._shot_bytes if is_shot else self._jitter_bytes
            if (
                len(buffer) >= self._max_buffered_packets
                or buffered_bytes + packet_size > self._max_buffered_bytes
            ):
                self._record_bypass()
                return False
            buffer.append((captured_at, packet, packet_size))
            if is_shot:
                self._shot_bytes += packet_size
            else:
                self._jitter_bytes += packet_size
            condition.notify()
            return True

    def _record_bypass(self) -> None:
        now = self._clock()
        with self._state_lock:
            self._bypassed_packets += 1
            should_log = now - self._last_bypass_log >= 1.0
            if should_log:
                self._last_bypass_log = now
        if should_log:
            LOGGER.warning("Traffic load is high; some traffic was sent without delay")

    def _release_loop(self, is_shot: bool) -> None:
        condition = self._shot_condition if is_shot else self._jitter_condition
        buffer = self._shot_buf if is_shot else self._jitter_buf

        while not self._stop_event.is_set():
            item = None
            with condition:
                while not buffer and not self._stop_event.is_set():
                    condition.wait()
                if self._stop_event.is_set():
                    break

                captured_at, packet, _packet_size = buffer[0]
                delay_ms = self._shot_delay_ms if is_shot else self._delay_ms
                remaining = captured_at + delay_ms / 1000 - self._clock()
                if remaining > 0:
                    condition.wait(timeout=remaining)
                    continue
                item = buffer.popleft()
                if is_shot:
                    self._shot_bytes -= item[2]
                else:
                    self._jitter_bytes -= item[2]

            if item is not None and self._handle is not None:
                self._send_packet(self._handle, item[1], item[0])

    def _send_packet(
        self,
        handle: Any,
        packet: Any,
        captured_at: float,
        *,
        record_stats: bool = True,
    ) -> bool:
        try:
            with self._send_lock:
                handle.send(packet)
            if record_stats:
                self._stats.update(max(0.0, (self._clock() - captured_at) * 1000))
            return True
        except Exception as exc:
            if not self._stop_event.is_set():
                self._record_runtime_error("Packet reinjection failed", exc)
            else:
                LOGGER.warning("Could not reinject a packet during shutdown: %s", exc)
            return False

    def _flush_buffers(self, handle: Any) -> int:
        pending: list[tuple[float, Any, int]] = []
        with self._jitter_condition:
            pending.extend(self._jitter_buf)
            self._jitter_buf.clear()
            self._jitter_bytes = 0
        with self._shot_condition:
            pending.extend(self._shot_buf)
            self._shot_buf.clear()
            self._shot_bytes = 0

        pending.sort(key=lambda item: item[0])
        failed = 0
        for captured_at, packet, _packet_size in pending:
            if not self._send_packet(handle, packet, captured_at, record_stats=False):
                failed += 1
        if failed:
            LOGGER.error("Failed to reinject %d buffered packets during shutdown", failed)
        return failed

    def _record_runtime_error(self, context: str, exc: Exception) -> None:
        message = f"{context}: {exc}"
        with self._state_lock:
            self._last_error = message
            self._state = "error"
        self._stop_event.set()
        with self._jitter_condition:
            self._jitter_condition.notify_all()
        with self._shot_condition:
            self._shot_condition.notify_all()
        LOGGER.exception(context)

    @staticmethod
    def _packet_size(packet: Any) -> int:
        raw = getattr(packet, "raw", None)
        if raw is not None:
            return len(raw)
        try:
            return len(packet)
        except TypeError:
            payload = getattr(packet, "payload", b"")
            return len(payload)

    @staticmethod
    def _format_start_error(exc: Exception) -> str:
        if getattr(exc, "winerror", None) == 5 or isinstance(exc, PermissionError):
            return (
                "Windows blocked the stabilizer. Close the app, open it again, "
                "and approve the administrator prompt."
            )
        return f"The stabilizer could not start: {exc}"

    @staticmethod
    def _close_handle(handle: Any) -> bool:
        try:
            handle.close()
            return True
        except Exception:
            LOGGER.exception("Unable to close WinDivert handle")
            return False
