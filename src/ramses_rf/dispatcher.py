#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
"""RAMSES RF - a RAMSES-II protocol decoder & analyser.

Decode/process a message (payload into JSON).
"""

# TODO:
# - fix dispatching - what devices (some are Addr) are sent packets, esp. 1FC9s

from __future__ import annotations

import logging
from datetime import timedelta as td
from typing import TYPE_CHECKING

from ramses_tx import (
    CODES_BY_DEV_SLUG,
    Message,
)
from ramses_tx.ramses import (
    CODES_OF_HEAT_DOMAIN,
    CODES_OF_HEAT_DOMAIN_ONLY,
    CODES_OF_HVAC_DOMAIN_ONLY,
)

from . import exceptions as exc
from .const import (
    DEV_TYPE_MAP,
    DONT_CREATE_ENTITIES,
    DONT_UPDATE_ENTITIES,
    SZ_DEVICES,
    SZ_OFFER,
    SZ_PHASE,
    DevType,
)
from .device import Device, Fakeable

from .const import (  # noqa: F401, isort: skip, pylint: disable=unused-import
    I_,
    RP,
    RQ,
    W_,
    Code,
)

if TYPE_CHECKING:  # mypy TypeVars and similar (e.g. Index, Verb)
    from .const import Index, Verb  # noqa: F401, pylint: disable=unused-import

if TYPE_CHECKING:
    from . import Gateway

_LOGGER = logging.getLogger(__name__)

# all debug flags should be False for published code
DEV_MODE = False  # set True for useful Tracebacks
_DEBUG_FORCE_LOG_MESSAGES = False  # useful for dev/test
STRICT_MODE = False

__all__ = ["detect_array_fragment", "process_msg"]


MSG_FORMAT_18 = "|| {:18s} | {:18s} | {:2s} | {:16s} | {:^4s} || {}"

_TD_SECONDS_003 = td(seconds=3)


def _create_devices_from_addrs(gwy: Gateway, this: Message) -> None:
    """Discover and create any new devices using the packet addresses (not payload)."""

    # prefer Devices but can continue with Addresses if required...
    this.src = gwy.device_by_id.get(this.src.id, this.src)
    this.dst = gwy.device_by_id.get(this.dst.id, this.dst)

    # Devices need to know their controller, ?and their location ('parent' domain)
    # NB: only addrs processed here, packet metadata is processed elsewhere

    # Determinging bindings to a controller:
    #  - configury; As per any schema
    #  - discovery: If in 000C pkt, or pkt *to* device where src is a controller
    #  - eavesdrop: If pkt *from* device where dst is a controller

    # Determinging location in a schema (domain/DHW/zone):
    #  - configury; As per any schema
    #  - discovery: If in 000C pkt - unable for 10: & 00: (TRVs)
    #  - discovery: from packet fingerprint, excl. payloads (only for 10:)
    #  - eavesdrop: from packet fingerprint, incl. payloads

    if not isinstance(this.src, Device):
        this.src = gwy.get_device(this.src.id)  # may: LookupError (don't swallow)
        if this.dst.id == this.src.id:
            this.dst = this.src
            return

    if not gwy.config.enable_eavesdrop:
        return

    if not isinstance(this.dst, Device) and this.src is not gwy.hgi:
        try:
            this.dst = gwy.get_device(this.dst.id)  # may: LookupError (but swallow it)
        except LookupError:
            pass


def _check_msg_addrs(msg: Message) -> None:  # TODO
    """Validate the packet's address set.

    Raise InvalidAddrSetError if the meta data is invalid, otherwise simply return.
    """

    # TODO: needs work: doesn't take into account device's (non-HVAC) class

    if (
        msg.src.id != msg.dst.id
        and msg.src.type == msg.dst.type
        and msg.src.type in DEV_TYPE_MAP.HEAT_DEVICES  # could still be HVAC domain
    ):
        # .I --- 18:013393 18:000730 --:------ 0001 005 00FFFF0200     # invalid
        # .I --- 01:078710 --:------ 01:144246 1F09 003 FF04B5         # invalid
        # .I --- 29:151550 29:237552 --:------ 22F3 007 00023C03040000 # valid? HVAC
        if msg.code in CODES_OF_HEAT_DOMAIN_ONLY:
            raise exc.PacketAddrSetInvalid(
                f"Invalid addr pair: {msg.src!r}/{msg.dst!r}"
            )
        elif msg.code in CODES_OF_HEAT_DOMAIN:
            _LOGGER.warning(
                f"{msg!r} < Invalid addr pair: {msg.src!r}/{msg.dst!r}, is it HVAC?"
            )
        elif msg.code not in CODES_OF_HVAC_DOMAIN_ONLY:
            _LOGGER.info(
                f"{msg!r} < Invalid addr pair: {msg.src!r}/{msg.dst!r}, is it HVAC?"
            )


def _check_src_slug(msg: Message, *, slug: str = None) -> None:
    """Validate the packet's source device class (type) against its verb/code pair.

    Raise InvalidPacketError if the meta data is invalid, otherwise simply return.
    """

    if slug is None:  # slug = best_dev_role(msg.src, msg=msg)._SLUG
        slug = getattr(msg.src, "_SLUG", DevType.DEV)
    if slug in (DevType.HGI, DevType.DEV, DevType.HEA, DevType.HVC):
        return  # TODO: use DEV_TYPE_MAP.PROMOTABLE_SLUGS

    if slug not in CODES_BY_DEV_SLUG:
        if msg.code != Code._10E0 and msg.code not in CODES_OF_HVAC_DOMAIN_ONLY:
            err_msg = f"Unknown src type: {msg.dst}"
            if STRICT_MODE:
                raise exc.PacketInvalid(err_msg)
            (_LOGGER.warning if DEV_MODE else _LOGGER.info)(f"{msg!r} < {err_msg}")
            return
        _LOGGER.warning(f"{msg!r} < Unknown src type: {msg.src}, is it HVAC?")
        return

    #
    #

    if msg.code not in CODES_BY_DEV_SLUG[slug]:  # type: ignore[index]
        if slug != DevType.DEV:
            err_msg = f"Invalid code for {msg.src} to Tx: {msg.code}"
            if STRICT_MODE:
                raise exc.PacketInvalid(err_msg)
            (_LOGGER.warning if DEV_MODE else _LOGGER.info)(f"{msg!r} < {err_msg}")
            return
        if msg.verb in (RQ, W_):
            return
        (_LOGGER.warning if DEV_MODE else _LOGGER.info)(
            f"{msg!r} < Invalid code for {msg.src} to Tx: {msg.code}"
        )
        return

    #
    #

    #
    # (code := CODES_BY_DEV_SLUG[slug][msg.code]) and msg.verb not in code:
    if msg.verb not in CODES_BY_DEV_SLUG[slug][msg.code]:  # type: ignore[index]
        err_msg = f"Invalid verb/code for {msg.src} to Tx: {msg.verb}/{msg.code}"
        if STRICT_MODE:
            raise exc.PacketInvalid(err_msg)
        (_LOGGER.warning if DEV_MODE else _LOGGER.info)(f"{msg!r} < {err_msg}")


def _check_dst_slug(msg: Message, *, slug: str = None) -> None:
    """Validate the packet's destination device class (type) against its verb/code pair.

    Raise InvalidPacketError if the meta data is invalid, otherwise simply return.
    """

    if slug is None:
        slug = getattr(msg.dst, "_SLUG", None)
    if slug in (None, DevType.HGI, DevType.DEV, DevType.HEA, DevType.HVC):
        return  # TODO: use DEV_TYPE_MAP.PROMOTABLE_SLUGS

    if slug not in CODES_BY_DEV_SLUG:
        if msg.code not in CODES_OF_HVAC_DOMAIN_ONLY:
            err_msg = f"Unknown dst type: {msg.dst}"
            if STRICT_MODE:
                raise exc.PacketInvalid(err_msg)
            (_LOGGER.warning if DEV_MODE else _LOGGER.info)(f"{msg!r} < {err_msg}")
            return
        _LOGGER.warning(f"{msg!r} < Unknown dst type: {msg.dst}, is it HVAC?")
        return

    if msg.verb == I_:  # TODO: not common, unless src=dst
        return  # receiving an I isn't currently in the schema & cant yet be tested
    if f"{slug}/{msg.verb}/{msg.code}" in (f"CTL/{RQ}/{Code._3EF1}",):
        return  # HACK: an exception-to-the-rule that need sorting

    if msg.code not in CODES_BY_DEV_SLUG[slug]:  # type: ignore[index]
        if False and slug != DevType.HGI:  # NOTE: not yet needed because of 1st if
            err_msg = f"Invalid code for {msg.dst} to Rx: {msg.code}"
            if STRICT_MODE:
                raise exc.PacketInvalid(err_msg)
            (_LOGGER.warning if DEV_MODE else _LOGGER.info)(f"{msg!r} < {err_msg}")
            return
        if msg.src._SLUG == DevType.HGI or msg.verb == RP:
            # HGI can do what it like
            return
        (_LOGGER.warning if DEV_MODE else _LOGGER.info)(
            f"{msg!r} < Invalid code for {msg.dst} to Rx/Tx: {msg.code}"
        )
        return

    if f"{msg.verb}/{msg.code}" in (f"{W_}/{Code._0001}",):
        return  # HACK: an exception-to-the-rule that need sorting
    if f"{slug}/{msg.verb}/{msg.code}" in (f"{DevType.BDR}/{RQ}/{Code._3EF0}",):
        return  # HACK: an exception-to-the-rule that need sorting

    verb = {RQ: RP, RP: RQ, W_: I_}[msg.verb]
    # (code := CODES_BY_DEV_SLUG[klass][msg.code]) and verb not in code:
    if verb not in CODES_BY_DEV_SLUG[slug][msg.code]:  # type: ignore[index]
        err_msg = f"Invalid verb/code for {msg.dst} to Rx: {msg.verb}/{msg.code}"
        if STRICT_MODE:
            raise exc.PacketInvalid(err_msg)
        (_LOGGER.warning if DEV_MODE else _LOGGER.info)(f"{msg!r} < {err_msg}")


def process_msg(gwy: Gateway, msg: Message) -> None:
    """Decoding the packet payload and route it appropriately."""

    # All methods require msg with a valid payload, except _create_devices_from_addrs(),
    # which requires a valid payload only for 000C.

    def logger_xxxx(msg: Message):
        if _DEBUG_FORCE_LOG_MESSAGES:
            _LOGGER.warning(msg)
        elif msg.src is not gwy.hgi or (msg.code != Code._PUZZ and msg.verb != RQ):
            _LOGGER.info(msg)
        elif msg.src is not gwy.hgi or msg.verb != RQ:
            _LOGGER.info(msg)
        elif _LOGGER.getEffectiveLevel() == logging.DEBUG:
            _LOGGER.info(msg)

    try:  # validate / dispatch the packet
        _check_msg_addrs(msg)  # ?InvalidAddrSetError  TODO: ?useful at all

        # TODO: any use in creating a device only if the payload is valid?
        if gwy.config.reduce_processing >= DONT_CREATE_ENTITIES:
            logger_xxxx(msg)  # return ensures try's else: clause wont be invoked
            return

        try:
            _create_devices_from_addrs(gwy, msg)
        except LookupError as err:
            (_LOGGER.error if DEV_MODE else _LOGGER.warning)(
                "%s < %s(%s)", msg._pkt, err.__class__.__name__, err
            )
            return

        _check_src_slug(msg)  # ? InvalidPacketError
        if msg.dst is not msg.src or msg.verb != I_:
            _check_dst_slug(msg)  # ? InvalidPacketError

        if gwy.config.reduce_processing >= DONT_UPDATE_ENTITIES:
            logger_xxxx(msg)  # return ensures try's else: clause wont be invoked
            return

        # NOTE: here, msgs are routed only to devices: routing to other entities (i.e.
        # systems, zones, circuits) is done by those devices (e.g. UFC to UfhCircuit)

        if isinstance(msg.src, Device):  # , HgiGateway)):  # could use DeviceBase
            gwy._loop.call_soon(msg.src._handle_msg, msg)

        # TODO: should only be for fully-faked dst (as it will pick up via RF if not)
        if msg.dst is not msg.src and isinstance(msg.dst, Fakeable):
            devices = [msg.dst]  # dont: msg.dst._handle_msg(msg)

        elif msg.code == Code._1FC9 and msg.payload[SZ_PHASE] == SZ_OFFER:
            devices = [
                d
                for d in gwy.devices
                if d is not msg.src
                and isinstance(d, Fakeable)
                and d._context.is_binding
            ]

        elif hasattr(msg.src, SZ_DEVICES):
            # .I --- 22:060293 --:------ 22:060293 0008 002 000C
            # .I --- 01:054173 --:------ 01:054173 0008 002 03AA
            # needed for (e.g.) faked relays: each device decides if the pkt is useful
            devices = msg.src.devices  # if d._SLUG = "BDR"

        else:
            devices = []

        for d in devices:  # FIXME: some may be Addresses?
            # if True or getattr(d, "_faked", False):
            gwy._loop.call_soon(d._handle_msg, msg)

    except (AssertionError, exc.RamsesException, NotImplementedError) as err:
        (_LOGGER.error if DEV_MODE else _LOGGER.warning)(
            "%s < %s(%s)", msg._pkt, err.__class__.__name__, err
        )

    except (AttributeError, LookupError, TypeError, ValueError) as err:
        _LOGGER.exception("%s < %s(%s)", msg._pkt, err.__class__.__name__, err)

    else:
        logger_xxxx(msg)


# TODO: this needs cleaning up (e.g. handle intervening packet)
def detect_array_fragment(this: Message, prev: Message) -> dict:  # _PayloadT
    """Return a merged array if this pkt is the latter half of an array."""
    # This will work, even if the 2nd pkt._is_array == False as 1st == True
    # .I --- 01:158182 --:------ 01:158182 000A 048 001201F409C4011101F409C40...
    # .I --- 01:158182 --:------ 01:158182 000A 006 081001F409C4

    return (
        prev
        and prev._has_array
        and this.code in (Code._000A, Code._22C9)  # TODO: not a complete list
        and this.code == prev.code
        and this.verb == prev.verb == I_
        and this.src == prev.src
        and this.dtm < prev.dtm + _TD_SECONDS_003
    )
