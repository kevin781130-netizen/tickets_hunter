# -*- coding: utf-8 -*-
"""Passive browser lifecycle helper, independent of any booking website."""
import asyncio


async def wait_until_browser_manually_closed(browser, *, interval=1.0):
    """Preserve visible results; never close or navigate the browser.

    Checks only the local browser's DevTools target list. No network calls to a
    booking site, retries, clicks, or automatic browser.stop() calls are made.
    """
    no_page_checks = 0
    while True:
        if browser.stopped:
            return
        try:
            targets = await browser._get_targets()
            if any(getattr(target, "type_", None) == "page"
                   for target in targets):
                no_page_checks = 0
            else:
                no_page_checks += 1
                if no_page_checks >= 3:
                    return
        except Exception:
            # DevTools may disconnect when Chrome exits; do not swallow
            # unrelated failures by exiting prematurely.
            connection = getattr(browser, "connection", None)
            if browser.stopped or (
                    connection is not None and connection.closed):
                return
        await asyncio.sleep(interval)
