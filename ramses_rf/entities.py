#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
"""RAMSES RF - a RAMSES-II protocol decoder & analyser."""

import logging
from typing import Any, List, Optional

from .command import Command
from .const import DISCOVER_ALL

from .const import I_, RP, RQ, W_, __dev_mode__  # noqa: F401, isort: skip

DEFAULT_BDR_ID = "13:000730"
DEFAULT_EXT_ID = "17:000730"
DEFAULT_THM_ID = "03:000730"

DEV_MODE = __dev_mode__ and False

_LOGGER = logging.getLogger(__name__)
if DEV_MODE:
    _LOGGER.setLevel(logging.DEBUG)


class Entity:
    """The Device/Zone base class."""

    def __init__(self, gwy) -> None:
        self._loop = gwy._loop

        self._gwy = gwy
        self.id = None

        self._msgs = {}
        self._msgz = {}

    def _discover(self, discover_flag=DISCOVER_ALL) -> None:
        pass

    def _get_msg_value(self, code, key=None) -> dict:
        if self._msgs.get(code):
            if isinstance(self._msgs[code].payload, list):
                return self._msgs[code].payload

            if key is not None:
                return self._msgs[code].payload.get(key)

            result = self._msgs[code].payload
            return {
                k: v
                for k, v in result.items()
                if k[:1] != "_" and k not in ("domain_id", "zone_idx")
            }

    def _handle_msg(self, msg) -> None:  # TODO: beware, this is a mess
        if msg.code not in self._msgz:
            self._msgz[msg.code] = {msg.verb: {msg._pkt._ctx: msg}}
        elif msg.verb not in self._msgz[msg.code]:
            self._msgz[msg.code][msg.verb] = {msg._pkt._ctx: msg}
        else:
            self._msgz[msg.code][msg.verb][msg._pkt._ctx] = msg

        # TODO:
        # if msg.verb == RP and msg._pkt._idx in self._msgz[msg.code].get(I_, []):
        #     assert msg.raw_payload == self._msgz[msg.code][I_][msg._pkt._idx].raw_payload, (
        #         f"\r\n{msg._pkt} ({msg._pkt._idx}),"
        #         f"\r\n{self._msgz[msg.code][I_][msg._pkt._idx]._pkt} ({msg._pkt._idx})"
        #     )
        #     del self._msgz[msg.code][I_][msg._pkt._idx]

        # elif msg.verb == I_ and msg._pkt._idx in self._msgz[msg.code].get(RP, []):
        #     assert msg.raw_payload == self._msgz[msg.code][RP][msg._pkt._idx].raw_payload, (
        #         f"\r\n{msg._pkt} ({msg._pkt._idx}),"
        #         f"\r\n{self._msgz[msg.code][RP][msg._pkt._idx]._pkt} ({msg._pkt._idx})"
        #     )
        #     del self._msgz[msg.code][RP][msg._pkt._idx]

        if msg.verb in (I_, RP):  # TODO: deprecate
            self._msgs[msg.code] = msg

    @property
    def _msg_db(self) -> List:  # a flattened version of _msgz[code][verb][indx]
        """Return a flattened version of _msgz[code][verb][indx]."""
        return [m for c in self._msgz.values() for v in c.values() for m in v.values()]

    # @property
    # def _pkt_db(self) -> Dict:
    #     """Return a flattened version of ..."""
    #     return {msg.dtm: msg._pkt for msg in self._msgs_db}

    def _send_cmd(self, code, dest_id, payload, verb=RQ, **kwargs) -> None:
        self._msgs.pop(code, None)  # remove the old one, so we can tell if RP'd rcvd
        self._gwy.send_cmd(Command(verb, code, payload, dest_id, **kwargs))

    def _msg_payload(self, msg, key=None) -> Optional[Any]:
        if msg and not msg._expired:
            if key:
                return msg.payload.get(key)
            return {k: v for k, v in msg.payload.items() if k[:1] != "_"}

    def _msg_expired(self, msg_name: str) -> Optional[bool]:
        attr = f"_{msg_name}"
        if not hasattr(self, attr):
            _LOGGER.error("%s: is not tracking %s msgs", self, msg_name)
            return

        msg = getattr(self, f"_{msg_name}")
        if not msg:
            _LOGGER.warning("%s: has no valid %s msg", self, msg_name)
        # elif msg_name != RAMSES_CODES[msg.code][NAME]:
        #     _LOGGER.warning(
        #         "%s: Message(%s) doesn't match name: %s",
        #         self,
        #         msg._pkt._hdr,
        #         msg_name,
        #     )
        #     assert False, msg.code
        elif msg._expired:
            _LOGGER.warning(
                "%s: Message(%s) has expired (%s)", self, msg._pkt._hdr, attr
            )
        else:
            return True

    @property
    def _codes(self) -> dict:
        return {
            "codes": sorted([k for k, v in self._msgs.items()]),
        }

    @property
    def controller(self):  # -> Optional[Controller]:
        """Return the entity's controller, if known."""

        return self._ctl  # TODO: if the controller is not known, try to find it?


def expired(msg) -> None:

    has_expired = msg._has_expired

    if has_expired < msg.HAS_EXPIRED:
        return has_expired

    entities = [msg.src]
    if "domain_id" in msg.payload:
        entities.append(msg._ctl)
    if "dhw_id" in msg.payload:
        entities.append(msg._ctl.get_zone_by_id["HW"])
    if "zone_idx" in msg.payload:
        entities.append(msg._ctl.get_zone_by_id[msg.payload["zone_idx"]])

    for obj in entities:
        if msg.code in obj._msgs and msg.verb == obj._msgs[msg.code].verb:
            del obj._msgs[msg.code]
        try:
            del obj._msgz[msg.code][msg.verb][msg._pkt._ctx]
            if obj._msgz[msg.code][msg.verb] == {}:
                del obj._msgz[msg.code][msg.verb]
            if obj._msgz[msg.code] == {}:
                del obj._msgz[msg.code]
        except KeyError:
            pass

        msg = None
        return has_expired