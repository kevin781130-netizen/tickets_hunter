#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the offline NCL suite and write an honest JSON + Markdown report.

    python tests/run_ncl_offline_report.py [--out-dir ncl_reports]

Skipped tests are reported as NOT_VERIFIED, never as PASS. Items that can only
be proven on the live site are listed explicitly as NOT_VERIFIED. No browser
session to the real site is opened; only synthetic fixtures run in Chromium.
"""
import argparse
import contextlib
import json
import os
import platform
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / "src"), str(HERE)]

import ncl_browser  # noqa: E402
from ncl_openlab_rooms import get_registry, support_matrix  # noqa: E402

TAIPEI = timezone(timedelta(hours=8))

# Facts that offline tests cannot establish. Keep this list honest and current.
LIVE_ONLY = (
    ("music 音樂創作室", "正向可預約 DOM、最終「預約」按鈕與成功頁尚無實機證據"),
    ("同一天連續兩筆預約 (--reserve-two)", "僅離線模擬，尚無兩筆實際成交"),
    ("午夜 T-10 / T=0 刷新與 3 秒重試", "離線測試通過；尚無自然午夜實機正向證據"),
    ("新版 --dry-run / --screenshot / --report-dir 在真實 zendriver 上", "只以假瀏覽器驗證；save_screenshot 未對真站執行"),
    ("ncl_openlab_inventory.py 在已登入的真實網站上", "只以合成頁面驗證；尚未實際盤點任何新房型"),
    ("P03 以外的房號 (P01、P02、P04...) 與其他空間類別", "未盤點、未設定，因此視為不支援"),
    ("網站目前 DOM 是否仍與記錄一致", "fixture 為合成頁面，不能取代實機檢查"),
)


class Recorder(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.rows = []

    def _add(self, test, status, detail=""):
        self.rows.append({"test": test.id(), "status": status, "detail": detail[:300]})

    def addSuccess(self, test):
        super().addSuccess(test)
        self._add(test, "PASS")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._add(test, "FAIL", str(err[1]))

    def addError(self, test, err):
        super().addError(test, err)
        self._add(test, "ERROR", str(err[1]))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._add(test, "NOT_VERIFIED", reason)


def run():
    suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_ncl_openlab_*.py",
                                                top_level_dir=str(HERE))
    runner = unittest.TextTestRunner(resultclass=Recorder, verbosity=0,
                                     stream=open(os.devnull, "w"))
    started = time.time()
    with contextlib.redirect_stdout(open(os.devnull, "w")):  # silence engine prints
        result = runner.run(suite)
    return result, time.time() - started


def build(result, seconds):
    counts = {}
    for row in result.rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    modules = {}
    for row in result.rows:
        module = row["test"].split(".")[0]
        entry = modules.setdefault(module, {})
        entry[row["status"]] = entry.get(row["status"], 0) + 1
    registry = get_registry()
    flows = {name: [p.key for p in members] for name, members in registry.by_flow().items()}
    return {
        "generated_taipei": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "browser_fixtures_available": ncl_browser.available(),
        "seconds": round(seconds, 1),
        "counts": counts,
        "overall": ("PASS" if not counts.get("FAIL") and not counts.get("ERROR")
                    and not counts.get("NOT_VERIFIED") else
                    "FAIL" if counts.get("FAIL") or counts.get("ERROR") else "PASS_WITH_NOT_VERIFIED"),
        "modules": modules,
        "flows": flows,
        "support_matrix": support_matrix(registry),
        "live_only_not_verified": [{"item": a, "reason": b} for a, b in LIVE_ONLY],
        "failures": [r for r in result.rows if r["status"] in ("FAIL", "ERROR")],
        "skipped": [r for r in result.rows if r["status"] == "NOT_VERIFIED"],
    }


def markdown(report):
    lines = ["# NCL OPEN LAB 離線驗證報告", "",
             f"- 產生時間（台北）：{report['generated_taipei']}",
             f"- 結果：**{report['overall']}**　{report['counts']}",
             f"- 瀏覽器 fixture 可用：{report['browser_fixtures_available']}", "",
             "## 房型支援矩陣", "",
             "| 房型 | 流程 | 時段數 | 離線 | 實機 | 狀態 |", "|---|---|---|---|---|---|"]
    for row in report["support_matrix"]:
        lines.append(f"| {row['label']} (`{row['room']}`) | {row['flow']} | {row['slots']} | "
                     f"{row['offline']} | {row['live']} | {row['status']} |")
    lines += ["", "## 流程分組（同流程共用引擎與完整走查測試）", ""]
    lines += [f"- `{flow}`：{', '.join(rooms)}" for flow, rooms in report["flows"].items()]
    lines += ["", "## 尚未實機驗證（NOT_VERIFIED）", ""]
    lines += [f"- **{i['item']}**：{i['reason']}" for i in report["live_only_not_verified"]]
    if report["skipped"]:
        lines += ["", "## 被略過的測試（視為 NOT_VERIFIED）", ""]
        lines += [f"- `{r['test']}`：{r['detail']}" for r in report["skipped"]]
    if report["failures"]:
        lines += ["", "## 失敗", ""]
        lines += [f"- `{r['test']}`：{r['detail']}" for r in report["failures"]]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="ncl_reports")
    args = parser.parse_args()
    result, seconds = run()
    report = build(result, seconds)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "offline_test_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "offline_test_report.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return 0 if report["overall"] != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
