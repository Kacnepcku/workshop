#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

"""
Класс Application — тонкий координатор. Вся работа разнесена по менеджерам:

    Notifier              — логирование и всплывающие сообщения
    ConnectionManager     — подключение к БД (диалог + повторные попытки)
    UIBuilder             — построение главного окна и панелей
    StatsPanel            — блок статистики за смену
    ImageDisplay          — показ изображений (по умолчанию и по детали)
    WorkerSessionManager  — сессии сотрудников (старт/стоп/перемещение)
    DetalProcessor        — регистрация деталей и изделий
    InputHandler          — обработка сканера (ввод, фокус, клики)
"""

import os
import sys
import pymysql
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageFile
from main import (
    font0, font1, font2, font3, font4,
    font1b, font2b, font3b, font4b,
    DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_CHARSET,
    image_folder, power_off, MY_IP,
    CODE_POWEROFF, PREFIX_WORKER,
    GRI_IMPOST, GRI_FRAME, GRI_SASH,
    AUTO_UPDATE_MS, RECONNECT_MS,
    log_message,
)
import db as dbm

# Разрешаем загрузку обрезанных JPEG
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Notifier — уведомления ==========================================================================
class Notifier:
    """Пишет сообщения в лог и/или показывает всплывающее окно."""

    def __init__(self, app):
        self.app = app

    def notify(self, message, level='info', title=None, timeout=5000):
        """
        Универсальный вывод: пишет в лог и показывает окно.
        level: 'info' | 'error' | 'warn'.
        """
        prefix = {'info': '', 'error': 'ОШИБКА', 'warn': 'ПРЕДУПРЕЖДЕНИЕ'}[level]
        log_message(f"{prefix}: {message}" if prefix else message)

        if title is None:
            title = {'info': 'Информация',
                     'error': 'Ошибка',
                     'warn': 'Предупреждение'}[level]
        msg_type = 'error' if level in ('error', 'warn') else 'info'
        self.show_auto_message(message, title, timeout, msg_type=msg_type)

    def show_auto_message(self, message, title="Информация",
                          timeout=5000, msg_type='info'):
        """
        Всплывающее окно с сообщением на заданное время.
        msg_type: 'info' или 'error' (меняет цвет рамки).
        """
        app = self.app
        win = tk.Toplevel(app.root)
        win.title(title)
        win_width, win_height = 600, 200
        screen_width  = win.winfo_screenwidth()
        screen_height = win.winfo_screenheight()
        x = (screen_width - win_width) // 2
        y = (screen_height - win_height) // 2
        win.geometry(f"{win_width}x{win_height}+{x}+{y}")
        win.resizable(False, False)
        win.transient(app.root)
        win.grab_set()

        border_color = "red" if msg_type == 'error' else "green"
        frame = tk.Frame(win, bd=5, relief='flat',
                         highlightbackground=border_color,
                         highlightcolor=border_color,
                         highlightthickness=5)
        frame.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        lbl = tk.Label(frame, text=message, font=font1b,
                       justify='center', wraplength=550)
        lbl.pack(expand=True, padx=10, pady=10)

        # Закрыть окно по таймауту и вернуть фокус на поле ввода
        def _close():
            win.destroy()
            if app.entry is not None and app.entry.winfo_exists():
                app.entry.focus_set()

        win.after(timeout, _close)

# ConnectionManager — подключение к БД ============================================================
class ConnectionManager:
    """Модальное окно подключения и циклические попытки соединиться."""

    def __init__(self, app):
        self.app = app
        self.dialog = None
        self.conn_label = None

    def show_connection_dialog(self):
        """
        Модальное окно с полем ввода для сканера и статусом подключения.
        Позволяет отсканировать 12345 для выключения ПК ещё до подключения.
        """
        app = self.app
        dialog = tk.Toplevel(app.root)
        dialog.title("Подключение к базе данных")
        dialog.geometry("600x250")
        dialog.transient(app.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 600) // 2
        y = (dialog.winfo_screenheight() - 250) // 2
        dialog.geometry(f"+{x}+{y}")

        frame = tk.Frame(dialog, bd=0, relief='flat')
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.conn_label = tk.Label(frame, text="Подключение к БД",
                                   font=font1, justify='center')
        self.conn_label.pack(pady=10)

        # Поле ввода для сканера
        app.entry = tk.Entry(frame, font=font1, width=15)
        app.entry.pack(pady=10)
        app.entry.bind("<Return>", app.input.on_scan)
        app.entry.focus_set()

        self.dialog = dialog
        return dialog

    def attempt_connection(self):
        """
        Пытается подключиться к БД; при ошибке повторяет через RECONNECT_MS.
        Текст ошибки пишется только в лог, окно не изменяется.
        """
        app = self.app
        try:
            app.conn = pymysql.connect(
                host=DB_HOST,
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME,
                charset=DB_CHARSET,
                autocommit=False,
            )
            app.cursor = app.conn.cursor()
            log_message("Подключение к БД успешно")

            # Закрываем диалог подключения
            if self.dialog:
                self.dialog.destroy()
                self.dialog = None

            # Ссылка на старое поле ввода недействительна — сбрасываем.
            # Новый entry будет создан в UIBuilder._create_input_panel.
            app.entry = None

            app.ui.build()
        except Exception as e:
            log_message(f"Ошибка подключения к БД: {e}")
            app.root.after(RECONNECT_MS, self.attempt_connection)

# UIBuilder — построение главного окна ============================================================
class UIBuilder:
    """Собирает все виджеты главного окна после успешного подключения к БД."""

    def __init__(self, app):
        self.app = app

    # Публичная точка входа ---------------------------------------------------
    def build(self):
        """Собирает всё главное окно."""
        self._load_workplace_info()
        self._create_main_panes()
        self._create_left_panel()
        self._create_workers_tree()
        self._create_input_panel()
        self._create_image_panel()
        self._initial_data_load()

    # Приватные методы --------------------------------------------------------
    def _load_workplace_info(self):
        """Получает информацию о рабочем месте и определяет разрешённые группы."""
        app = self.app
        workplace = dbm.get_workplace_info(app.cursor, app.current_ip)
        if not workplace:
            app.notify(f"Рабочее место с IP {app.current_ip} не найдено в БД.",
                       level='error')
            sys.exit(1)

        app.workplace_name, app.rab_max, app.rab_cur, app.gr = workplace
        log_message(f"Рабочее место: {app.workplace_name}, GR={app.gr}, "
                    f"RAB_MAX={app.rab_max}, RAB_CUR={app.rab_cur}")

        # Разрешённые группы деталей для данного рабочего места
        app.allowed_gri = {
            1: [GRI_FRAME], 2: [GRI_FRAME],
            3: [GRI_SASH],  4: [GRI_SASH],
            5: [GRI_FRAME, GRI_SASH],
            6: [GRI_FRAME, GRI_SASH],
        }.get(app.gr, [])

        group_names = {GRI_FRAME: 'РАМЫ', GRI_SASH: 'СТВОРКИ'}
        if not app.allowed_gri:
            allowed_desc = "не разрешена регистрация деталей"
        elif len(app.allowed_gri) == 1:
            allowed_desc = f"разрешена только {group_names[app.allowed_gri[0]]}"
        else:
            allowed_desc = "разрешены РАМЫ и СТВОРКИ"
        log_message(f"Разрешённые группы: {allowed_desc}")

    def _create_main_panes(self):
        """Создаёт разделитель (paned) и два основных фрейма: левый и правый."""
        app = self.app
        app.paned = ttk.PanedWindow(app.root, orient=tk.HORIZONTAL)
        app.paned.pack(fill=tk.BOTH, expand=True)

        app.left_frame = ttk.Frame(app.paned)
        app.paned.add(app.left_frame, weight=1)

        app.right_frame = ttk.Frame(app.paned)
        app.paned.add(app.right_frame, weight=3)

    def _create_left_panel(self):
        """Создаёт верхнюю панель, блоки информации о детали и статистики."""
        app = self.app

        # Верхняя панель: название рабочего места + счётчик сотрудников
        top_panel = tk.Frame(app.left_frame)
        top_panel.pack(pady=5, fill=tk.X)

        app.label_place = tk.Label(top_panel, text=app.workplace_name,
                                   font=font0, fg="blue")
        app.label_place.pack(side=tk.LEFT, padx=20)

        app.info_label = tk.Label(
            top_panel,
            text=f"Максимум сотрудников: {app.rab_max} | Занято: {app.rab_cur}",
            font=font4
        )
        app.info_label.pack(side=tk.RIGHT, padx=20)

        # Блок информации о детали (5 строк)
        app.detal_frame = ttk.LabelFrame(app.left_frame,
                                         text="Информация о детали / изделии",
                                         padding=10)
        app.detal_frame.pack(fill=tk.X, padx=10, pady=5)

        app.info_line1 = tk.Label(app.detal_frame, text="", font=font1b, fg="darkblue", anchor='w')
        app.info_line2 = tk.Label(app.detal_frame, text="", font=font1b, fg="darkblue", anchor='w')
        app.info_line3 = tk.Label(app.detal_frame, text="", font=font4b, fg="darkblue", anchor='w')
        app.info_line4 = tk.Label(app.detal_frame, text="", font=font2b, fg="green",    anchor='w')
        app.info_line5 = tk.Label(app.detal_frame, text="", font=font2b, fg="darkred",  anchor='w')

        for line in (app.info_line1, app.info_line2, app.info_line3,
                     app.info_line4, app.info_line5):
            line.pack(fill=tk.X, padx=10, pady=2, anchor='w')

        # Блок статистики за смену
        app.stats_frame = ttk.LabelFrame(app.left_frame,
                                         text="Статистика за смену",
                                         padding=10)
        app.stats_frame.pack(fill=tk.X, padx=10, pady=5)

        app.stats_line1 = tk.Label(app.stats_frame,
                                   text="Количество изделий: 0",
                                   font=font1, anchor='w')
        app.stats_line2 = tk.Label(app.stats_frame,
                                   text="Суммарный периметр: 0.000 м",
                                   font=font1, anchor='w')
        app.stats_line3 = tk.Label(app.stats_frame,
                                   text="Суммарная площадь: 0.000 м²",
                                   font=font1, anchor='w')

        for line in (app.stats_line1, app.stats_line2, app.stats_line3):
            line.pack(fill=tk.X, padx=10, pady=2, anchor='w')

    def _create_workers_tree(self):
        """Создаёт таблицу сотрудников на рабочем месте."""
        app = self.app
        app.workers_frame = ttk.LabelFrame(app.left_frame,
                                           text="Сотрудники на рабочем месте",
                                           padding=5)
        app.workers_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        style = ttk.Style()
        style.configure("Treeview", font=font3, rowheight=30)
        style.configure("Treeview.Heading", font=font4)

        tree_frame = tk.Frame(app.workers_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        app.tree_workers = ttk.Treeview(
            tree_frame,
            columns=("num", "fio", "start", "total"),
            show="headings",
            height=6
        )
        app.tree_workers.heading("num",   text="№")
        app.tree_workers.heading("fio",   text="ФИО")
        app.tree_workers.heading("start", text="Начало")
        app.tree_workers.heading("total", text="Всего")
        app.tree_workers.column("num",   width=30,  anchor="center")
        app.tree_workers.column("fio",   width=250, anchor="w")
        app.tree_workers.column("start", width=60,  anchor="center")
        app.tree_workers.column("total", width=60,  anchor="center")
        app.tree_workers.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                                  command=app.tree_workers.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        app.tree_workers.config(yscrollcommand=scrollbar.set)

    def _create_input_panel(self):
        """Создаёт нижнюю панель с полем ввода для сканера (по правому краю)."""
        app = self.app
        bottom_frame = tk.Frame(app.left_frame)
        bottom_frame.pack(pady=10, fill=tk.X)

        # Сначала entry — он будет у самого правого края
        app.entry = tk.Entry(bottom_frame, font=font3, width=25)
        app.entry.pack(side=tk.RIGHT, padx=10)
        app.entry.bind("<Return>", app.input.on_scan)
        app.entry.focus_set()

        # Затем label — он встанет левее entry
        app.entry_label = tk.Label(bottom_frame, text="Штрих-код:", font=font4)
        app.entry_label.pack(side=tk.RIGHT, padx=10)

    def _create_image_panel(self):
        """Создаёт правую часть — контейнер для отображения изображений."""
        app = self.app
        bg_color = app.root.cget('bg')
        app.image_label = tk.Label(app.right_frame, bg=bg_color)
        app.image_label.pack(expand=True, fill=tk.BOTH)
        app.right_frame.bind('<Configure>', app.images.on_resize)

    def _initial_data_load(self):
        """Первичная загрузка данных: сессии, список, статистика, картинка."""
        app = self.app
        app.current_image_path = None
        app.workers.close_previous()
        app.workers.update_list()
        app.workers.auto_update()
        self.clear_detal_info()
        app.stats.update()
        app.images.show_default()

    # Публичные методы работы с информацией о детали -------------------------
    def clear_detal_info(self):
        """Очищает поля информации о детали."""
        app = self.app
        for line in (app.info_line1, app.info_line2, app.info_line3,
                     app.info_line4, app.info_line5):
            line.config(text="")

    def set_detal_info(self, detal_info, width_mm, height_mm,
                       perimeter_m, area_m2, override_type=None):
        """Заполняет поля информации о детали переданными данными."""
        app = self.app

        line1 = (f"{detal_info.get('zaknum', '')}  "
                 f"{detal_info.get('konname', '')}  "
                 f"{detal_info.get('matcolor', '')}")
        length = detal_info.get('length', 0)
        length_minus_6 = length - 6 if length is not None else 0
        line2 = f"{detal_info.get('matname', '')}  {length_minus_6}"
        line3 = detal_info.get('primproizv', '')

        if override_type:
            type_text = override_type
        else:
            gri = detal_info.get('gri', '')
            if gri == GRI_FRAME:
                type_text = "Тип: РАМА"
            elif gri == GRI_SASH:
                type_text = "Тип: СТВОРКА"
            elif gri == GRI_IMPOST:
                type_text = "Тип: ИМПОСТ"
            else:
                type_text = f"Тип: {gri}"

        if width_mm is not None and height_mm is not None:
            w_m = (width_mm - 6) / 1000.0
            h_m = (height_mm - 6) / 1000.0
            dims_text = (f"Шир: {w_m:.3f} м  Выс: {h_m:.3f} м  "
                         f"Пр: {perimeter_m:.3f} м  Пл: {area_m2:.3f} м²")
        else:
            dims_text = "Габариты: данные отсутствуют (нет ORIENT='Н' или 'П')"

        app.info_line1.config(text=line1)
        app.info_line2.config(text=line2)
        app.info_line3.config(text=line3)
        app.info_line4.config(text=type_text)
        app.info_line5.config(text=dims_text)

# StatsPanel — статистика за смену ===============================================================
class StatsPanel:
    """Блок статистики: количество изделий, суммарные периметр и площадь."""

    def __init__(self, app):
        self.app = app

    def update(self):
        """Обновляет статистику за смену."""
        app = self.app
        try:
            count, total_perimeter, total_area = dbm.get_stats_for_shift(
                app.cursor, app.current_ip
            )
            app.stats_line1.config(text=f"Количество изделий: {count}")
            app.stats_line2.config(text=f"Суммарный периметр: {total_perimeter:.3f} м")
            app.stats_line3.config(text=f"Суммарная площадь: {total_area:.3f} м²")
            app.entry.focus_set()
        except Exception as e:
            app.notify(f"Ошибка получения статистики: {e}", level='error')

# ImageDisplay — отображение изображений =========================================================
class ImageDisplay:
    """Загрузка, обрезка и показ изображений в правой панели."""

    def __init__(self, app):
        self.app = app

    def show_default(self):
        """Загружает и отображает стандартное изображение ROSHAN.png."""
        app = self.app
        default_path = os.path.join(image_folder, "ROSHAN.png")
        if os.path.exists(default_path):
            try:
                img = Image.open(default_path)
                img.load()
                app.current_image_path = default_path
                self.display(img)
                log_message("Отображено стандартное изображение ROSHAN.png")
            except Exception as e:
                log_message(f"Ошибка загрузки стандартного изображения: {e}")
                app.image_label.config(image='', text='')
                app.image_label.image = None
        else:
            app.image_label.config(image='', text='')
            app.image_label.image = None
            log_message("Стандартное изображение ROSHAN.png не найдено")

    def update(self, zaknum, konid):
        """Загружает и отображает изображение конструкции."""
        app = self.app
        app.current_image_path = None
        filename = f"{zaknum} ({konid}).jpg"
        filepath = os.path.join(image_folder, filename)
        if not os.path.exists(filepath):
            self.show_default()
            log_message(f"Файл изображения не найден: {filepath}")
            return

        try:
            img = Image.open(filepath)
            img.load()
            app.current_image_path = filepath
            self.display(img)
        except Exception as e:
            log_message(f"Ошибка открытия {filepath}: {e}")
            self.show_default()

    def display(self, img):
        """Масштабирует изображение под размер правого фрейма и отображает."""
        if img is None:
            return

        app = self.app

        # Обрезка на 40 пикселей со всех сторон
        width, height = img.size
        if width > 80 and height > 80:
            img = img.crop((40, 40, width - 40, height - 40))

        fw = app.right_frame.winfo_width()
        fh = app.right_frame.winfo_height()
        if fw < 20 or fh < 20:
            fw, fh = 400, 300

        padding = 5
        display_width  = fw - 2 * padding
        display_height = fh - 2 * padding
        if display_width < 50 or display_height < 50:
            display_width  = fw - 10
            display_height = fh - 10

        img.thumbnail((display_width, display_height), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        app.image_label.config(image=photo, text='')
        app.image_label.image = photo

    def on_resize(self, event):
        """При изменении размера правой панели перерисовываем изображение."""
        app = self.app
        if app.current_image_path is None:
            return
        try:
            img = Image.open(app.current_image_path)
            img.load()
            self.display(img)
        except Exception:
            pass

# WorkerSessionManager — сессии сотрудников ======================================================
class WorkerSessionManager:
    """Регистрация, перемещение, завершение сессий сотрудников."""

    def __init__(self, app):
        self.app = app

    # Публичные точки входа ---------------------------------------------------
    def process(self, rab):
        """
        Точка входа: обрабатывает сканирование сотрудника (префикс 2200).
        Регистрирует начало/окончание работы, перемещение между рабочими местами.
        """
        app = self.app
        try:
            fio = dbm.get_worker_fio(app.cursor, rab)
            if fio is None:
                app.notify(f"Работник с кодом {rab} не найден в базе.",
                           level='error')
                app.conn.rollback()
                return

            open_session = dbm.get_open_session(app.cursor, rab)
            if open_session:
                old_ip, _ = open_session
                if old_ip == app.current_ip:
                    self._stop_worker(rab, fio)
                else:
                    self._move_worker(rab, fio, old_ip)
            else:
                self._register_worker(rab, fio)

            self.update_list()
        except Exception as e:
            app.conn.rollback()
            app.notify(f"Ошибка обработки сотрудника: {e}", level='error')

    def close_previous(self):
        """
        Закрывает зависшие сессии сотрудников за предыдущие дни
        (TIME_END_W = 18:00 дня открытия).
        """
        app = self.app
        try:
            app.cursor.execute(
                "SELECT RAB, IP, TIME_START_W FROM WORKER_TIME "
                "WHERE TIME_END_W IS NULL AND DATE(TIME_START_W) < CURDATE()"
            )
            sessions = app.cursor.fetchall()
            if not sessions:
                log_message("Нет зависших сессий сотрудников за предыдущие дни.")
                return

            count = 0
            for rab, ip, start_time in sessions:
                close_time = start_time.replace(hour=18, minute=0, second=0,
                                                microsecond=0)
                if start_time > close_time:
                    close_time = start_time
                app.cursor.execute(
                    "UPDATE WORKER_TIME SET TIME_END_W = %s "
                    "WHERE RAB = %s AND IP = %s AND TIME_END_W IS NULL",
                    (close_time, rab, ip)
                )
                dbm.decrement_workplace_cur(app.cursor, ip)
                count += 1
                log_message(f"Закрыта сессия сотрудника {rab} на IP {ip} "
                            f"(время окончания {close_time})")

            app.conn.commit()
            if count > 0:
                app.notify(f"Закрыто {count} сессий сотрудников за предыдущие "
                           f"дни (в 18:00 дня открытия).")
            else:
                app.entry.focus_set()
        except Exception as e:
            app.conn.rollback()
            app.notify(f"Не удалось закрыть предыдущие сессии сотрудников: {e}",
                       level='error')

    def close_all(self):
        """Закрывает все открытые сессии на текущем рабочем месте."""
        app = self.app
        try:
            app.cursor.execute(
                "SELECT RAB FROM WORKER_TIME "
                "WHERE IP = %s AND TIME_END_W IS NULL",
                (app.current_ip,)
            )
            sessions = app.cursor.fetchall()
            if not sessions:
                log_message("Нет открытых сессий на данном рабочем месте.")
                return

            count = 0
            for (rab,) in sessions:
                dbm.close_session(app.cursor, rab)
                if not dbm.decrement_workplace_cur(app.cursor, app.current_ip):
                    log_message(f"Не удалось уменьшить RAB_CUR для сотрудника {rab}")
                count += 1
                log_message(f"Закрыта сессия сотрудника {rab} на IP "
                            f"{app.current_ip} (время закрытия NOW())")
            app.conn.commit()
            log_message(f"Закрыто {count} сессий на рабочем месте "
                        f"{app.workplace_name}")
            self.update_list()
        except Exception as e:
            app.conn.rollback()
            app.notify(f"Ошибка закрытия сессий: {e}", level='error')

    def update_list(self):
        """Обновляет таблицу сотрудников на рабочем месте."""
        app = self.app
        for item in app.tree_workers.get_children():
            app.tree_workers.delete(item)

        try:
            workers = dbm.get_current_workers(app.cursor, app.current_ip)
            for idx, (rab, fio, start_time, total_sec) in enumerate(workers, start=1):
                start_str = start_time.strftime("%H:%M") if start_time else "--:--"
                hours   = total_sec // 3600
                minutes = (total_sec % 3600) // 60
                time_str = f"{hours}ч {minutes}м" if hours > 0 else f"{minutes}м"
                app.tree_workers.insert("", "end",
                                        values=(idx, fio, start_str, time_str))

            info = dbm.get_workplace_info(app.cursor, app.current_ip)
            if info:
                _, _, cur, _ = info
                app.rab_cur = cur
                app.info_label.config(
                    text=f"Максимум сотрудников: {app.rab_max} | "
                         f"Занято: {app.rab_cur}"
                )
            app.entry.focus_set()
        except Exception as e:
            app.notify(f"Не удалось обновить список сотрудников: {e}",
                       level='error')

    def auto_update(self):
        """Автоматическое обновление списка сотрудников раз в минуту."""
        self.update_list()
        self.app.root.after(AUTO_UPDATE_MS, self.auto_update)

    # Приватные методы --------------------------------------------------------
    def _stop_worker(self, rab, fio):
        """Закрывает сессию сотрудника на текущем рабочем месте."""
        app = self.app
        dbm.close_session(app.cursor, rab)
        if not dbm.decrement_workplace_cur(app.cursor, app.current_ip):
            app.conn.rollback()
            app.notify(f"Счётчик RAB_CUR на месте {app.workplace_name} "
                       f"уже равен 0. Операция отменена.", level='error')
            return
        app.conn.commit()
        app.notify(f"Работник {fio} завершил работу на {app.workplace_name}.")

    def _move_worker(self, rab, fio, old_ip):
        """Перемещает сотрудника с другого рабочего места на текущее."""
        app = self.app
        info = dbm.get_workplace_info(app.cursor, app.current_ip)
        if info is None:
            app.conn.rollback()
            app.notify("Текущее рабочее место не найдено.", level='error')
            return

        name, max_cur, cur_cur, _ = info
        if cur_cur >= max_cur:
            app.conn.rollback()
            app.notify(f"Место '{name}' заполнено (занято {cur_cur} из "
                       f"{max_cur}). Перемещение невозможно.", level='warn')
            return

        old_place_name = dbm.get_workplace_name(app.cursor, old_ip)

        dbm.close_session(app.cursor, rab)
        if not dbm.decrement_workplace_cur(app.cursor, old_ip):
            app.conn.rollback()
            app.notify("Счётчик RAB_CUR на старом месте уже равен 0. "
                       "Операция отменена.", level='error')
            return
        dbm.create_session(app.cursor, rab, app.current_ip)
        dbm.increment_workplace_cur(app.cursor, app.current_ip)
        app.conn.commit()
        app.notify(f"Работник {fio} перемещён с '{old_place_name}' "
                   f"на '{name}'.")

    def _register_worker(self, rab, fio):
        """Регистрирует сотрудника на текущем рабочем месте."""
        app = self.app
        info = dbm.get_workplace_info(app.cursor, app.current_ip)
        if info is None:
            app.conn.rollback()
            app.notify("Текущее рабочее место не найдено.", level='error')
            return

        name, max_cur, cur_cur, _ = info
        if cur_cur >= max_cur:
            app.conn.rollback()
            app.notify(f"Место '{name}' заполнено (занято {cur_cur} из "
                       f"{max_cur}). Регистрация невозможна.", level='warn')
            return

        dbm.create_session(app.cursor, rab, app.current_ip)
        dbm.increment_workplace_cur(app.cursor, app.current_ip)
        app.conn.commit()
        app.notify(f"Работник {fio} зарегистрирован на {name}.")

# DetalProcessor — регистрация деталей ============================================================
class DetalProcessor:
    """Обработка сканирования деталей и изделий."""

    def __init__(self, app):
        self.app = app

    # Публичная точка входа ---------------------------------------------------
    def process(self, detal):
        """
        Обрабатывает сканирование детали:
        - импост (GRI='3') игнорируется;
        - для GR 1-4 разрешена только «своя» группа (r или s);
        - для GR 5-6 разрешены и рамы, и створки, с проверкой дублей по BCI.
        """
        app = self.app
        try:
            detal_info = dbm.get_detal_full_info(app.cursor, detal)
            if detal_info is None:
                app.notify(f"Деталь с кодом {detal} не найдена.", level='error')
                app.conn.rollback()
                app.ui.clear_detal_info()
                return

            bci = detal_info['bci']
            gri = detal_info['gri']

            # Импост не регистрируется
            if gri == GRI_IMPOST:
                app.notify("Для регистрации отсканируйте деталь рамы или "
                           "створки. Импост не регистрируется.", level='warn')
                app.conn.rollback()
                app.ui.clear_detal_info()
                return

            # Проверка разрешённой группы для 1-4
            if not self._validate_group(gri):
                return

            # Уже зарегистрирована именно эта деталь на этом IP?
            if dbm.get_open_detal_session_at_ip(app.cursor, detal, app.current_ip):
                self._handle_registered(detal, detal_info, bci, gri)
                return

            # Проверка дубликата: для 5-6 — по BCI, для 1-4 — по BCI+GRI
            dup, dup_msg = self._check_duplicate(bci, gri, detal)
            if dup:
                app.notify(dup_msg, level='warn')
                app.conn.rollback()
                return

            self._register(detal, detal_info, bci, gri)
        except Exception as e:
            app.conn.rollback()
            app.notify(f"Ошибка обработки детали: {e}", level='error')

    # Приватные методы --------------------------------------------------------
    def _validate_group(self, gri):
        """Проверяет, разрешена ли данная группа деталей на рабочем месте."""
        app = self.app
        if app.gr in (1, 2, 3, 4) and gri not in app.allowed_gri:
            group_names = {GRI_FRAME: 'РАМЫ', GRI_SASH: 'СТВОРКИ'}
            allowed_names = ', '.join(group_names.get(g, g)
                                      for g in app.allowed_gri)
            if not allowed_names:
                allowed_names = "не разрешена регистрация деталей"
            app.notify(f"На данном рабочем месте разрешена регистрация "
                       f"только {allowed_names}, а вы сканируете "
                       f"{group_names.get(gri, gri)}.", level='warn')
            app.conn.rollback()
            app.ui.clear_detal_info()
            return False
        return True

    def _handle_registered(self, detal, detal_info, bci, gri):
        """Показывает информацию о детали, которая уже зарегистрирована."""
        app = self.app
        app.notify(f"Деталь {detal} (ZAKNUM:{detal_info['zaknum']}) уже "
                   f"зарегистрирована на {app.workplace_name}.", level='warn')
        app.conn.rollback()

        if app.gr in (5, 6):
            dims = dbm.get_dimensions_and_perimeter_area_for_bci_gri(
                app.cursor, bci, GRI_FRAME
            )
            if dims[0] is None or dims[1] is None:
                dims = dbm.get_dimensions_and_perimeter_area_for_bci_gri(
                    app.cursor, bci, GRI_SASH
                )
            app.ui.set_detal_info(detal_info, *dims, override_type="Изделие")
        else:
            dims = dbm.get_dimensions_and_perimeter_area_for_bci_gri(
                app.cursor, bci, gri
            )
            app.ui.set_detal_info(detal_info, *dims)
        app.images.update(detal_info['zaknum'], detal_info['konid'])

    def _check_duplicate(self, bci, gri, detal):
        """
        Проверяет, есть ли уже открытая сессия на это изделие.
        Возвращает (is_duplicate, message).
        """
        app = self.app
        if app.gr in (5, 6):
            dup = dbm.has_open_detal_session_for_bci(
                app.cursor, bci, app.current_ip, exclude_detal=detal
            )
            msg = (f"Изделие с BCI={bci} уже зарегистрировано на "
                   f"{app.workplace_name} (другая деталь). "
                   f"Регистрация новой детали невозможна.")
        else:
            dup = dbm.has_open_detal_sessions_for_bci_gri(
                app.cursor, bci, gri, app.current_ip, exclude_detal=detal
            )
            msg = (f"Изделие (BCI={bci}, тип={gri}) уже зарегистрировано "
                   f"на {app.workplace_name} (другая деталь). "
                   f"Регистрация новой детали невозможна.")
        return dup, msg

    def _register(self, detal, detal_info, bci, gri):
        """Регистрирует деталь и обновляет интерфейс."""
        app = self.app

        if app.gr in (5, 6):
            dims = dbm.get_dimensions_and_perimeter_area_for_bci_gri(
                app.cursor, bci, GRI_FRAME
            )
            if dims[0] is None or dims[1] is None:
                dims = dbm.get_dimensions_and_perimeter_area_for_bci_gri(
                    app.cursor, bci, GRI_SASH
                )
            override_type = "Изделие"
        else:
            dims = dbm.get_dimensions_and_perimeter_area_for_bci_gri(
                app.cursor, bci, gri
            )
            override_type = None

        width_mm, height_mm, perimeter, area = dims
        if width_mm is None or height_mm is None:
            if app.gr in (5, 6):
                msg = ("Не удалось определить габариты изделия "
                       "(нет ни рамы, ни створки с ORIENT='Н' или 'П').")
            else:
                msg = "Не удалось определить габариты изделия (нет ORIENT='Н' или 'П')."
            app.notify(msg, level='error')
            app.conn.rollback()
            return

        dbm.create_detal_session(app.cursor, detal, app.current_ip, app.gr,
                                 bci, gri, perimeter, area)
        app.conn.commit()
        log_message(f"Деталь {detal} зарегистрирована на IP {app.current_ip} "
                    f"(BCI={bci}, GRI={gri})")

        app.ui.set_detal_info(detal_info, width_mm, height_mm, perimeter, area,
                              override_type=override_type)
        app.images.update(detal_info['zaknum'], detal_info['konid'])
        app.notify(f"Зарегистрировано изделие\n"
                   f"Заказ: {detal_info['zaknum']}\n"
                   f"Конструкция: {detal_info['konname']}",
                   timeout=3000)
        app.workers.update_list()
        app.stats.update()

# InputHandler — обработка сканера =================================================================
class InputHandler:
    """Обработчики событий ввода: клики, потеря фокуса, сканирование."""

    def __init__(self, app):
        self.app = app

    def on_click(self, event):
        """При клике на любое место, кроме поля ввода, переводим фокус на поле."""
        app = self.app
        if (app.entry is not None
                and app.entry.winfo_exists()
                and event.widget != app.entry):
            app.entry.focus_set()

    def on_focus_out(self, event):
        """При потере фокуса возвращаем его на поле ввода."""
        app = self.app
        if app.entry is not None and app.entry.winfo_exists():
            app.root.after(10, app.entry.focus_set)

    def on_scan(self, event):
        """Обрабатывает ввод со сканера (или клавиатуры)."""
        app = self.app
        if app.entry is None:
            return

        code = app.entry.get().strip()
        app.entry.delete(0, tk.END)
        if not code:
            app.entry.focus_set()
            return

        # До установки соединения разрешён только код выключения
        if app.conn is None or app.cursor is None:
            if code == CODE_POWEROFF:
                app.on_closing()
            else:
                app.notifier.show_auto_message("Нет подключения к БД.",
                                               "Ожидание", 3000,
                                               msg_type='error')
                app.entry.focus_set()
            return

        # Основная логика после подключения
        if code == CODE_POWEROFF:
            app.workers.close_all()
            app.on_closing()
            return
        if code.startswith(PREFIX_WORKER):
            app.workers.process(code)
        else:
            app.detals.process(code)
        app.entry.focus_set()

# Application — тонкий координатор ================================================================
class Application:
    """Главное окно и координатор менеджеров."""

    def __init__(self, root):
        self.root = root
        self.root.title("Учёт рабочего времени и деталей")
        self.root.geometry("1920x1080+0+0")

        # Общие атрибуты состояния
        self.conn = None
        self.cursor = None
        self.entry = None
        self.current_image_path = None
        self.workplace_name = None
        self.rab_max = 0
        self.rab_cur = 0
        self.gr = None
        self.allowed_gri = []

        log_message("=== Запуск программы ===")
        self.current_ip = int(MY_IP)
        log_message(f"Определён IP: {self.current_ip}")

        # Менеджеры. Порядок важен:
        #   input нужен connection (для on_scan в диалоге);
        #   ui требует уже созданных images, stats, workers;
        #   connection — последний, т.к. стартует первым.
        self.notifier = Notifier(self)
        self.input = InputHandler(self)
        self.images = ImageDisplay(self)
        self.stats = StatsPanel(self)
        self.workers = WorkerSessionManager(self)
        self.detals = DetalProcessor(self)
        self.ui = UIBuilder(self)
        self.connection = ConnectionManager(self)

        # Обработчики событий главного окна
        self.root.bind('<Button-1>', self.input.on_click)
        self.root.bind('<FocusOut>', self.input.on_focus_out)

        # Показываем диалог подключения и начинаем попытки подключения.
        # Дальнейшая инициализация произойдёт в UIBuilder.build()
        # после успешного соединения с БД.
        self.connection.show_connection_dialog()
        self.connection.attempt_connection()

    # Прокси для удобства вызова из менеджеров --------------------------------
    def notify(self, message, level='info', title=None, timeout=5000):
        """Прокси к Notifier.notify (чтобы писать app.notify(...))."""
        return self.notifier.notify(message, level=level,
                                    title=title, timeout=timeout)

    # Завершение работы -------------------------------------------------------
    def on_closing(self):
        """Закрывает соединение с БД и выключает компьютер."""
        log_message("=== Завершение программы ===")
        if self.conn:
            self.conn.close()
        os.system(f"{power_off}")
        self.root.destroy()