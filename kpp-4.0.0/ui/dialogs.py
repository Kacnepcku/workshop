#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

import tkinter as tk
from typing import Callable, Optional
from config import FONTS


def show_auto_popup(
    parent: tk.Misc,
    message: str,
    level: str = "info",
    title: Optional[str] = None,
    timeout_ms: int = 5000,
    on_close: Optional[Callable[[], None]] = None,
) -> None:
    """Показывает модальное уведомление с автозакрытием."""
    if title is None:
        title = {"info": "Информация", "error": "Ошибка", "warn": "Предупреждение"}.get(
            level, "Информация"
        )

    win = tk.Toplevel(parent)
    win.title(title)
    win_w, win_h = 600, 200
    x = (win.winfo_screenwidth() - win_w) // 2
    y = (win.winfo_screenheight() - win_h) // 2
    win.geometry(f"{win_w}x{win_h}+{x}+{y}")
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    border_color = "red" if level in ("error", "warn") else "green"
    frame = tk.Frame(
        win,
        bd=5,
        relief="flat",
        highlightbackground=border_color,
        highlightcolor=border_color,
        highlightthickness=5,
    )
    frame.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

    tk.Label(
        frame, text=message, font=FONTS["f1b"], justify="center", wraplength=550
    ).pack(expand=True, padx=10, pady=10)

    def _close():
        if win.winfo_exists():
            win.destroy()
        if on_close:
            on_close()

    win.after(timeout_ms, _close)


class ConnectionDialog(tk.Toplevel):
    """Стартовое модальное окно ожидания БД с поддержкой сканирования 12345."""

    def __init__(self, parent: tk.Misc, on_scan_callback: Callable[[str], None]):
        super().__init__(parent)
        self.on_scan_callback = on_scan_callback

        self.title("Подключение к базе данных")
        self.geometry("600x250")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 600) // 2
        y = (self.winfo_screenheight() - 250) // 2
        self.geometry(f"+{x}+{y}")

        frame = tk.Frame(self, bd=0, relief="flat")
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.status_label = tk.Label(
            frame, text="Подключение к БД...", font=FONTS["f1"], justify="center"
        )
        self.status_label.pack(pady=10)

        self.entry = tk.Entry(frame, font=FONTS["f1"], width=15)
        self.entry.pack(pady=10)
        self.entry.bind("<Return>", self._handle_enter)
        self.entry.focus_set()

    def _handle_enter(self, _event) -> None:
        code = self.entry.get().strip()
        self.entry.delete(0, tk.END)
        if code:
            self.on_scan_callback(code)

    def set_status(self, text: str) -> None:
        if self.winfo_exists():
            self.status_label.config(text=text)
