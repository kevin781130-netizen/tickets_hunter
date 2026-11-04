#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tkinter booking console for NCL OPEN LAB (Windows and macOS, same code).

Pick equipment, date and one or two slots, choose when to start (default:
7 days before the date at 00:00:00 Taipei, freely editable), authorise, and
press "start". The window launches the shared engine, shows the countdown and
state, and can cancel while nothing has been booked yet.

Manual browser login remains mandatory. No credentials are handled here.
"""
import calendar
import subprocess
import sys
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import messagebox, ttk

from ncl_openlab_auth import AUTH_LABELS, autofill_available, load_site
from ncl_openlab_control import (
    ACTIVE_STATES, CANCELLABLE, HISTORY_PATH, LOCK_PATH, PROJECT_ROOT, STATE_LABELS,
    DuplicateStart, RunSupervisor, read_history,
)
from ncl_openlab_credentials import CredentialError, CredentialStore
from ncl_openlab_picker_model import (
    ROOM_CHOICES, CATEGORY_CHOICES, TAIPEI, available_slots, selectable_slots,
    category_for_room, category_notice, room_keys_for_category, room_is_verified,
    build_booking_args, default_run_at_text,
    engine_command, parse_start_fields, room_requires_ack, start_notes,
    summary_lines, validate_start,
)

BURGUNDY = "#731d20"
GOLD = "#a88057"
PAPER = "#faf8f5"
DARK = "#2d2926"
MUTED = "#756f6a"
IDLE_BG = "#f2edeb"
STATE_COLORS = {
    "IDLE": MUTED, "LAUNCHING": GOLD, "LOGIN": GOLD, "STANDBY": "#1f6f8b",
    "RUNNING": BURGUNDY, "SUCCESS": "#2e7d32", "FAILED": "#b3261e",
    "UNKNOWN": "#b36b00", "CANCELLED": MUTED, "FINISHED": MUTED, "ERROR": "#b3261e",
}
CANCEL_FORCE_AFTER = timedelta(seconds=10)
TICK_MS = 200


def ui_font(size=10, bold=False):
    family = {"darwin": "PingFang TC", "win32": "Microsoft JhengHei UI"}.get(
        sys.platform, "sans-serif")
    return (family, size, "bold") if bold else (family, size)


def month_shift(year, month, offset):
    index = year * 12 + month - 1 + offset
    return index // 12, index % 12 + 1


class FlatButton(tk.Label):
    """Label-based button: colours render identically on Windows and macOS."""

    def __init__(self, parent, text, command, *, primary=False, **kwargs):
        self._command, self._enabled, self._primary = command, True, primary
        super().__init__(parent, text=text, cursor="hand2", padx=kwargs.pop("padx", 10),
                         pady=kwargs.pop("pady", 6), **kwargs)
        self.bind("<Button-1>", lambda event: self.invoke())
        self.set_look(False)

    def set_look(self, selected):
        if not self._enabled:
            self.configure(bg="#e6e1de", fg="#aaa5a2", relief="flat", cursor="arrow")
        elif self._primary or selected:
            self.configure(bg=BURGUNDY, fg="white", relief="sunken" if selected else "raised",
                           cursor="hand2")
        else:
            self.configure(bg=IDLE_BG, fg=DARK, relief="ridge", cursor="hand2")

    def set_enabled(self, enabled, selected=False):
        self._enabled = bool(enabled)
        self.set_look(selected)

    @property
    def enabled(self):
        return self._enabled

    def invoke(self):
        if self._enabled:
            self._command()


class BookingPicker(tk.Tk):
    def __init__(self, *, popen=subprocess.Popen, history_path=HISTORY_PATH,
                 lock_path=LOCK_PATH, now=None, executable=None, command_builder=engine_command,
                 credential_store=None, site=None):
        super().__init__()
        self._store = credential_store or CredentialStore()
        self._site = site or load_site()
        self._popen, self._history_path, self._lock_path = popen, history_path, lock_path
        self._command_builder = command_builder
        self._now = now or (lambda: datetime.now(TAIPEI))
        self._executable = executable
        self.title("國圖 OPEN LAB｜預約控制台")
        self.geometry("920x820")
        self.minsize(720, 560)
        self.configure(bg=PAPER)

        today = self._now().date()
        self.selected_date = today + timedelta(days=8)
        self.view_year, self.view_month = self.selected_date.year, self.selected_date.month
        self.room = tk.StringVar(value=next(iter(ROOM_CHOICES)))
        self.category = tk.StringVar(value=category_for_room(self.room.get()))
        self.mode = tk.StringVar(value="scheduled")  # scheduled | now
        self.start_date = tk.StringVar()
        self.start_time = tk.StringVar()
        self.sync_clock = tk.BooleanVar(value=True)
        self.authorize_submit = tk.BooleanVar(value=False)
        self.accept_terms = tk.BooleanVar(value=False)
        self.ack_unverified = tk.BooleanVar(value=False)
        self.card_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.use_saved_login = tk.BooleanVar(value=False)
        self.slots = []  # Selection order is also booking order.
        self.supervisor = None
        self._start_edited = False
        self._cancel_at = None
        self._shown_log = 0
        self._build()
        self._reset_start_time()
        self._render_calendar()
        self._render_slots()
        self._refresh_all()
        self._refresh_credentials()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(TICK_MS, self._tick)

    # ------------------------------------------------------------ layout
    def _build(self):
        # The action footer stays visible on small / high-DPI screens; only the
        # configuration area above it scrolls.
        footer = tk.Frame(self, bg=PAPER, padx=18, pady=9)
        footer.pack(side="bottom", fill="x")
        status_row = tk.Frame(footer, bg=PAPER)
        status_row.pack(fill="x")
        self.state_label = tk.Label(status_row, bg=PAPER, anchor="w", font=ui_font(12, True))
        self.state_label.pack(side="left")
        self.countdown_label = tk.Label(status_row, bg=PAPER, fg=DARK, anchor="e",
                                        font=ui_font(16, True))
        self.countdown_label.pack(side="right")
        self.auth_label = tk.Label(footer, bg=PAPER, fg=MUTED, anchor="w", font=ui_font(10))
        self.auth_label.pack(fill="x")
        self.summary = tk.Label(footer, bg=PAPER, fg=DARK, justify="left", anchor="w",
                                font=ui_font(10))
        self.summary.pack(fill="x", pady=(4, 6))
        buttons = tk.Frame(footer, bg=PAPER)
        buttons.pack(fill="x")
        self.start_button = FlatButton(buttons, "啟動排程", self._start, primary=True,
                                       font=ui_font(12, True), pady=9)
        self.start_button.pack(side="left", fill="x", expand=True)
        self.login_button = FlatButton(buttons, "已登入但偵測不到？手動確認", self._confirm_login,
                                       font=ui_font(11), pady=9)
        self.login_button.pack(side="left", fill="x", expand=True, padx=6)
        self.cancel_button = FlatButton(buttons, "取消排程", self._cancel,
                                        font=ui_font(11), pady=9)
        self.cancel_button.pack(side="left", fill="x", expand=True)
        tk.Label(footer, bg=PAPER, fg=MUTED, anchor="w", font=ui_font(9),
                 text="勾選兩段＝預約兩筆；第一筆未確認成功就停止。結果以網站成功頁為準，不保證預約成功。").pack(
                     anchor="w", pady=(4, 0))

        viewport = tk.Frame(self, bg=PAPER)
        viewport.pack(side="top", fill="both", expand=True)
        self.content_canvas = tk.Canvas(viewport, bg=PAPER, highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(viewport, orient="vertical", command=self.content_canvas.yview)
        self.content_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.content_canvas.pack(side="left", fill="both", expand=True)
        main = tk.Frame(self.content_canvas, bg=PAPER, padx=18, pady=12)
        window = self.content_canvas.create_window((0, 0), window=main, anchor="nw")
        main.bind("<Configure>", lambda event: self.content_canvas.configure(
            scrollregion=self.content_canvas.bbox("all")))
        self.content_canvas.bind("<Configure>", lambda event:
                                 self.content_canvas.itemconfigure(window, width=event.width))
        self.content_canvas.bind_all("<MouseWheel>", self._scroll_wheel)
        self.content_canvas.bind_all("<Button-4>", lambda event: self._scroll_units(-1))
        self.content_canvas.bind_all("<Button-5>", lambda event: self._scroll_units(1))

        tk.Label(main, text="國圖 OPEN LAB 預約控制台", bg=PAPER, fg=BURGUNDY,
                 font=ui_font(19, True)).pack(anchor="w")
        tk.Label(main, text="選空間類別 → 選房間／設備 → 選日期 → 選時段 → 設定排程與授權",
                 bg=PAPER, fg=DARK, font=ui_font(10)).pack(anchor="w", pady=(3, 13))

        room_row = tk.LabelFrame(main, text=" 1｜空間類別 → 房間／設備 ", bg=PAPER, fg=DARK,
                                 padx=12, pady=8)
        room_row.pack(fill="x", pady=(0, 11))
        self.category_box = ttk.Combobox(room_row, state="readonly", width=23,
                                         values=list(CATEGORY_CHOICES.values()))
        self.category_box.current(list(CATEGORY_CHOICES).index(self.category.get()))
        self.category_box.pack(side="left")
        self.category_box.bind("<<ComboboxSelected>>", self._category_selected)
        self.room_box = ttk.Combobox(room_row, state="readonly", width=34,
                                     values=[ROOM_CHOICES[k] for k in
                                             room_keys_for_category(self.category.get())])
        self.room_box.current(room_keys_for_category(self.category.get()).index(self.room.get()))
        self.room_box.pack(side="left", padx=(10, 0))
        self.room_box.bind("<<ComboboxSelected>>", self._room_selected)
        self.room_note = tk.Label(room_row, bg=PAPER, fg=MUTED, font=ui_font(9),
                                  wraplength=240, justify="left")
        self.room_note.pack(side="left", padx=10)

        choices_row = tk.Frame(main, bg=PAPER)
        choices_row.pack(fill="x", pady=(0, 11))
        choices_row.columnconfigure(0, weight=1, uniform="choice")
        choices_row.columnconfigure(1, weight=1, uniform="choice")
        cal_frame = tk.LabelFrame(choices_row, text=" 2｜月曆選擇預約日期 ", bg=PAPER,
                                  fg=DARK, padx=8, pady=8)
        cal_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        navigation = tk.Frame(cal_frame, bg=PAPER)
        navigation.pack(fill="x", pady=(0, 8))
        FlatButton(navigation, "◀ 上個月", lambda: self._change_month(-1)).pack(side="left")
        self.month_caption = tk.Label(navigation, bg=PAPER, fg=BURGUNDY, font=ui_font(13, True))
        self.month_caption.pack(side="left", expand=True)
        FlatButton(navigation, "下個月 ▶", lambda: self._change_month(1)).pack(side="right")
        self.days_frame = tk.Frame(cal_frame, bg=PAPER)
        self.days_frame.pack(fill="x")
        for column in range(7):
            self.days_frame.columnconfigure(column, weight=1, uniform="day")
        self.date_caption = tk.Label(cal_frame, bg=PAPER, fg=DARK, font=ui_font(10))
        self.date_caption.pack(anchor="w", pady=(7, 0))

        slot_area = tk.LabelFrame(choices_row, text=" 3｜時段（可複選兩個） ",
                                  bg=PAPER, fg=DARK, padx=8, pady=8)
        slot_area.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.slot_frame = tk.Frame(slot_area, bg=PAPER)
        self.slot_frame.pack(fill="x")
        self.slot_note = tk.Label(slot_area, bg=PAPER, fg=DARK, anchor="w", font=ui_font(10))
        self.slot_note.pack(fill="x", pady=(7, 0))
        FlatButton(slot_area, "清除時段", self._clear_slots).pack(anchor="e")

        when = tk.LabelFrame(main, text=" 4｜自動開始預約的時間（台北時間 Asia/Taipei） ",
                             bg=PAPER, fg=DARK, padx=12, pady=8)
        when.pack(fill="x", pady=(0, 11))
        mode_row = tk.Frame(when, bg=PAPER)
        mode_row.pack(fill="x")
        ttk.Radiobutton(mode_row, text="排程執行（到時間自動開始）", value="scheduled",
                        variable=self.mode, command=self._refresh_all).pack(side="left")
        ttk.Radiobutton(mode_row, text="立即執行（登入後馬上開始，會真的送出）", value="now",
                        variable=self.mode, command=self._refresh_all).pack(side="left", padx=20)
        time_row = tk.Frame(when, bg=PAPER)
        time_row.pack(fill="x", pady=(8, 0))
        tk.Label(time_row, text="日期", bg=PAPER, fg=DARK, font=ui_font(10)).pack(side="left")
        self.date_entry = ttk.Entry(time_row, textvariable=self.start_date, width=12)
        self.date_entry.pack(side="left", padx=(4, 12))
        tk.Label(time_row, text="時間（精確到秒）", bg=PAPER, fg=DARK,
                 font=ui_font(10)).pack(side="left")
        self.time_entry = ttk.Entry(time_row, textvariable=self.start_time, width=10)
        self.time_entry.pack(side="left", padx=(4, 12))
        FlatButton(time_row, "重設為預設", self._reset_start_time).pack(side="left")
        for entry in (self.date_entry, self.time_entry):
            entry.bind("<KeyRelease>", self._start_typed)
        self.start_note = tk.Label(when, bg=PAPER, fg=MUTED, anchor="w", font=ui_font(9))
        self.start_note.pack(fill="x", pady=(5, 0))
        ttk.Checkbutton(when, text="啟動前以網路時間校正系統時鐘（失敗時改用系統時間）",
                        variable=self.sync_clock).pack(anchor="w", pady=(4, 0))

        login = tk.LabelFrame(main, text=" 5｜登入與憑證 ", bg=PAPER, fg=DARK, padx=12, pady=8)
        login.pack(fill="x", pady=(0, 11))
        tk.Label(login, bg=PAPER, fg=MUTED, anchor="w", justify="left", font=ui_font(9),
                 text="已登入時直接沿用；未登入時由你親自在瀏覽器輸入圖片驗證碼並登入，"
                      "程式只確認結果，不辨識、不代填驗證碼。").pack(fill="x")
        cred_row = tk.Frame(login, bg=PAPER)
        cred_row.pack(fill="x", pady=(8, 0))
        tk.Label(cred_row, text="閱覽證號", bg=PAPER, fg=DARK, font=ui_font(10)).pack(side="left")
        self.card_entry = ttk.Entry(cred_row, textvariable=self.card_var, width=16)
        self.card_entry.pack(side="left", padx=(4, 12))
        tk.Label(cred_row, text="密碼", bg=PAPER, fg=DARK, font=ui_font(10)).pack(side="left")
        self.password_entry = ttk.Entry(cred_row, textvariable=self.password_var, width=16, show="●")
        self.password_entry.pack(side="left", padx=(4, 12))
        FlatButton(cred_row, "安全儲存憑證", self._save_credentials).pack(side="left")
        FlatButton(cred_row, "刪除已儲存憑證", self._delete_credentials).pack(side="left", padx=6)
        self.cred_status = tk.Label(login, bg=PAPER, fg=DARK, anchor="w", font=ui_font(9))
        self.cred_status.pack(fill="x", pady=(5, 0))
        self.saved_login_check = ttk.Checkbutton(
            login, text="登入頁出現時自動填入已儲存的帳密（驗證碼與登入鈕仍由我操作）",
            variable=self.use_saved_login)
        self.saved_login_check.pack(anchor="w", pady=(4, 0))
        self.saved_login_note = tk.Label(login, bg=PAPER, fg=MUTED, anchor="w", font=ui_font(9))
        self.saved_login_note.pack(fill="x")
        tk.Label(login, bg=PAPER, fg=MUTED, anchor="w", font=ui_font(9),
                 text="帳密只存在 macOS Keychain／Windows 憑證管理員，不會寫入檔案、環境變數或命令列。").pack(fill="x")

        auth = tk.LabelFrame(main, text=" 6｜授權與條款 ", bg=PAPER, fg=DARK, padx=12, pady=8)
        auth.pack(fill="x", pady=(0, 11))
        ttk.Checkbutton(auth, text="我已閱讀網站規範；對我已親自同意過的同一版本，允許程式自動按「同意」"
                                   "（規範內容更新時會請我重新同意）",
                        variable=self.accept_terms).pack(anchor="w")
        ttk.Checkbutton(auth, text="我明確授權正式送出預約（必須勾選）",
                        variable=self.authorize_submit,
                        command=self._refresh_all).pack(anchor="w", pady=(2, 0))
        self.ack_check = ttk.Checkbutton(
            auth, text="我了解此設備尚未實機驗證，仍要嘗試（確認頁比對不符時不會送出）",
            variable=self.ack_unverified)

        logs = tk.LabelFrame(main, text=" 7｜執行紀錄 ", bg=PAPER, fg=DARK, padx=8, pady=8)
        logs.pack(fill="both", expand=True, pady=(0, 6))
        self.log_box = tk.Text(logs, height=7, wrap="word", state="disabled", bg="white",
                               fg=DARK, font=ui_font(9))
        self.log_box.pack(fill="x")
        tk.Label(logs, text="歷史預約紀錄", bg=PAPER, fg=DARK, anchor="w",
                 font=ui_font(9, True)).pack(fill="x", pady=(8, 2))
        self.history_box = tk.Listbox(logs, height=5, bg="white", fg=DARK, font=ui_font(9),
                                      activestyle="none")
        self.history_box.pack(fill="x")

    # --------------------------------------------------------- scrolling
    def _scroll_wheel(self, event):
        if event.delta:
            self._scroll_units(-1 if event.delta > 0 else 1)

    def _scroll_units(self, units):
        self.content_canvas.yview_scroll(units, "units")

    # -------------------------------------------------------- selection
    @property
    def locked(self):
        return self.supervisor is not None and self.supervisor.active

    def _room_key(self):
        return self.room.get()

    def _category_selected(self, _event=None):
        if self.locked:
            self.category_box.current(list(CATEGORY_CHOICES).index(self.category.get()))
            return
        index = self.category_box.current()
        if index < 0:
            return
        self.category.set(list(CATEGORY_CHOICES)[index])
        keys = room_keys_for_category(self.category.get())
        self.room_box.configure(values=[ROOM_CHOICES[k] for k in keys])
        self.room.set(keys[0] if keys else "")
        if keys:
            self.room_box.current(0)
        else:
            self.room_box.set("")
        self.slots.clear()
        self.ack_unverified.set(False)
        self._render_slots()
        self._refresh_all()

    def _room_selected(self, _event=None):
        keys = room_keys_for_category(self.category.get())
        if self.locked:
            if self.room.get() in keys:
                self.room_box.current(keys.index(self.room.get()))
            return
        index = self.room_box.current()
        if index < 0 or index >= len(keys):
            return
        self.room.set(keys[index])
        self.slots.clear()
        self.ack_unverified.set(False)
        self._render_slots()
        self._refresh_all()

    def _change_month(self, offset):
        self.view_year, self.view_month = month_shift(self.view_year, self.view_month, offset)
        self._render_calendar()

    def _render_calendar(self):
        for widget in self.days_frame.winfo_children():
            widget.destroy()
        self.month_caption.config(text=f"{self.view_year} 年 {self.view_month:02d} 月")
        for col, label in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            tk.Label(self.days_frame, text=label, bg=PAPER, fg=DARK).grid(row=0, column=col, pady=2)
        today = self._now().date()
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(self.view_year, self.view_month)
        for row, week in enumerate(weeks, start=1):
            for col, day_number in enumerate(week):
                if not day_number:
                    continue
                chosen = date(self.view_year, self.view_month, day_number)
                # Openings are seven days ahead; allow picking up to 31 days out.
                enabled = today <= chosen <= today + timedelta(days=31)
                cell = FlatButton(self.days_frame, str(day_number),
                                  lambda chosen=chosen: self._pick_date(chosen), padx=4, pady=3)
                cell.set_enabled(enabled, selected=chosen == self.selected_date)
                cell.grid(row=row, column=col, padx=1, pady=1, sticky="ew")
        self.date_caption.config(text=f"已選：{self.selected_date.isoformat()}（台北時間）")

    def _pick_date(self, selected):
        if self.locked:
            return
        self.selected_date = selected
        if not self._start_edited:
            self._reset_start_time()
        self._render_calendar()
        self._refresh_all()

    def _clear_slots(self):
        if self.locked:
            return
        self.slots.clear()
        self._render_slots()
        self._refresh_all()

    def _toggle_slot(self, value):
        if self.locked:
            return
        if value in self.slots:
            self.slots.remove(value)
        elif len(self.slots) >= 2:
            messagebox.showwarning("最多兩段", "每天最多選兩個時段。先取消一個時段再選。")
            return
        else:
            self.slots.append(value)
        self._render_slots()
        self._refresh_all()

    def _render_slots(self):
        for widget in self.slot_frame.winfo_children():
            widget.destroy()
        choices = selectable_slots(self._room_key())
        columns = 2 if len(choices) > 4 else 3
        for col in range(columns):
            self.slot_frame.columnconfigure(col, weight=1, uniform="slot")
        for index, slot in enumerate(choices):
            priority = (self.slots.index(slot) + 1) if slot in self.slots else None
            label = f"第{priority}筆 {slot}" if priority else slot
            button = FlatButton(self.slot_frame, label, lambda slot=slot: self._toggle_slot(slot),
                                padx=4)
            button.set_enabled(True, selected=bool(priority))
            button.grid(row=index // columns, column=index % columns, padx=3, pady=3, sticky="ew")
        self.slot_note.config(
            text=("NOT_VERIFIED｜此設備時段尚未實機盤點，無法選取" if not choices
                  else "選擇一個＝預約一筆；選擇兩個＝依順序預約兩筆。" if not self.slots
                  else "預約順序：" + " → ".join(self.slots)))

    # ----------------------------------------------------------- schedule
    def _reset_start_time(self):
        if self.locked:
            return
        stamp = default_run_at_text(self.selected_date)
        self.start_date.set(stamp[:10])
        self.start_time.set(stamp[11:])
        self._start_edited = False
        if hasattr(self, "summary"):
            self._refresh_all()

    def _start_typed(self, _event=None):
        self._start_edited = True
        self._refresh_all()

    def _parse_start(self):
        """(run_at or None, error text or None) for the current mode."""
        if self.mode.get() == "now":
            return None, None
        try:
            run_at = parse_start_fields(self.start_date.get(), self.start_time.get())
        except ValueError as exc:
            return None, str(exc)
        return run_at, validate_start(self.selected_date, run_at, self._now())

    # ----------------------------------------------------------- refresh
    def _refresh_all(self):
        note = category_notice(self.category.get())
        if self._room_key() and not room_is_verified(self._room_key()):
            note = "NOT_VERIFIED｜尚未實機驗證，不開放正式提交"
        self.room_note.config(text=note)
        if room_requires_ack(self._room_key()):
            self.ack_check.pack(anchor="w", pady=(2, 0))
        else:
            self.ack_check.pack_forget()
        now_mode = self.mode.get() == "now"
        for entry in (self.date_entry, self.time_entry):
            entry.configure(state="disabled" if now_mode or self.locked else "normal")
        self.category_box.configure(state="disabled" if self.locked else "readonly")
        self.room_box.configure(state="disabled" if self.locked or not self._room_key()
                                else "readonly")
        run_at, error = self._parse_start()
        if now_mode:
            self.start_note.config(text="立即執行：登入完成後立刻開始預約，不等待放位時間。", fg=BURGUNDY)
        elif error:
            self.start_note.config(text=error, fg="#b3261e")
        else:
            self.start_note.config(text=start_notes(self.selected_date, run_at), fg=MUTED)
        self.summary.config(text="\n".join(summary_lines(
            day=self.selected_date, room=self._room_key(), slots=self.slots,
            immediate=now_mode, run_at=run_at)))
        self.start_button.configure(text="立即執行" if now_mode else "啟動排程")
        self._refresh_buttons()

    def _refresh_credentials(self):
        self.cred_status.config(text="憑證：" + self._store.describe())
        saved = self._store.has_saved()
        available = autofill_available(self._site)
        self.saved_login_check.configure(state="normal" if saved and available else "disabled")
        if not (saved and available):
            self.use_saved_login.set(False)
        self.saved_login_note.config(
            text=("登入頁欄位已由真實頁面盤點；實際填入與登入結果尚待實機驗證（驗證碼仍由你輸入）"
                  if available else
                  "登入頁欄位尚未實機確認：不會自動填入，請手動登入（NOT_VERIFIED）"))

    def _save_credentials(self):
        try:
            self._store.save(self.card_var.get().strip(), self.password_var.get())
        except CredentialError as exc:
            messagebox.showwarning("無法儲存憑證", str(exc))
            return
        finally:
            self.password_var.set("")      # never keep the password in the window
        self.card_var.set("")
        self._refresh_credentials()
        messagebox.showinfo("已儲存", "憑證已存入系統金鑰庫。")

    def _delete_credentials(self):
        if not messagebox.askyesno("刪除憑證", "確定刪除已儲存的閱覽證號與密碼？"):
            return
        try:
            self._store.delete()
        except CredentialError as exc:
            messagebox.showwarning("無法刪除", str(exc))
        self._refresh_credentials()

    def _auth_text(self):
        sup = self.supervisor
        if sup is None or sup.auth_state is None:
            return ""
        detail = sup.auth_detail if sup.auth_detail and sup.auth_detail != AUTH_LABELS[sup.auth_state] else ""
        return "登入：" + AUTH_LABELS[sup.auth_state] + (f"（{detail}）" if detail else "")

    def _refresh_buttons(self):
        state = self.supervisor.state if self.supervisor else "IDLE"
        self.start_button.set_enabled(state not in ACTIVE_STATES and
                                      room_is_verified(self._room_key()))
        # Manual confirmation is only a fallback when the page cannot be classified.
        self.login_button.set_enabled(
            state == "LOGIN" and (self.supervisor.auth_state in (None, "AUTH_INTERACTION_REQUIRED")
                                  if self.supervisor else False))
        self.auth_label.config(text=self._auth_text())
        self.cancel_button.set_enabled(state in CANCELLABLE)
        self.state_label.config(text=STATE_LABELS[state], fg=STATE_COLORS[state])

    def _tick(self):
        try:
            if self.supervisor is not None:
                changed = self.supervisor.pump()
                if changed:
                    self._refresh_buttons()
                    self._show_log()
                    if not self.supervisor.active:
                        self._refresh_all()
                        self._show_history()
                self.countdown_label.config(text=self._countdown_text())
                self._force_stop_if_stuck()
        finally:
            self.after(TICK_MS, self._tick)

    def _countdown_text(self):
        seconds = self.supervisor.countdown()
        if seconds is None:
            return ""
        return "即將開始…" if seconds <= 0 else f"{self.supervisor.countdown_text()} 後開始預約"

    def _force_stop_if_stuck(self):
        sup = self.supervisor
        if sup.cancel_requested and sup.active:
            self._cancel_at = self._cancel_at or self._now()
            if self._now() - self._cancel_at > CANCEL_FORCE_AFTER:
                sup.force_stop()
        else:
            self._cancel_at = None

    def _show_log(self):
        rows = self.supervisor.log[self._shown_log:]
        self._shown_log = len(self.supervisor.log)
        self.log_box.configure(state="normal")
        for stamp, text in rows:
            self.log_box.insert("end", f"[{stamp}] {text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _show_history(self):
        self.history_box.delete(0, "end")
        for row in read_history(8, self._history_path):
            self.history_box.insert("end", "｜".join(str(x) for x in (
                str(row.get("finished_taipei", ""))[5:19].replace("T", " "),
                ROOM_CHOICES.get(row.get("room"), row.get("room")), row.get("date"),
                " → ".join(row.get("slots") or []), STATE_LABELS.get(row.get("state"), row.get("state")))))

    # ----------------------------------------------------------- actions
    def _start(self):
        if self.locked:
            messagebox.showwarning("已在執行", "已有預約程序在執行，請先等待結果或取消。")
            return
        run_at, error = self._parse_start()
        if error:
            messagebox.showwarning("請確認啟動時間", error)
            return
        immediate = self.mode.get() == "now"
        try:
            argv = build_booking_args(
                day=self.selected_date, room=self._room_key(), slots=self.slots,
                immediate=immediate, run_at=run_at, auto_submit=self.authorize_submit.get(),
                accept_terms=self.accept_terms.get(), ack_unverified=self.ack_unverified.get(),
                sync_clock=self.sync_clock.get(), machine_status=True, auth_check=True,
                use_saved_login=self.use_saved_login.get())
        except ValueError as exc:
            messagebox.showwarning("請確認設定", str(exc))
            return
        lines = summary_lines(day=self.selected_date, room=self._room_key(), slots=self.slots,
                              immediate=immediate, run_at=run_at)
        text = ("將正式預約，並會真的送出：\n\n" + "\n".join(lines) +
                "\n\n接著會開啟 Chrome：已登入會直接沿用；未登入時請在瀏覽器輸入圖片驗證碼並登入，"
                "程式會自動確認登入狀態後進入待命。\n"
                "送出後結果不明時不會重複送出；不保證預約成功，以網站結果為準。確定啟動？")
        if not messagebox.askyesno("正式預約確認", text, icon="warning"):
            return
        self.supervisor = RunSupervisor(
            self._command_builder(argv, self._executable),
            meta={"room": self._room_key(), "date": self.selected_date.isoformat(),
                  "slots": list(self.slots), "mode": "now" if immediate else "scheduled",
                  "run_at": run_at.isoformat() if run_at else None},
            popen=self._popen, cwd=str(PROJECT_ROOT), history_path=self._history_path,
            lock_path=self._lock_path, now=self._now)
        self._shown_log = 0
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        try:
            self.supervisor.start()
        except DuplicateStart as exc:
            messagebox.showwarning("已在執行", str(exc))
            self.supervisor = None
            return
        except OSError as exc:
            messagebox.showerror("無法啟動", str(exc))
            self.supervisor = None
            return
        self._refresh_all()
        self._show_log()

    def _confirm_login(self):
        if self.supervisor and self.supervisor.confirm_login():
            self._refresh_buttons()

    def _cancel(self):
        if self.supervisor and self.supervisor.cancel():
            self._refresh_buttons()

    def _on_close(self):
        sup = self.supervisor
        if sup is not None and sup.state == "RUNNING":
            messagebox.showwarning("預約進行中", "預約正在執行，請等結果出現後再關閉視窗。")
            return
        if sup is not None and sup.active:
            if not messagebox.askyesno("取消排程", "排程尚未開始預約。取消並關閉視窗嗎？"):
                return
            sup.cancel()
        self.destroy()


def main():
    BookingPicker().mainloop()


if __name__ == "__main__":
    main()
