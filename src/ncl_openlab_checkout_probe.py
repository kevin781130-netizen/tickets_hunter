#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inspect the final NCL reservation page, without taking any booking action."""
import argparse
import asyncio
import json
from urllib.parse import urlsplit

from ncl_openlab_probe import NCL_URL, NCL_HOST, SLOTS, next_open_date
from ncl_openlab_checkout import checkout_script, assess_checkout


async def inspect_checkout(day, slot):
    import zendriver as uc

    browser = await uc.start(headless=False)
    try:
        tab = await browser.get(NCL_URL)
        await asyncio.to_thread(
            input,
            "請手動登入、選日期與空間、選時段並按「下一步」，"
            "停在最後「預約」確認頁（不要按預約）；返回按 Enter 唯讀檢查：",
        )
        current_url = await tab.evaluate("location.href")
        if urlsplit(current_url).hostname != NCL_HOST:
            raise RuntimeError("Not on the official NCL reservation host")
        raw = await tab.evaluate(checkout_script(day, slot))
        result = assess_checkout(raw)
        print(json.dumps({"checkout_readonly_assessment": result},
                         ensure_ascii=False, indent=2))
        print("僅顯示固定標籤及選取數量；不能確認空位或預約成功。")
        print("唯讀檢查完成：沒有點擊、送出、儲存個資、刷新或輪詢。")
    finally:
        await browser.stop()


def main():
    parser = argparse.ArgumentParser(description="國圖預約最後步驟：唯讀檢查")
    parser.add_argument("--date", type=__import__("datetime").date.fromisoformat,
                        default=next_open_date(), help="目標日期 YYYY-MM-DD")
    parser.add_argument("--slot", choices=SLOTS, required=True,
                        help="音樂創作室三小時目標時段")
    args = parser.parse_args()
    print("唯讀模式：最後「預約」按鈕需使用者自行操作，本工具絕不點擊。")
    asyncio.run(inspect_checkout(args.date, args.slot))


if __name__ == "__main__":
    main()
