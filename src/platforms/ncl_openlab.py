# -*- coding: utf-8 -*-
"""NCL OPEN LAB adapter for Tickets Hunter (passive router registration).

The existing NCL one-shot booking flow remains the production entry point.
The URL router recognizes the exact official NCL host and calls the passive
nodriver_ncl_main only. It must NEVER call nodriver_ncl_booking implicitly.
Only an explicit call to nodriver_ncl_booking with auto_submit=True can
reach a final reservation; nodriver_ncl_main is strictly passive.
"""
from datetime import date, datetime
from urllib.parse import urlsplit

from ncl_openlab_guard import NCL_HOST, VALID_SLOTS
import ncl_openlab_autobook as ncl


__all__ = ["nodriver_ncl_main", "nodriver_ncl_booking"]


async def nodriver_ncl_main(tab, url, config_dict):
    """Passive router-compatible entry point; does not navigate or book.

    Automatic router dispatch is always passive; one-shot submission requires
    a separate, explicit caller and cannot be authorized by a URL alone.
    """
    if urlsplit(url).hostname != NCL_HOST:
        return "NCL_HOST_NOT_MATCHED"
    # Even if a future settings page exposes an enable switch, simply
    # observing a URL must never authorize a reservation.
    return "NCL_MANUAL_BOOKING_ONLY"


async def nodriver_ncl_booking(tab, day, slot, *,
                              mode="music", auto_submit=False,
                              accept_terms=False):
    """One explicitly authorized booking through the existing NCL stages.

    One invocation handles only one room and time block. A two-slot workflow
    remains owned by the tested NCL controller; never repeat an uncertain
    final submission from this adapter.
    """
    if not auto_submit:
        return "NCL_ADAPTER_SUBMIT_NOT_AUTHORIZED"
    if not isinstance(day, date) or isinstance(day, datetime):
        return "NCL_ADAPTER_INVALID_DATE"
    if mode not in ncl.ROOM_MODES:
        return "NCL_ADAPTER_INVALID_ROOM"
    allowed = VALID_SLOTS if mode == "music" else ncl.P03_SLOTS
    if slot not in allowed:
        return "NCL_ADAPTER_INVALID_SLOT"
    if not await ncl.at_official_host(tab):
        return "NCL_ADAPTER_WRONG_HOST"
    entry = await ncl.ensure_date_grid(
        tab, mode=mode, accept_terms=accept_terms)
    if entry != "GRID_READY":
        return "NCL_ADAPTER_ENTRY_BLOCKED_" + str(entry)
    return await ncl.book_one_target(
        tab, day, (slot,), mode=mode, auto_submit=True)
