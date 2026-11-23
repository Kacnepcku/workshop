#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import tkinter as tk
from tkinter import ttk

from config import AppConfig, FONTS
from database.connection import Database
from models import Workplace, ActionResult
from services.worker_service import WorkerService
from services.detal_service import DetalService, DetalDisplayData
from ui.dialogs import ConnectionDialog, show_auto_popup
from ui.widgets import (
    DetalInfoPanel,
    StatsPanel,
    WorkersTablePanel,
    StatusIndicator,
    ImageViewerPanel,
)
from log import log_message, init_log


class Application:
    """Главное окно и тонкий координатор между UI и сервисами."""

    def __init__(
        self,
        root: tk.Tk,
        cfg: AppConfig,
        db: Database,
        worker_service: WorkerService,
        detal_service: DetalService,
    ):
        self.root = root
        self.cfg = cfg
        self.db = db
        self.worker_service = worker_service
        self.detal_service = detal_service

        self.workplace: Optional[Workplace] = None
        self.entry: Optional[tk.Entry] = None
        self.conn_dialog: Optional[ConnectionDialog] = None
        self._health_executor = ThreadPoolExecutor(max_workers=1)

        # Виджеты (инициализируются после подключения к БД)
        self.info_label: Optional[tk.Label] = None
        self.detal_panel: Optional[DetalInfoPanel] = None
        self.stats_panel: Optional[StatsPanel] = None
        self.workers_table: Optional[WorkersTablePanel] = None
        self.status_indicator: Optional[StatusIndicator] = None
        self.image_viewer: Optional[ImageViewerPanel] = None

        self.root.title("Учёт рабочего времени и деталей")
        self.root.geometry("1920x1080+0+0")
        self.root.bind("<Button-1>", self._on_window_click)
        self.root.bind("<FocusOut>", self._on_focus_out)

        log_message("=== Запуск программы ===")
        log_message(f"Определён IP: {self.cfg.my_ip}")

        self.conn_dialog = ConnectionDialog(self.root, on_scan_callback=self._on_pre_connect_scan)
        self._attempt_initial_connection()

    # === Подключение к БД при старте =========================================

    def _on_pre_connect_scan(self, code: str) -> None:
        if code == self.cfg.code_poweroff:
            self.shutdown_system()

    def _attempt_initial_connection(self) -> None:
        if not self.db.is_port_open(timeout=0.5):
            log_message(
                f"БД ({self.cfg.db_host}:{self.cfg.db_port}) недоступна, "
                f"повтор через {self.cfg.reconnect_ms // 1000} сек."
            )
            if self.conn_dialog:
                self.conn_dialog.set_status(f"Нет связи с БД ({self.cfg.db_host})...")
            self.root.after(self.cfg.reconnect_ms, self._attempt_initial_connection)
            return

        if not self.db.ensure_connected():
            self.root.after(self.cfg.reconnect_ms, self._attempt_initial_connection)
            return

        if self.conn_dialog:
            self.conn_dialog.destroy()
            self.conn_dialog = None

        self._init_workplace_and_ui()

    def _init_workplace_and_ui(self) -> None:
        try:
            self.workplace = self.worker_service.get_workplace(self.cfg.my_ip)
        except Exception as e:
            self._notify(f"Ошибка загрузки рабочего места: {e}", level="error")
            sys.exit(1)

        if not self.workplace:
            init_log(f"IP_{self.cfg.my_ip}", self.cfg.my_ip)
            self._notify(f"Рабочее место с IP {self.cfg.my_ip} не найдено в БД.", level="error")
            sys.exit(1)

        init_log(self.workplace.name, self.cfg.my_ip)
        log_message(
            f"Рабочее место: {self.workplace.name}, GR={self.workplace.gr}, "
            f"RAB_MAX={self.workplace.rab_max}"
        )

        self._build_main_ui()
        self._start_background_loops()

    # === Построение интерфейса ===============================================

    def _build_main_ui(self) -> None:
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=1)

        self.image_viewer = ImageViewerPanel(paned, self.cfg.image_folder)
        paned.add(self.image_viewer, weight=3)

        # Верхняя строка: название места и счётчик сотрудников
        top_panel = tk.Frame(left_frame)
        top_panel.pack(pady=5, fill=tk.X)

        tk.Label(
            top_panel, text=self.workplace.name, font=FONTS["title"], fg="blue"
        ).pack(side=tk.LEFT, padx=20)

        self.info_label = tk.Label(
            top_panel,
            text=f"Максимум сотрудников: {self.workplace.rab_max} | Занято: 0",
            font=FONTS["f4"],
        )
        self.info_label.pack(side=tk.RIGHT, padx=20)

        # Основные панели
        self.detal_panel = DetalInfoPanel(left_frame)
        self.detal_panel.pack(fill=tk.X, padx=10, pady=5)

        self.stats_panel = StatsPanel(left_frame)
        self.stats_panel.pack(fill=tk.X, padx=10, pady=5)

        self.workers_table = WorkersTablePanel(left_frame)
        self.workers_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Нижняя панель: статус, версия, поле сканера
        bottom_frame = tk.Frame(left_frame)
        bottom_frame.pack(pady=10, fill=tk.X)

        self.status_indicator = StatusIndicator(bottom_frame)
        self.status_indicator.pack(side=tk.LEFT, padx=(10, 6))

        tk.Label(
            bottom_frame, text=self.cfg.app_version, font=FONTS["f4"], fg="gray35"
        ).pack(side=tk.LEFT, padx=(0, 10))

        self.entry = tk.Entry(bottom_frame, font=FONTS["f3"], width=25)
        self.entry.pack(side=tk.RIGHT, padx=10)
        self.entry.bind("<Return>", self._on_scan)
        self.entry.focus_set()

        tk.Label(bottom_frame, text="Штрих-код:", font=FONTS["f4"]).pack(side=tk.RIGHT, padx=10)

    def _start_background_loops(self) -> None:
        self.worker_service.close_stale_sessions(ip=self.workplace.ip, silent=False)
        self._refresh_dashboard()
        self.image_viewer.show_default()

        self._loop_auto_update()
        self._loop_idle_check()
        self._loop_health_check()

    # === Обработка ввода и фокуса ============================================

    def _focus_entry(self) -> None:
        if self.entry is not None and self.entry.winfo_exists():
            self.entry.focus_set()

    def _on_window_click(self, event) -> None:
        if self.entry is not None and event.widget != self.entry:
            self._focus_entry()

    def _on_focus_out(self, _event) -> None:
        self.root.after(10, self._focus_entry)

    def _on_scan(self, _event) -> None:
        if self.entry is None:
            return
        code = self.entry.get().strip()
        self.entry.delete(0, tk.END)
        if not code:
            self._focus_entry()
            return

        if code == self.cfg.code_poweroff:
            self.worker_service.close_all_on_workplace(self.workplace)
            self.shutdown_system()
            return

        if code.startswith(self.cfg.prefix_worker):
            result = self.worker_service.handle_worker_scan(code, self.workplace)
            self._apply_action_result(result, refresh_workers=True)
        else:
            result = self.detal_service.handle_detal_scan(code, self.workplace)
            self._apply_action_result(result, refresh_workers=result.success, refresh_stats=result.success)

        self._focus_entry()

    def _apply_action_result(
        self,
        result: ActionResult,
        refresh_workers: bool = False,
        refresh_stats: bool = False,
    ) -> None:
        if isinstance(result.payload, DetalDisplayData):
            data = result.payload
            self.detal_panel.show_detal(data.detal, data.dims, data.override_type)
            self.image_viewer.show_construction(data.detal.zaknum, data.detal.konid)
        elif not result.success and result.payload is None:
            self.detal_panel.clear()

        if refresh_workers or refresh_stats:
            self._refresh_dashboard()

        self._notify(result.message, level=result.level, timeout_ms=result.timeout_ms)

    def _refresh_dashboard(self) -> None:
        try:
            workers, occupied = self.worker_service.get_dashboard_data(self.workplace.ip)
            self.workers_table.update_workers(workers)
            self.info_label.config(
                text=f"Максимум сотрудников: {self.workplace.rab_max} | Занято: {occupied}"
            )

            stats = self.detal_service.get_shift_stats(self.workplace.ip)
            self.stats_panel.update_stats(stats)
        except Exception as e:
            log_message(f"Ошибка обновления панели: {e}")

    # === Фоновые циклы =======================================================

    def _loop_auto_update(self) -> None:
        if self.db.ensure_connected():
            self.worker_service.close_stale_sessions(ip=self.workplace.ip, silent=True)
            self._refresh_dashboard()
        self.root.after(self.cfg.auto_update_ms, self._loop_auto_update)

    def _loop_idle_check(self) -> None:
        if self.worker_service.check_idle_and_close_if_needed(self.workplace.ip):
            self._refresh_dashboard()
            self.shutdown_system()
            return
        self.root.after(self.cfg.idle_check_ms, self._loop_idle_check)

    def _loop_health_check(self) -> None:
        """Проверка сети и SMB в фоновом потоке без блокировки GUI."""
        def _probe():
            db_ok = self.db.is_port_open(timeout=0.4)
            if db_ok:
                self.db.ensure_connected()
            else:
                self.db.drop()

            try:
                img_ok = os.path.isdir(self.cfg.image_folder)
            except Exception:
                img_ok = False
            return db_ok, img_ok

        def _on_done(future):
            if not self.root.winfo_exists():
                return
            db_ok, img_ok = future.result()
            self.root.after(0, lambda: self._update_health_ui(db_ok, img_ok))

        future = self._health_executor.submit(_probe)
        future.add_done_callback(_on_done)

    def _update_health_ui(self, db_ok: bool, img_ok: bool) -> None:
        if self.status_indicator and self.status_indicator.winfo_exists():
            self.status_indicator.set_state(db_ok, img_ok)
        self.root.after(self.cfg.reconnect_ms, self._loop_health_check)

    # === Уведомления и выключение ============================================

    def _notify(self, message: str, level: str = "info", timeout_ms: int = 5000) -> None:
        prefix = {"info": "", "error": "ОШИБКА", "warn": "ПРЕДУПРЕЖДЕНИЕ"}.get(level, "")
        log_message(f"{prefix}: {message}" if prefix else message)
        show_auto_popup(
            self.root,
            message=message,
            level=level,
            timeout_ms=timeout_ms,
            on_close=self._focus_entry,
        )

    def shutdown_system(self) -> None:
        log_message("=== Завершение программы ===")
        self._health_executor.shutdown(wait=False)
        if self.image_viewer:
            self.image_viewer.shutdown()
        self.db.close()
        os.system(self.cfg.power_off_cmd)
        self.root.destroy()
