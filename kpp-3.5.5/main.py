#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

"""
main.py — точка входа kpp 3.5.5.

Конфигурация и шрифты вынесены из main (как было в 3.5.4) в config.py и
ui/fonts.py соответственно; здесь только запуск Tk-приложения.
"""

import sys
import tkinter as tk


def main() -> int:
    try:
        import config  # noqa: F401  (проверка конфигурации/платформы до GUI)
        from logging_setup import setup_logging, log_message
        from app import Application
    except RuntimeError as e:
        # Неподдерживаемая платформа / битая конфигурация — без «тёмного» exit(0)
        print(f"Ошибка запуска: {e}", file=sys.stderr)
        return 1

    setup_logging()
    root = tk.Tk()
    try:
        Application(root)
        root.mainloop()
    except Exception:
        log_message("Аварийное завершение приложения", exc_info=True)
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
