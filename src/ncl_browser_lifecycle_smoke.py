#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""No-booking acceptance test: keep Chrome open until the user closes it.

Never visits NCL, logs in, refreshes, selects a slot, or submits any booking.
"""
import asyncio

from ncl_openlab_autobook import wait_until_browser_manually_closed


async def smoke():
    import zendriver as uc

    browser = await uc.start(headless=False)
    await browser.get("about:blank")
    await asyncio.sleep(0.5)
    if browser.stopped:
        raise RuntimeError("BROWSER_CLOSED_TOO_EARLY")
    targets = await browser._get_targets()
    if not any(getattr(t, "type_", None) == "page" for t in targets):
        raise RuntimeError("BROWSER_PAGE_NOT_DETECTED")
    print("BROWSER_OPEN_PASS：測試瀏覽器已開啟；完全不會預約。", flush=True)
    print("請手動關閉剛開啟的 Chrome 視窗，不要按 Enter。", flush=True)
    await wait_until_browser_manually_closed(browser)
    print("BROWSER_CLOSE_PASS：手動關閉後程式已自動結束。", flush=True)


if __name__ == "__main__":
    asyncio.run(smoke())
