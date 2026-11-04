#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows/macOS Tkinter launcher for the NCL booking workflow.

Manual browser login remains mandatory. No network calls or credentials are
handled by this window. Booking starts only after an explicit confirmation.
"""
import calendar
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from ncl_openlab_launcher import launch_booking_command
from ncl_openlab_room_catalog import ROOM_GROUPS, room_status, room_notice
from ncl_openlab_picker_model import (
    ROOM_CHOICES, TAIPEI, available_slots, build_booking_args,
    console_python, release_datetime,
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
        self.geometry("900x760")
        self.minsize(720, 510)
        self.configure(bg=PAPER)

        now = datetime.now(TAIPEI)
        self.selected_date = now.date() + timedelta(days=8)
        self.view_year = self.selected_date.year
        self.view_month = self.selected_date.month
        self.room = tk.StringVar(value="music")
        self.immediate = tk.BooleanVar(value=False)
        self.authorize_submit = tk.BooleanVar(value=False)
        self.fallback_any_slot = tk.BooleanVar(value=True)
        self.accept_terms = tk.BooleanVar(value=False)
        self.slots = []  # Selection order is also booking order.
        self._build()
        self._render_calendar()
        self._render_slots()
        self._refresh_summary()

    def _build(self):
        # The bottom controls remain visible even on 125–200% Windows display
        # scaling and low-height screens. Only the upper configuration scrolls.
        footer = tk.Frame(self, bg=PAPER, padx=18, pady=9)
        footer.pack(side="bottom", fill="x")
        self.summary = tk.Label(footer, bg=PAPER, fg=DARK, justify="left",
                                anchor="w", font=("Microsoft JhengHei UI", 10))
        self.summary.pack(fill="x", pady=(0, 5))
        tk.Button(footer, text="確認設定並開啟預約瀏覽器", bg=BURGUNDY, fg="white",
                  activebackground=GOLD, activeforeground="white",
                  pady=9, font=("Microsoft JhengHei UI", 12, "bold"),
                  command=self._launch).pack(fill="x")
        tk.Label(footer, bg=PAPER, fg="#756f6a", anchor="w",
                 text="勾選兩段＝預約兩筆；第一筆未確認成功就停止。").pack(
                     anchor="w", pady=(4, 0))

        viewport = tk.Frame(self, bg=PAPER)
        viewport.pack(side="top", fill="both", expand=True)
        self.content_canvas = tk.Canvas(
            viewport, bg=PAPER, highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(
            viewport, orient="vertical", command=self.content_canvas.yview)
        self.content_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.content_canvas.pack(side="left", fill="both", expand=True)

        main = tk.Frame(self.content_canvas, bg=PAPER, padx=18, pady=12)
        window = self.content_canvas.create_window(
            (0, 0), window=main, anchor="nw")
        main.bind("<Configure>", lambda event:
                  self.content_canvas.configure(
                      scrollregion=self.content_canvas.bbox("all")))
        self.content_canvas.bind("<Configure>", lambda event:
                  self.content_canvas.itemconfigure(window, width=event.width))
        self.content_canvas.bind_all("<MouseWheel>", self._scroll_wheel)

        tk.Label(main, text="國圖 OPEN LAB 預約選擇器", bg=PAPER, fg=BURGUNDY,
                 font=("Microsoft JhengHei UI", 19, "bold")).pack(anchor="w")
        tk.Label(main, text="選日期 → 選房間 → 勾選 1–2 個時段 → 確認送出",
                 bg=PAPER, fg=DARK,
                 font=("Microsoft JhengHei UI", 10)).pack(anchor="w", pady=(3, 13))

        room_row = tk.LabelFrame(main, text=" 1｜選擇空間（全部 14 類） ", bg=PAPER,
                                 fg=DARK, padx=12, pady=8)
        room_row.pack(fill="x", pady=(0, 11))
        # Two-column layout prevents the 14 entries from overflowing a laptop.
        # Online-unverified rooms may be inspected, but cannot launch booking.
        # On-site-only spaces are informational and disabled.
        for group_title, modes in ROOM_GROUPS:
            group = tk.Frame(room_row, bg=PAPER)
            group.pack(fill="x", anchor="w", pady=(1, 6))
            tk.Label(group, text=group_title, bg=PAPER, fg=GOLD,
                     font=("Microsoft JhengHei UI", 10, "bold")).grid(
                         row=0, column=0, columnspan=2, sticky="w", pady=(1, 2))
            for index, mode in enumerate(modes):
                choice = ttk.Radiobutton(
                    group, text=ROOM_CHOICES[mode], value=mode,
                    variable=self.room, command=self._room_changed)
                if room_status(mode) == "onsite_only":
                    choice.configure(state="disabled")
                choice.grid(row=index // 2 + 1, column=index % 2,
                            sticky="w", padx=(5, 20), pady=2)
        self.room_note = tk.Label(room_row, bg=PAPER, fg=DARK, anchor="w",
                                  justify="left", wraplength=760,
                                  font=("Microsoft JhengHei UI", 10))
        self.room_note.pack(fill="x", pady=(6, 0))
        ttk.Button(room_row, text="讀取所選空間的實際網頁規則（唯讀、不預約）",
                   command=self._inspect_room).pack(anchor="w", pady=(7, 1))

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
        ttk.Checkbutton(settings, text="立即正式預約（不等午夜；會真的送出；預設關閉）",
                        variable=self.immediate, command=self._refresh_summary).pack(anchor="w")
        ttk.Checkbutton(settings, text="我已閱讀網站規範，並允許程式在網站顯示同意視窗時按「同意」",
                        variable=self.accept_terms).pack(anchor="w", pady=(2, 0))
        ttk.Checkbutton(settings,
                        text="偏好時段已滿時，自動改選同日同房間的其他時段（預設開啟）",
                        variable=self.fallback_any_slot,
                        command=self._refresh_summary).pack(anchor="w", pady=(2, 0))
        ttk.Checkbutton(settings, text="我明確授權正式送出預約（必須勾選）",
                        variable=self.authorize_submit).pack(anchor="w", pady=(2, 0))

    def _scroll_wheel(self, event):
        if event.delta:
            self.content_canvas.yview_scroll(
                -1 if event.delta > 0 else 1, "units")

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
        room = self.room.get()
        choices = available_slots(room)
        columns = 2 if room == "p03" else 3
        for col in range(columns):
            self.slot_frame.columnconfigure(col, weight=1, uniform="slot")
        for index, slot in enumerate(choices):
            priority = (self.slots.index(slot) + 1) if slot in self.slots else None
            button = tk.Button(
                self.slot_frame, text=f"{'第' + str(priority) + '筆 ✓ ' if priority else '選取  '}{slot}",
                bg=BURGUNDY if priority else "#f2edeb",
                fg="white" if priority else DARK,
                relief="sunken" if priority else "ridge",
                command=lambda slot=slot: self._toggle_slot(slot),
                padx=9, pady=8,
            )
            button.grid(row=index // columns, column=index % columns,
                        padx=3, pady=3, sticky="ew")
        self.slot_note.config(
            text=(("此空間時段尚待驗證，暫不開放程式選取。" if not choices else
                  "選擇一個＝預約一筆；選擇兩個＝依順序預約兩筆。")
                  if not self.slots else
                  "預約順序：" + " → ".join(self.slots))
        )
        self.room_note.config(text=room_notice(room))

    def _refresh_summary(self):
        status = room_status(self.room.get())
        if status != "verified":
            plan = ("現場限定，不可線上預約" if status == "onsite_only"
                    else "待驗證空間：僅列入清單，禁止自動送出")
        else:
            release = release_datetime(self.selected_date)
            plan = ("立即正式預約（真實送出；無午夜重試）"
                    if self.immediate.get() else
                    f"放位日 {release:%Y/%m/%d} 00:00（台北）；"
                    "23:59:50 預刷新；未開放每 3 秒重試（最多 90 秒）")
        self.summary.config(
            text=f"日期：{self.selected_date.isoformat()}    空間：{ROOM_CHOICES[self.room.get()]}\n"
                 f"時段：{' → '.join(self.slots) if self.slots else '尚未選擇'}\n"
                 f"模式：{plan}\n"
                 f"自動改選：{'開啟（同日同房間）' if self.fallback_any_slot.get() and status == 'verified' else '停用'}"
        )

    def _inspect_room(self):
        mode = self.room.get()
        if room_status(mode) != "needs_live_dom":
            messagebox.showinfo(
                "唯讀診斷", "此空間已完成選取驗證，或官網僅開放現場借用。")
            return
        entry = Path(__file__).resolve().with_name("ncl_openlab_room_diag.py")
        command = [console_python(sys.executable), str(entry), "--room", mode]
        try:
            launch_booking_command(command, entry.parent.parent)
        except (OSError, ValueError) as exc:
            messagebox.showerror("診斷無法啟動", str(exc))
            return
        messagebox.showinfo(
            "已啟動唯讀診斷",
            "請在獨立 Chrome 登入並打開所選空間時段頁，再回終端按 Enter。"
            "診斷不會點擊任何預約按鈕，也不會正式送出。")

    def _launch(self):
        try:
            argv = build_booking_args(
                day=self.selected_date, room=self.room.get(), slots=self.slots,
                immediate=self.immediate.get(),
                auto_submit=self.authorize_submit.get(),
                accept_terms=self.accept_terms.get(),
                fallback_any_slot=self.fallback_any_slot.get(),
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
                    "若該日期已開放，請勾選「立即正式預約」（會真的送出）。"
                )
                return

        count = len(self.slots)
        explanation = (f"將正式預約 {count} 個時段：\n"
                       f"{self.selected_date.isoformat()}｜{ROOM_CHOICES[self.room.get()]}\n"
                       + " → ".join(self.slots) + "\n\n"
                       + ("立即正式預約（會送出）" if self.immediate.get() else
                          f"預定放位：{release_datetime(self.selected_date):%Y/%m/%d 00:00}（台北）")
                       + ("\n偏好時段不可用時，會嘗試同日同房間其他時段。"
                          if self.fallback_any_slot.get() else
                          "\n僅嘗試指定時段，不自動改選。")
                       + "\n先登入國圖並停在日期頁，回終端按 Enter。\n"
                       "送出後不會重複送出同一筆預約。確定啟動？")
        if not messagebox.askyesno("正式預約確認", explanation, icon="warning"):
            return

        entry = Path(__file__).resolve().with_name("ncl_openlab_autobook.py")
        command = [console_python(sys.executable), str(entry), *argv]
        try:
            launch_booking_command(command, entry.parent.parent)
        except (OSError, ValueError) as exc:
            messagebox.showerror("無法啟動", str(exc))
            return
        messagebox.showinfo(
            "請檢查獨立終端",
            "已要求系統開啟獨立預約終端。\n"
            "請先確認新終端顯示日期與房間，再手動登入國圖並按 Enter。\n"
            "這只代表已要求啟動，不代表預約成功。"
        )


def main():
    BookingPicker().mainloop()


if __name__ == "__main__":
    main()
