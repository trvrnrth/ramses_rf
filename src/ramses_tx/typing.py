#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
"""RAMSES RF - Typing for RamsesProtocol & RamsesTransport."""

from collections.abc import Callable
from datetime import datetime as dt
from enum import IntEnum
from typing import Any, Protocol, TypeVar

from .command import Command
from .message import Message
from .packet import Packet

ExceptionT = TypeVar("ExceptionT", bound=type[Exception])
MsgFilterT = Callable[[Message], bool]
MsgHandlerT = Callable[[Message], None]
SerPortName = str


_DEFAULT_TX_COUNT = 1  # number of times to Tx each Command
_DEFAULT_TX_DELAY = 0.02  # gap between re-Tx of same Command

DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30.0  # total waiting for successful send: FIXME


class SendPriority(IntEnum):
    _MAX = -9
    HIGH = -2
    DEFAULT = 0
    LOW = 2
    _MIN = 9


class QosParams:
    """A container for QoS attributes and state."""

    def __init__(
        self,
        *,
        max_retries: int | None = DEFAULT_MAX_RETRIES,
        timeout: float | None = DEFAULT_TIMEOUT,
        wait_for_reply: bool | None = None,
    ) -> None:
        """Create a QosParams instance."""

        self._max_retries = DEFAULT_MAX_RETRIES if max_retries is None else max_retries
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._wait_for_reply = wait_for_reply  # False / None have different meanings

        self._echo_pkt: Packet | None = None
        self._rply_pkt: Packet | None = None

        self._dt_cmd_sent: dt | None = None
        self._dt_echo_rcvd: dt | None = None
        self._dt_rply_rcvd: dt | None = None

    @property
    def max_retries(self) -> int:
        return self._max_retries

    @property
    def timeout(self) -> float:
        return self._timeout

    @property
    def wait_for_reply(self) -> bool | None:
        # None has a special meaning, distinct from False
        return self._wait_for_reply


class SendParams:
    """A container for Send attributes and state."""

    def __init__(
        self,
        *,
        gap_duration: float | None = _DEFAULT_TX_DELAY,
        num_repeats: int | None = _DEFAULT_TX_COUNT,
        priority: SendPriority | None = SendPriority.DEFAULT,
    ) -> None:
        """Create a SendParams instance."""

        self._gap_duration = gap_duration or _DEFAULT_TX_DELAY
        self._num_repeats = num_repeats or _DEFAULT_TX_COUNT
        self._priority = priority or SendPriority.DEFAULT

        self._dt_cmd_arrived: dt | None = None
        self._dt_cmd_queued: dt | None = None
        self._dt_cmd_sent: dt | None = None

    @property
    def gap_duration(self) -> float:
        return self._gap_duration

    @property
    def num_repeats(self) -> int:
        return self._num_repeats

    @property
    def priority(self) -> SendPriority:
        return self._priority


class RamsesTransportT(Protocol):
    """A typing.Protocol (i.e. a structural type) of asyncio.Transport."""

    # _is_reading: bool

    def _dt_now(self) -> dt:
        ...

    def close(self, err: ExceptionT | None = None) -> None:
        ...

    def get_extra_info(self, name, default: Any | None = None) -> Any:
        ...

    def is_closing(self) -> bool:
        ...

    # NOTE this should not be included - maybe is a subclasses
    # @staticmethod
    # def is_hgi80(serial_port: SerPortName) -> None | bool: ...

    def is_reading(self) -> bool:
        ...

    def pause_reading(self) -> None:
        ...

    def resume_reading(self) -> None:
        ...

    def send_frame(self, frame: str) -> None:
        ...

    # NOTE this should not be included - a RamsesProtocol will not invoke it
    # def write(self, data: bytes) -> None: ...


class RamsesProtocolT(Protocol):
    """A typing.Protocol (i.e. a structural type) of asyncio.Protocol."""

    _pause_writing: bool
    _transport: RamsesTransportT

    def add_handler(
        self, /, *, msg_handler: MsgHandlerT, msg_filter: MsgFilterT | None = None
    ) -> Callable[[], None]:
        ...

    def connection_lost(self, err: ExceptionT | None) -> None:
        ...

    def connection_made(self, transport: RamsesTransportT) -> None:
        ...

    def pause_writing(self) -> None:
        ...

    def pkt_received(self, pkt: Packet) -> None:
        ...

    def resume_writing(self) -> None:
        ...

    async def send_cmd(
        self,
        cmd: Command,
        /,
        *,
        gap_duration: float = _DEFAULT_TX_DELAY,
        num_repeats: int = _DEFAULT_TX_COUNT,
        priority: SendPriority = SendPriority.DEFAULT,
        qos: QosParams | None = None,
    ) -> Packet | None:
        ...
