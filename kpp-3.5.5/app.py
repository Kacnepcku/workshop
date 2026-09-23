#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

"""
app.py — координатор GUI kpp 3.5.5 (тонкий, ~250 строк вместо 1000).

Слои:
    config / logging_setup — настройки и лог
    database.ConnectionHolder — соединение с БД (ping/reconnect, транзакции)
    db                      — только SQL, возвращает dataclass-ы
    logic.*                 — чистые правила (политики мест, тексты, решения)
    ui.panels / ui.dialogs  — инкапсулированные виджеты и уведомления

Здесь живут только менеджеры-исполнители (WorkerSessionManager,
DetalProcessor, InputHandler, ConnectionManager) и Application.
Поведение для оператора сохранено: те же сообщения, та же логика
старт/стоп/перемещение/регистрация.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import tkinter as tk
from tkinter import ttk

import config
import db as dbm
from database import ConnectionHolder
from logging_setup import log_message
from logic.sessions import (check_capacity, decide_worker_action,
                            duplicate_message, missing_dimensions_message,
                            registered_message, validate_detal)
from logic.workplace_policy import get_policy, product_group_order
from ui.dialogs import Notifier, center_on_screen
from ui.fonts import font1, font3, font4
from ui.panels import (DetalInfoPanel, ImageDisplay, StatsPanel,
                       WorkersTree, WorkplaceHeader)


# --------------------------------------------------------------------------- #
#  ConnectionManager                                                            #
# --------------------------------------------------------------------------- #
class ConnectionManager:
    """Модальный диалог ожидания БД + повторные попытки подключения."""

    def __init__(self, app: "Application") -> None:
        self.app = app
        self._dialog: Optional[tk.Toplevel] = None

    def show_dialog(self) -> None:
        app = self.app
        dialog = tk.Toplevel(app.root)
        dialog.title("Подключение к базе данных")
        dialog.resizable(False, False)
        dialog.transient(app.root)
        dialog.grab_set()
        center_on_screen(dialog, 600, 250)

        frame = tk.Frame(dialog, bd=0, relief="flat")
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        tk.Label(frame, text="Подключение к БД", font=font1,
                 justify="center").pack(pady=10)

        entry = tk.Entry(frame, font=font1, width=15)
        entry.pack(pady=10)
        entry.bind("<Return>", app.input.on_scan)
        entry.focus_set()
        self._dialog = dialog

    def attempt(self) -> None:
        app = self.app
        try:
            app.holder.connect()
            log_message("Подключение к БД успешно")
        except Exception as e:
            log_message(f"Ошибка подключения к БД: {e}")
            app.root.after(config.RECONNECT_MS, self.attempt)
            return
        if self._dialog is not None:
            self._dialog.destroy()
            self._dialog = None
        app.entry = None  # поле диалога уничтожено; новое создаст build_ui
        app.build_ui()


# --------------------------------------------------------------------------- #
#  WorkerSessionManager                                                         #
# --------------------------------------------------------------------------- #
class WorkerSessionManager:
    """Старт/стоп/перемещение сотрудников, автообновление списка."""

    def __init__(self, app: "Application") -> None:
        self.app = app

    def process(self, rab: int) -> None:
        app = self.app
        try:
            # holder берём внутри try: AttributeError (например, у тестовой
            # заглушки приложения без holder) не должен приводить к rollback
            # несуществующей транзакции
            holder = app.holder
            with holder.transaction() as cur:
                fio = dbm.get_worker_fio(holder, rab)
                if fio is None:
                    raise _Abort(f"Работник с кодом {rab} не найден в базе.",
                                 level="error")
                session = dbm.get_open_session(holder, rab)
                action = decide_worker_action(
                    rab, app.current_ip, session.ip if session else None)

                if action.kind == "stop":
                    self._stop(cur, holder, rab, fio)
                elif action.kind == "move":
                    assert session is not None
                    self._move(cur, holder, rab, fio, session.ip)
                else:
                    self._register(cur, holder, rab, fio)
        except _Abort as e:
            # transaction() уже выполнил rollback при выходе с исключением
            app.notify(str(e), level=e.level)
            return
        except Exception as e:
            app.notify(f"Ошибка обработки сотрудника: {e}", level="error")
            return
        self.update_list()

    # -- исполнения решений (внутри открытой транзакции) ----------------------
    def _stop(self, cur, holder, rab, fio) -> None:
        app = self.app
        dbm.close_session(holder, rab)
        if not dbm.decrement_workplace_cur(holder, app.current_ip):
            raise _Abort(f"Счётчик RAB_CUR на месте {app.workplace_name} "
                         f"уже равен 0. Операция отменена.", level="error")
        cur.connection.commit()
        app.notify(f"Работник {fio} завершил работу на {app.workplace_name}.")

    def _move(self, cur, holder, rab, fio, old_ip) -> None:
        app = self.app
        info = dbm.get_workplace_info(holder, app.current_ip)
        if info is None:
            raise _Abort("Текущее рабочее место не найдено.", level="error")
        full = check_capacity(info)
        if full:
            raise _Abort(full + " Перемещение невозможно.", level="warn")
        old_place_name = dbm.get_workplace_name(holder, old_ip)
        dbm.close_session(holder, rab)
        if not dbm.decrement_workplace_cur(holder, old_ip):
            raise _Abort("Счётчик RAB_CUR на старом месте уже равен 0. "
                         "Операция отменена.", level="error")
        dbm.create_session(holder, rab, app.current_ip)
        dbm.increment_workplace_cur(holder, app.current_ip)
        cur.connection.commit()
        app.notify(f"Работник {fio} перемещён с '{old_place_name}' "
                   f"на '{info.name}'.")

    def _register(self, cur, holder, rab, fio) -> None:
        app = self.app
        info = dbm.get_workplace_info(holder, app.current_ip)
        if info is None:
            raise _Abort("Текущее рабочее место не найдено.", level="error")
        full = check_capacity(info)
        if full:
            raise _Abort(full + " Регистрация невозможна.", level="warn")
        dbm.create_session(holder, rab, app.current_ip)
        dbm.increment_workplace_cur(holder, app.current_ip)
        cur.connection.commit()
        app.notify(f"Работник {fio} зарегистрирован на {info.name}.")

    # -- служебные операции -----------------------------------------------------
    def close_previous(self) -> None:
        """Пакетно закрыть зависшие сессии за предыдущие дни (был цикл N UPDATE)."""
        app = self.app
        try:
            with app.holder.transaction() as cur:
                closed = dbm.close_stale_sessions_batch(app.holder)
            if closed:
                log_message(f"Пакетно закрыто {closed} зависших сессий "
                            f"сотрудников за предыдущие дни (в 18:00 дня "
                            f"открытия).")
                app.notify(f"Закрыто {closed} сессий сотрудников за "
                           f"предыдущие дни (в 18:00 дня открытия).")
            else:
                log_message("Нет зависших сессий сотрудников за предыдущие дни.")
                app.focus_entry()
        except Exception as e:
            app.notify("Не удалось закрыть предыдущие сессии сотрудников: "
                       f"{e}", level="error")

    def close_all(self) -> None:
        """Закрыть все открытые сессии текущего места (один пакетный UPDATE)."""
        app = self.app
        try:
            with app.holder.transaction():
                closed = dbm.close_all_sessions_at_ip(app.holder,
                                                      app.current_ip)
            if closed:
                log_message(f"Закрыто {closed} сессий на рабочем месте "
                            f"{app.workplace_name}")
            else:
                log_message("Нет открытых сессий на данном рабочем месте.")
            self.update_list()
        except Exception as e:
            app.notify(f"Ошибка закрытия сессий: {e}", level="error")

    def update_list(self) -> None:
        """Обновить таблицу сотрудников и счётчик занятости."""
        app = self.app
        try:
            workers = dbm.get_current_workers(app.holder, app.current_ip)
            app.workers_tree.update_workers(workers)
            info = dbm.get_workplace_info(app.holder, app.current_ip)
            if info is not None:
                app.header.capacity.set(info.rab_cur)
            app.focus_entry()
        except Exception as e:
            app.notify(f"Не удалось обновить список сотрудников: {e}",
                       level="error")

    def auto_update(self) -> None:
        """Раз в AUTO_UPDATE_MS освежать список (отработанное время тикает)."""
        self.update_list()
        self.app.root.after(config.AUTO_UPDATE_MS, self.auto_update)


# --------------------------------------------------------------------------- #
#  DetalProcessor                                                               #
# --------------------------------------------------------------------------- #
class DetalProcessor:
    """Регистрация деталей согласно политике рабочего места."""

    def __init__(self, app: "Application") -> None:
        self.app = app

    def process(self, detal: str) -> None:
        app = self.app
        holder = app.holder
        policy = get_policy(app.gr)
        try:
            info = dbm.get_detal_full_info(holder, detal)
            if info is None:
                app.notify(f"Деталь с кодом {detal} не найдена.",
                           level="error")
                app.detal_panel.clear()
                return

            decision = validate_detal(info, policy, config.GRI_IMPOST)
            if not decision.allowed:
                app.notify(decision.message, level=decision.level)
                app.detal_panel.clear()
                return

            if dbm.has_open_detal_session_at_ip(holder, detal,
                                                app.current_ip):
                self._show_registered(info)
                return

            dup = dbm.has_open_duplicate(
                holder, info.bci, app.current_ip,
                gri=None if policy.dup_check_by_bci_only else info.gri,
                exclude_detal=detal)
            if dup:
                app.notify(duplicate_message(info.bci, info.gri,
                                             app.workplace_name,
                                             policy.dup_check_by_bci_only),
                           level="warn")
                return

            self._register(detal, info, policy)
        except Exception as e:
            app.notify(f"Ошибка обработки детали: {e}", level="error")

    # -- внутреннее -------------------------------------------------------------
    def _product_or_detail_dims(self, bci: str, gri: str, policy):
        """Габариты: для мест 5-6 — изделие целиком (рама→створка), иначе — деталь."""
        if policy.show_product_dimensions:
            for g in product_group_order():
                dims = dbm.get_dimensions_for_bci_gri(self.app.holder, bci, g)
                if dims.is_known:
                    return dims, "Изделие"
            return dims, "Изделие"   # dims последнего кандидата — «нет данных»
        dims = dbm.get_dimensions_for_bci_gri(self.app.holder, bci, gri)
        return dims, None

    def _show_registered(self, info: dbm.DetalInfo) -> None:
        """Деталь уже зарегистрирована на этом месте — показать данные."""
        app = self.app
        policy = get_policy(app.gr)
        app.notify(registered_message(info.detal, info, app.workplace_name),
                   level="warn")
        dims, override = self._product_or_detail_dims(info.bci, info.gri,
                                                      policy)
        app.detal_panel.show(info, dims, override_type=override)
        app.images.show_detal(info.zaknum, info.konid)

    def _register(self, detal: str, info: dbm.DetalInfo, policy) -> None:
        app = self.app
        dims, override = self._product_or_detail_dims(info.bci, info.gri,
                                                      policy)
        if not dims.is_known:
            app.notify(missing_dimensions_message(
                policy.show_product_dimensions), level="error")
            return
        with app.holder.transaction():
            dbm.create_detal_session(app.holder, detal, app.current_ip,
                                     app.gr, info.bci, info.gri,
                                     dims.perimeter_m, dims.area_m2)
        log_message(f"Деталь {detal} зарегистрирована на IP "
                    f"{app.current_ip} (BCI={info.bci}, GRI={info.gri})")
        app.detal_panel.show(info, dims, override_type=override)
        app.images.show_detal(info.zaknum, info.konid)
        app.notify(f"Зарегистрировано изделие\n"
                   f"Заказ: {info.zaknum}\n"
                   f"Конструкция: {info.konname}", timeout=3000)
        app.workers.update_list()
        app.stats_refresh()


# --------------------------------------------------------------------------- #
#  InputHandler                                                                 #
# --------------------------------------------------------------------------- #
class InputHandler:
    """Фокус-менеджмент и разбор отсканированного кода."""

    def __init__(self, app: "Application") -> None:
        self.app = app

    def on_click(self, event) -> None:
        app = self.app
        if (app.entry is not None and app.entry.winfo_exists()
                and event.widget is not app.entry):
            app.entry.focus_set()

    def on_focus_out(self, event) -> None:
        app = self.app
        if app.entry is not None and app.entry.winfo_exists():
            app.root.after(10, app.entry.focus_set)

    def on_scan(self, event) -> None:
        app = self.app
        if app.entry is None:
            return
        code = app.entry.get().strip()
        app.entry.delete(0, tk.END)
        if not code:
            app.entry.focus_set()
            return

        if not app.holder.is_connected:      # до подключения — только выкл. ПК
            if code == config.CODE_POWEROFF:
                app.shutdown()
            else:
                app.notifier.show_auto_message("Нет подключения к БД.",
                                               "Ожидание", 3000,
                                               msg_type="error")
                app.entry.focus_set()
            return

        if code == config.CODE_POWEROFF:
            app.workers.close_all()
            app.shutdown()
        elif code.startswith(config.PREFIX_WORKER):
            app.workers.process(int(code))
        else:
            app.detals.process(code)
        app.entry.focus_set()


# --------------------------------------------------------------------------- #
#  Application                                                                  #
# --------------------------------------------------------------------------- #
class _Abort(Exception):
    """Внутренний сигнал «прервать транзакцию и сообщить оператору»."""

    def __init__(self, message: str, level: str = "error") -> None:
        super().__init__(message)
        self.level = level


class Application:
    """Главное окно; собирает менеджеры и панели."""

    WINDOW_GEOMETRY = "1920x1080+0+0"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Учёт рабочего времени и деталей")
        root.geometry(self.WINDOW_GEOMETRY)

        self.entry: Optional[tk.Entry] = None
        self.current_ip: int = int(config.MY_IP or 0)
        self.workplace_name: str = ""
        self.gr: Optional[int] = None
        self.holder = ConnectionHolder()

        log_message("=== Запуск программы ===")
        log_message(f"Определён IP: {self.current_ip}")

        # Порядок важен: input нужен в диалоге подключения до построения UI.
        self.notifier = Notifier(root, restore_focus=self.focus_entry)
        self.input = InputHandler(self)
        self.workers = WorkerSessionManager(self)
        self.detals = DetalProcessor(self)
        self.connection = ConnectionManager(self)

        root.bind("<Button-1>", self.input.on_click)
        root.bind("<FocusOut>", self.input.on_focus_out)

        self.connection.show_dialog()
        self.connection.attempt()

    # -- построение главного окна после подключения ----------------------------
    def build_ui(self) -> None:
        info = dbm.get_workplace_info(self.holder, self.current_ip)
        if info is None:
            self.notify(f"Рабочее место с IP {self.current_ip} не найдено "
                        f"в БД.", level="error", timeout=10000)
            self.root.after(10000, self._exit_without_shutdown)
            return
        self.workplace_name, self.gr = info.name, info.gr
        log_message(f"Рабочее место: {info.name}, GR={info.gr}, "
                    f"RAB_MAX={info.rab_max}, RAB_CUR={info.rab_cur}")
        log_message(f"Разрешённые группы: "
                    f"{get_policy(info.gr).allowed_names}")

        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        right = ttk.Frame(paned)
        paned.add(right, weight=3)

        top = tk.Frame(left)
        top.pack(pady=5, fill=tk.X)
        self.header = WorkplaceHeader(top, info.name, info.rab_max,
                                      info.rab_cur)
        self.header.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.detal_panel = DetalInfoPanel(left)
        self.detal_panel.pack(fill=tk.X, padx=10, pady=5)

        self.stats_view = StatsPanel(left)
        self.stats_view.pack(fill=tk.X, padx=10, pady=5)

        self.workers_tree = WorkersTree(left)
        self.workers_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        bottom = tk.Frame(left)
        bottom.pack(pady=10, fill=tk.X)
        self.entry = tk.Entry(bottom, font=font3, width=25)
        self.entry.pack(side=tk.RIGHT, padx=10)
        self.entry.bind("<Return>", self.input.on_scan)
        tk.Label(bottom, text="Штрих-код:", font=font4) \
            .pack(side=tk.RIGHT, padx=10)
        self.entry.focus_set()

        self.images = ImageDisplay(right)
        self.images.pack(expand=True, fill=tk.BOTH)

        # Первичная загрузка
        self.workers.close_previous()
        self.workers.update_list()
        self.workers.auto_update()
        self.detal_panel.clear()
        self.stats_refresh()
        self.images.show_default()

    # -- вспомогательное ----------------------------------------------------------
    def notify(self, message: str, level: str = "info",
               title: Optional[str] = None, timeout: int = 5000) -> None:
        self.notifier.notify(message, level=level, title=title,
                             timeout=timeout)

    def focus_entry(self) -> None:
        if self.entry is not None and self.entry.winfo_exists():
            self.entry.focus_set()

    def stats_refresh(self) -> None:
        try:
            stats = dbm.get_stats_for_shift(self.holder, self.current_ip)
            self.stats_view.set(stats)
            self.focus_entry()
        except Exception as e:
            self.notify(f"Ошибка получения статистики: {e}", level="error")

    def _exit_without_shutdown(self) -> None:
        self.holder.close()
        self.root.destroy()

    def shutdown(self) -> None:
        """Завершение: закрыть БД и выключить компьютер."""
        log_message("=== Завершение программы ===")
        self.holder.close()
        rc = os.system(config.power_off)
        log_message(f"Команда выключения вернула код {rc}")
        self.root.destroy()


if __name__ == "__main__":
    from main import main
    sys.exit(main())
