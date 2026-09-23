# -*- coding: utf-8 -*-

"""
dialogs.py — всплывающие сообщения и утилиты позиционирования окон.

Notifier здесь — единственный способ показать что-то оператору: пишет в лог
и открывает автозакрывающееся окно (как Notifier в 3.5.4, но без прямого
доступа к чужим виджетам — возврат фокуса передаётся колбэком).
"""

from __future__ import annotations

from typing import Callable, Optional

import tkinter as tk

from ui.fonts import font1b
from logging_setup import log_message


def center_on_screen(win: tk.Toplevel, width: int, height: int) -> None:
    """Размер + центрирование окна по экрану."""
    x = (win.winfo_screenwidth() - width) // 2
    y = (win.winfo_screenheight() - height) // 2
    win.geometry(f"{width}x{height}+{x}+{y}")


class Notifier:
    """Лог + модальное автозакрывающееся сообщение."""

    _LEVEL_PREFIX = {"info": "", "error": "ОШИБКА", "warn": "ПРЕДУПРЕЖДЕНИЕ"}
    _LEVEL_TITLE = {"info": "Информация", "error": "Ошибка",
                    "warn": "Предупреждение"}

    def __init__(self, root: tk.Misc,
                 restore_focus: Optional[Callable[[], None]] = None) -> None:
        self._root = root
        self._restore_focus = restore_focus or (lambda: None)

    def notify(self, message: str, level: str = "info",
               title: Optional[str] = None, timeout: int = 5000) -> None:
        prefix = self._LEVEL_PREFIX[level]
        log_message(f"{prefix}: {message}" if prefix else message)
        msg_type = "error" if level in ("error", "warn") else "info"
        self.show_auto_message(message,
                               title or self._LEVEL_TITLE[level],
                               timeout, msg_type=msg_type)

    def show_auto_message(self, message: str, title: str = "Информация",
                          timeout: int = 5000, msg_type: str = "info") -> None:
        win = tk.Toplevel(self._root)
        win.title(title)
        center_on_screen(win, 600, 200)
        win.resizable(False, False)
        win.transient(self._root)
        win.grab_set()

        border_color = "red" if msg_type == "error" else "green"
        frame = tk.Frame(win, bd=5, relief="flat",
                         highlightbackground=border_color,
                         highlightcolor=border_color,
                         highlightthickness=5)
        frame.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        lbl = tk.Label(frame, text=message, font=font1b,
                       justify="center", wraplength=550)
        lbl.pack(expand=True, padx=10, pady=10)

        def _close() -> None:
            win.destroy()
            self._restore_focus()

        win.after(timeout, _close)
