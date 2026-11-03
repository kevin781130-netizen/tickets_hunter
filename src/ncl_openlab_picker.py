#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows Tkinter launcher for the NCL booking workflow.

Manual browser login remains mandatory. No network calls or credentials are
handled by this window. Booking starts only after an explicit confirmation.
"""
import calendar
import os
from datetime import date, datetime, timedelta
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from ncl_openlab_picker_model import (
    ROOM_CHOICES, TAIPEI, available_slots, build_booking_args, release_datetime,
)

BURGUNDY = "#731d20"
GOLD = "#a88057"
PAPER = "#faf8f5"
DARK = "#2d2926"
BORDER = "#dad0c9"


def month_shift(year, month, offset):
    index = year * 12 + month - 1 + offset
    return index // 12, index % 12 + 1


class BookingPicker(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("國圖 OPEN LAB｜預約日期與時段")
        self.geometry("820x720")
        self.minsize(730, 660)
        self.configure(bg=PAPER)

        now = datetime.now(TAIPEI)
        self.selected_date = now.date() + timedelta(days=8)
        self.view_year = self.selected_date.year
        self.view_month = self.selected_date.month
        self.room = tk.StringVar(value="music")
        self.immediate = tk.BooleanVar(value=False)
        self.authorize_submit = tk.BooleanVar(value=False)
        self.accept_terms = tk.BooleanVar(value=False)
        self.slots = []  # Selection order is also booking order.
        self._build()
        self._render_calendar()
        self._render_slots()
        self._refresh_summary()

    def _build(self):
        main = tk.Frame(self, bg=PAPER, padx=25, pady=20)
        main.pack(fill="both", expand=True)
        tk.Label(main, text="國圖 OPEN LAB 預約選擇器", bg=PAPER, fg=BURGUNDY,
                 font=("Microsoft JhengHei UI", 19, "bold")).pack(anchor="w")
        tk.Label(main, text="選日期 → 選房間 → 勾選 1–2 個時段 → 確認送出",
                 bg=PAPER, fg=DARK,
                 font=("Microsoft JhengHei UI", 10)).pack(anchor="w", pady=(3, 13))

        room_row = tk.LabelFrame(main, text=" 1｜選擇空間 ", bg=PAPER, fg=DARK,
                                 padx=12, pady=8)
        room_row.pack(fill="x", pady=(0, 11))
        for mode, title in ROOM_CHOICES.items():
            ttk.Radiobutton(room_row, text=title, value=mode,
                            variable=self.room, command=self._room_changed).pack(
                                side="left", padx=(5, 26))

        # Calendar and slots side-by-side keep all controls visible on 720p.
        choices_row = tk.Frame(main, bg=PAPER)
        choices_row.pack(fill="x", pady=(0, 11))
        choices_row.columnconfigure(0, weight=1, uniform="choice")
        choices_row.columnconfigure(1, weight=1, uniform="choice")
        cal_frame = tk.LabelFrame(choices_row, text=" 2｜月曆選擇預約日期 ", bg=PAPER,
                                  fg=DARK, padx=8, pady=8)
        cal_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        navigation = tk.Frame(cal_frame, bg=PAPER)
        navigation.pack(fill="x", pady=(0, 8))
        ttk.Button(navigation, text="◀ 上個月", command=lambda: self._change_month(-1)).pack(side="left")
        self.month_caption = tk.Label(navigation, bg=PAPER, fg=BURGUNDY,
                                       font=("Microsoft JhengHei UI", 13, "bold"))
        self.month_caption.pack(side="left", expand=True)
        ttk.Button(navigation, text="下個月 ▶", command=lambda: self._change_month(1)).pack(side="right")
        self.days_frame = tk.Frame(cal_frame, bg=PAPER)
        self.days_frame.pack(fill="x")
        for column in range(7):
            self.days_frame.columnconfigure(column, weight=1, uniform="day")
        self.date_caption = tk.Label(cal_frame, bg=PAPER, fg=DARK,
                                     font=("Microsoft JhengHei UI", 10))
        self.date_caption.pack(anchor="w", pady=(7, 0))

        slot_area = tk.LabelFrame(choices_row, text=" 3｜時段（可複選兩個） ",
                                  bg=PAPER, fg=DARK, padx=8, pady=8)
        slot_area.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.slot_frame = tk.Frame(slot_area, bg=PAPER)
        self.slot_frame.pack(fill="x")
        self.slot_note = tk.Label(slot_area, bg=PAPER, fg=DARK, anchor="w",
                                  font=("Microsoft JhengHei UI", 10))
        self.slot_note.pack(fill="x", pady=(7, 0))
        ttk.Button(slot_area, text="清除時段", command=self._clear_slots).pack(anchor="e")

        settings = tk.LabelFrame(main, text=" 4｜執行選項 ", bg=PAPER, fg=DARK,
                                 padx=12, pady=8)
        settings.pack(fill="x", pady=(0, 11))
        ttk.Checkbutton(settings, text="立即測試（不等午夜；預設關閉）",
                        variable=self.immediate, command=self._refresh_summary).pack(anchor="w")
        ttk.Checkbutton(settings, text="我已閱讀網站規範，並允許程式在網站顯示同意視窗時按「同意」",
                        variable=self.accept_terms).pack(anchor="w", pady=(2, 0))
        ttk.Checkbutton(settings, text="我明確授權正式送出預約（必須勾選）",
                        variable=self.authorize_submit).pack(anchor="w", pady=(2, 0))

        self.summary = tk.Label(main, bg=PAPER, fg=DARK, justify="left",
                                anchor="w", wraplength=685,
                                font=("Microsoft JhengHei UI", 10))
        self.summary.pack(fill="x", pady=(0, 9))
        tk.Button(main, text="確認設定並開啟預約瀏覽器", bg=BURGUNDY, fg="white",
                  activebackground=GOLD, activeforeground="white",
                  padx=18, pady=10, font=("Microsoft JhengHei UI", 12, "bold"),
                  command=self._launch).pack(fill="x")
        tk.Label(main, bg=PAPER, fg="#756f6a",
                 text="瀏覽器需手動登入。選兩個時段會送出兩次預約；第一筆未確認成功就停止。",
                 wraplength=685).pack(anchor="w", pady=(8, 0))

    def _change_month(self, offset):
        self.view_year, self.view_month = month_shift(
            self.view_year, self.view_month, offset)
        self._render_calendar()

    def _render_calendar(self):
        for widget in self.days_frame.winfo_children():
            widget.destroy()
        self.month_caption.config(text=f"{self.view_year} 年 {self.view_month:02d} 月")
        for col, label in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            tk.Label(self.days_frame, text=label, bg=PAPER,
                     fg=DARK).grid(row=0, column=col, pady=2)
        today = datetime.now(TAIPEI).date()
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(
            self.view_year, self.view_month)
        for row, week in enumerate(weeks, start=1):
            for col, day_number in enumerate(week):
                if not day_number:
                    continue
                chosen = date(self.view_year, self.view_month, day_number)
                selected = chosen == self.selected_date
                # Openings are seven days ahead. The upcoming midnight release
                # can be for today+8. Allow picking future dates up to 31 days.
                enabled = today <= chosen <= today + timedelta(days=31)
                tk.Button(
                    self.days_frame, text=str(day_number), width=5,
                    bg=BURGUNDY if selected else PAPER,
                    fg="white" if selected else (DARK if enabled else "#aaa5a2"),
                    relief="sunken" if selected else "flat",
                    state="normal" if enabled else "disabled",
                    command=lambda chosen=chosen: self._pick_date(chosen)
                ).grid(row=row, column=col, padx=1, pady=1, sticky="ew")
        self.date_caption.config(text=f"已選：{self.selected_date.isoformat()}（台北時間）")

    def _pick_date(self, selected):
        self.selected_date = selected
        self._render_calendar()
        self._refresh_summary()

    def _room_changed(self):
        self.slots.clear()
        self._render_slots()
        self._refresh_summary()

    def _clear_slots(self):
        self.slots.clear()
        self._render_slots()
        self._refresh_summary()

    def _toggle_slot(self, value):
        if value in self.slots:
            self.slots.remove(value)
        elif len(self.slots) >= 2:
            messagebox.showwarning("最多兩段", "每天最多選兩個時段。先取消一個時段再選。")
            return
        else:
            self.slots.append(value)
        self._render_slots()
        self._refresh_summary()

    def _render_slots(self):
        for widget in self.slot_frame.winfo_children():
            widget.destroy()
        choices = available_slots(self.room.get())
        columns = 2 if self.room.get() == "p03" else 3
        for col in range(columns):
            self.slot_frame.columnconfigure(col, weight=1, uniform="slot")
        for index, slot in enumerate(choices):
            priority = (self.slots.index(slot) + 1) if slot in self.slots else None
            button = tk.Button(
                self.slot_frame, text=f"{'✓ ' + str(priority) + '｜' if priority else '□ '}{slot}",
                bg=BURGUNDY if priority else "#f2edeb",
                fg="white" if priority else DARK,
                relief="sunken" if priority else "ridge",
                command=lambda slot=slot: self._toggle_slot(slot),
                padx=9, pady=8,
            )
            button.grid(row=index // columns, column=index % columns,
                        padx=3, pady=3, sticky="ew")
        self.slot_note.config(
            text=("選擇一個＝預約一筆；選擇兩個＝依順序預約兩筆。"
                  if not self.slots else
                  "預約順序：" + " → ".join(self.slots))
        )

    def _refresh_summary(self):
        release = release_datetime(self.selected_date)
        plan = "立即執行一次（無重試）" if self.immediate.get() else (
            f"放位日 {release:%Y/%m/%d} 00:00（台北）；"
            "23:59:50 預刷新；未開放每 3 秒重試（最多 90 秒）"
        )
        self.summary.config(
            text=f"日期：{self.selected_date.isoformat()}    空間：{ROOM_CHOICES[self.room.get()]}\n"
                 f"時段：{' → '.join(self.slots) if self.slots else '尚未選擇'}\n"
                 f"模式：{plan}"
        )

    def _launch(self):
        try:
            argv = build_booking_args(
                day=self.selected_date, room=self.room.get(), slots=self.slots,
                immediate=self.immediate.get(),
                auto_submit=self.authorize_submit.get(),
                accept_terms=self.accept_terms.get(),
            )
        except ValueError as exc:
            messagebox.showwarning("請確認設定", str(exc))
            return

        if not self.immediate.get():
            remaining = (release_datetime(self.selected_date) -
                         datetime.now(TAIPEI)).total_seconds()
            if not 0 <= remaining <= 900:
                messagebox.showwarning(
                    "午夜放位時間",
                    "正式午夜模式請在放位前 15 分鐘內啟動。\n"
                    "若該日期已開放，請勾選「立即測試」。"
                )
                return

        count = len(self.slots)
        explanation = (f"將正式預約 {count} 個時段：\n"
                       f"{self.selected_date.isoformat()}｜{ROOM_CHOICES[self.room.get()]}\n"
                       + " → ".join(self.slots) + "\n\n"
                       + ("立即開始選位" if self.immediate.get() else
                          f"預定放位：{release_datetime(self.selected_date):%Y/%m/%d 00:00}（台北）")
                       + "\n先登入國圖並停在日期頁，回終端按 Enter。\n"
                       "送出後不會重複送出同一筆預約。確定啟動？")
        if not messagebox.askyesno("正式預約確認", explanation, icon="warning"):
            return

        entry = Path(__file__).resolve().with_name("ncl_openlab_autobook.py")
        command = [sys.executable, str(entry), *argv]
        try:
            if os.name == "nt":
                subprocess.Popen(command, cwd=str(entry.parent.parent),
                                 creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                raise OSError("此啟動器目前僅支援 Windows 新主控台")
        except OSError as exc:
            messagebox.showerror("無法啟動", str(exc))
            return
        messagebox.showinfo("已啟動", "已開啟獨立終端執行預約。\n請登入國圖，再回終端按 Enter。")


def main():
    BookingPicker().mainloop()


if __name__ == "__main__":
    main()
