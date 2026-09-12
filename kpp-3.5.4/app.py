#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

import os
import sys
import tkinter as tk
from tkinter import ttk

import pymysql
from PIL import Image, ImageTk, ImageFile

from main import (
    # шрифты
    font0, font1, font2, font3, font4,
    font1b, font2b, font3b, font4b,
    # БД
    DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_CHARSET,
    # пути и ОС
    image_folder, power_off, MY_IP,
    # константы
    CODE_POWEROFF, PREFIX_WORKER,
    GRI_IMPOST, GRI_FRAME, GRI_SASH,
    AUTO_UPDATE_MS, RECONNECT_MS,
    # логирование
    log_message,
)
import db as dbm

# Разрешаем загрузку обрезанных JPEG
ImageFile.LOAD_TRUNCATED_IMAGES = True


class Application:
    """Главное окно и логика приложения."""

    # Инициализация ============================================================================
    def __init__(self, root):
        self.root = root
        self.root.title("Учёт рабочего времени и деталей")
        self.root.geometry("1920x1080+0+0")
        self.root.bind('<Button-1>', self.on_click)
        self.root.bind('<FocusOut>', self.on_focus_out)

        # Атрибуты соединения с БД
        self.conn = None
        self.cursor = None

        log_message("=== Запуск программы ===")
        self.current_ip = int(MY_IP)
        log_message(f"Определён IP: {self.current_ip}")

        # Показываем диалог подключения и начинаем попытки подключения
        self.connection_dialog = self.show_connection_dialog()
        self.attempt_connection()
        # Остальная инициализация — в init_ui (после успешного подключения)

    # Подключение к БД ==========================================================================
    def show_connection_dialog(self):
        """
        Модальное окно с полем ввода для сканера и статусом подключения.
        Позволяет отсканировать 12345 для выключения ПК ещё до подключения.
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("Подключение к базе данных")
        dialog.geometry("600x250")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 600) // 2
        y = (dialog.winfo_screenheight() - 250) // 2
        dialog.geometry(f"+{x}+{y}")

        frame = tk.Frame(dialog, bd=0, relief='flat')
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.conn_label = tk.Label(frame, text="Подключение к БД ...",
                                   font=font1, justify='center')
        self.conn_label.pack(pady=10)

        # Поле ввода для сканера
        self.entry = tk.Entry(frame, font=font1, width=15)
        self.entry.pack(pady=10)
        self.entry.bind("<Return>", self.on_scan)
        self.entry.focus_set()

        return dialog

    def attempt_connection(self):
        """
        Пытается подключиться к БД; при ошибке повторяет через RECONNECT_MS.
        Текст ошибки пишется только в лог, окно не изменяется.
        """
        try:
            self.conn = pymysql.connect(
                host=DB_HOST,
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME,
                charset=DB_CHARSET,
                autocommit=False
            )
            self.cursor = self.conn.cursor()
            log_message("Подключение к БД успешно")

            # Закрываем диалог подключения
            if hasattr(self, 'connection_dialog') and self.connection_dialog:
                self.connection_dialog.destroy()
                self.connection_dialog = None

            # Ссылка на старое поле ввода недействительна — сбрасываем.
            # Новый entry будет создан в init_ui -> _create_input_panel.
            self.entry = None

            self.init_ui()
        except Exception as e:
            log_message(f"Ошибка подключения к БД: {e}")
            self.root.after(RECONNECT_MS, self.attempt_connection)

    # Построение главного окна =================================================================
    def init_ui(self):
        """Собирает все виджеты главного окна после подключения к БД."""
        self._load_workplace_info()
        self._create_main_panes()
        self._create_left_panel()
        self._create_workers_tree()
        self._create_input_panel()
        self._create_image_panel()
        self._initial_data_load()

    def _load_workplace_info(self):
        """Получает информацию о рабочем месте и определяет разрешённые группы."""
        workplace = dbm.get_workplace_info(self.cursor, self.current_ip)
        if not workplace:
            self.notify(f"Рабочее место с IP {self.current_ip} не найдено в БД.",
                        level='error')
            sys.exit(1)

        self.workplace_name, self.rab_max, self.rab_cur, self.gr = workplace
        log_message(f"Рабочее место: {self.workplace_name}, GR={self.gr}, "
                    f"RAB_MAX={self.rab_max}, RAB_CUR={self.rab_cur}")

        # Разрешённые группы деталей для данного рабочего места
        self.allowed_gri = {
            1: [GRI_FRAME], 2: [GRI_FRAME],
            3: [GRI_SASH],  4: [GRI_SASH],
            5: [GRI_FRAME, GRI_SASH],
            6: [GRI_FRAME, GRI_SASH],
        }.get(self.gr, [])

        group_names = {GRI_FRAME: 'РАМЫ', GRI_SASH: 'СТВОРКИ'}
        if not self.allowed_gri:
            allowed_desc = "не разрешена регистрация деталей"
        elif len(self.allowed_gri) == 1:
            allowed_desc = f"разрешена только {group_names[self.allowed_gri[0]]}"
        else:
            allowed_desc = "разрешены РАМЫ и СТВОРКИ"
        log_message(f"Разрешённые группы: {allowed_desc}")

    def _create_main_panes(self):
        """Создаёт разделитель (paned) и два основных фрейма: левый и правый."""
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        self.left_frame = ttk.Frame(self.paned)
        self.paned.add(self.left_frame, weight=1)

        self.right_frame = ttk.Frame(self.paned)
        self.paned.add(self.right_frame, weight=3)

    def _create_left_panel(self):
        """Создаёт верхнюю панель, блоки информации о детали и статистики."""
        # Верхняя панель: название рабочего места + счётчик сотрудников
        top_panel = tk.Frame(self.left_frame)
        top_panel.pack(pady=5, fill=tk.X)

        self.label_place = tk.Label(top_panel, text=self.workplace_name,
                                    font=font0, fg="blue")
        self.label_place.pack(side=tk.LEFT, padx=20)

        self.info_label = tk.Label(
            top_panel,
            text=f"Максимум сотрудников: {self.rab_max} | Занято: {self.rab_cur}",
            font=font4
        )
        self.info_label.pack(side=tk.RIGHT, padx=20)

        # Блок информации о детали (5 строк)
        self.detal_frame = ttk.LabelFrame(self.left_frame,
                                          text="Информация о детали / изделии",
                                          padding=10)
        self.detal_frame.pack(fill=tk.X, padx=10, pady=5)

        self.info_line1 = tk.Label(self.detal_frame, text="", font=font1b, fg="darkblue", anchor='w')
        self.info_line2 = tk.Label(self.detal_frame, text="", font=font1b, fg="darkblue", anchor='w')
        self.info_line3 = tk.Label(self.detal_frame, text="", font=font4b, fg="darkblue", anchor='w')
        self.info_line4 = tk.Label(self.detal_frame, text="", font=font2b, fg="green",    anchor='w')
        self.info_line5 = tk.Label(self.detal_frame, text="", font=font2b, fg="darkred",  anchor='w')

        for line in (self.info_line1, self.info_line2, self.info_line3,
                     self.info_line4, self.info_line5):
            line.pack(fill=tk.X, padx=10, pady=2, anchor='w')

        # Блок статистики за смену
        self.stats_frame = ttk.LabelFrame(self.left_frame,
                                          text="Статистика за смену",
                                          padding=10)
        self.stats_frame.pack(fill=tk.X, padx=10, pady=5)

        self.stats_line1 = tk.Label(self.stats_frame,
                                    text="Количество изделий: 0",
                                    font=font1, anchor='w')
        self.stats_line2 = tk.Label(self.stats_frame,
                                    text="Суммарный периметр: 0.000 м",
                                    font=font1, anchor='w')
        self.stats_line3 = tk.Label(self.stats_frame,
                                    text="Суммарная площадь: 0.000 м²",
                                    font=font1, anchor='w')

        for line in (self.stats_line1, self.stats_line2, self.stats_line3):
            line.pack(fill=tk.X, padx=10, pady=2, anchor='w')

    def _create_workers_tree(self):
        """Создаёт таблицу сотрудников на рабочем месте."""
        self.workers_frame = ttk.LabelFrame(self.left_frame,
                                            text="Сотрудники на рабочем месте",
                                            padding=5)
        self.workers_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        style = ttk.Style()
        style.configure("Treeview", font=font3, rowheight=30)
        style.configure("Treeview.Heading", font=font4)

        tree_frame = tk.Frame(self.workers_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree_workers = ttk.Treeview(
            tree_frame,
            columns=("num", "fio", "start", "total"),
            show="headings",
            height=6
        )
        self.tree_workers.heading("num",   text="№")
        self.tree_workers.heading("fio",   text="ФИО")
        self.tree_workers.heading("start", text="Начало")
        self.tree_workers.heading("total", text="Всего")
        self.tree_workers.column("num",   width=30,  anchor="center")
        self.tree_workers.column("fio",   width=250, anchor="w")
        self.tree_workers.column("start", width=60,  anchor="center")
        self.tree_workers.column("total", width=60,  anchor="center")
        self.tree_workers.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                                  command=self.tree_workers.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_workers.config(yscrollcommand=scrollbar.set)

    def _create_input_panel(self):
        """Создаёт нижнюю панель с полем ввода для сканера (по правому краю)."""
        bottom_frame = tk.Frame(self.left_frame)
        bottom_frame.pack(pady=10, fill=tk.X)

        # Сначала entry — он будет у самого правого края
        self.entry = tk.Entry(bottom_frame, font=font3, width=25)
        self.entry.pack(side=tk.RIGHT, padx=10)
        self.entry.bind("<Return>", self.on_scan)
        self.entry.focus_set()

        # Затем label — он встанет левее entry
        self.entry_label = tk.Label(bottom_frame, text="Штрих-код:", font=font4)
        self.entry_label.pack(side=tk.RIGHT, padx=10)

    def _create_image_panel(self):
        """Создаёт правую часть — контейнер для отображения изображений."""
        bg_color = self.root.cget('bg')
        self.image_label = tk.Label(self.right_frame, bg=bg_color)
        self.image_label.pack(expand=True, fill=tk.BOTH)
        self.right_frame.bind('<Configure>', self.on_right_frame_resize)

    def _initial_data_load(self):
        """Первичная загрузка данных: сессии, список, статистика, картинка."""
        self.current_image_path = None
        self.close_previous_sessions()
        self.update_workers_list()
        self.auto_update()
        self.clear_detal_info()
        self.update_stats_panel()
        self.show_default_image()

    # Обработчики событий и вспомогательные методы ================================================
    def on_click(self, event):
        """При клике на любое место, кроме поля ввода, переводим фокус на поле."""
        if (self.entry is not None
                and self.entry.winfo_exists()
                and event.widget != self.entry):
            self.entry.focus_set()

    def on_focus_out(self, event):
        """При потере фокуса возвращаем его на поле ввода."""
        if self.entry is not None and self.entry.winfo_exists():
            self.root.after(10, self.entry.focus_set)

    def notify(self, message, level='info', title=None, timeout=5000):
        """
        Универсальный вывод сообщения: пишет в лог и показывает окно.
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
        win = tk.Toplevel(self.root)
        win.title(title)
        win_width, win_height = 600, 200
        screen_width  = win.winfo_screenwidth()
        screen_height = win.winfo_screenheight()
        x = (screen_width - win_width) // 2
        y = (screen_height - win_height) // 2
        win.geometry(f"{win_width}x{win_height}+{x}+{y}")
        win.resizable(False, False)
        win.transient(self.root)
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
            if self.entry is not None and self.entry.winfo_exists():
                self.entry.focus_set()

        win.after(timeout, _close)

    # Отображение изображений ====================================================================
    def show_default_image(self):
        """Загружает и отображает стандартное изображение ROSHAN.png."""
        default_path = os.path.join(image_folder, "ROSHAN.png")
        if os.path.exists(default_path):
            try:
                img = Image.open(default_path)
                img.load()
                self.current_image_path = default_path
                self.display_image(img)
                log_message("Отображено стандартное изображение ROSHAN.png")
            except Exception as e:
                log_message(f"Ошибка загрузки стандартного изображения: {e}")
                self.image_label.config(image='', text='')
                self.image_label.image = None
        else:
            self.image_label.config(image='', text='')
            self.image_label.image = None
            log_message("Стандартное изображение ROSHAN.png не найдено")

    def update_image(self, zaknum, konid):
        """Загружает и отображает изображение конструкции по заказу и ID конструкции."""
        self.current_image_path = None
        filename = f"{zaknum} ({konid}).jpg"
        filepath = os.path.join(image_folder, filename)
        if not os.path.exists(filepath):
            self.show_default_image()
            log_message(f"Файл изображения не найден: {filepath}")
            return

        try:
            img = Image.open(filepath)
            img.load()
            self.current_image_path = filepath
            self.display_image(img)
        except Exception as e:
            log_message(f"Ошибка открытия {filepath}: {e}")
            self.show_default_image()

    def display_image(self, img):
        """Масштабирует изображение под размер правого фрейма и отображает."""
        if img is None:
            return

        # Обрезка на 40 пикселей со всех сторон
        width, height = img.size
        if width > 80 and height > 80:
            img = img.crop((40, 40, width - 40, height - 40))

        fw = self.right_frame.winfo_width()
        fh = self.right_frame.winfo_height()
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
        self.image_label.config(image=photo, text='')
        self.image_label.image = photo

    def on_right_frame_resize(self, event):
        """При изменении размера правой панели перерисовываем изображение."""
        if self.current_image_path is None:
            return
        try:
            img = Image.open(self.current_image_path)
            img.load()
            self.display_image(img)
        except Exception:
            pass

    # Работа с сессиями сотрудников ==============================================================
    def close_previous_sessions(self):
        """
        Закрывает зависшие сессии сотрудников за предыдущие дни
        (TIME_END_W = 18:00 дня открытия).
        """
        try:
            self.cursor.execute(
                "SELECT RAB, IP, TIME_START_W FROM WORKER_TIME "
                "WHERE TIME_END_W IS NULL AND DATE(TIME_START_W) < CURDATE()"
            )
            sessions = self.cursor.fetchall()
            if not sessions:
                log_message("Нет зависших сессий сотрудников за предыдущие дни.")
                return

            count = 0
            for rab, ip, start_time in sessions:
                close_time = start_time.replace(hour=18, minute=0, second=0,
                                                microsecond=0)
                if start_time > close_time:
                    close_time = start_time
                self.cursor.execute(
                    "UPDATE WORKER_TIME SET TIME_END_W = %s "
                    "WHERE RAB = %s AND IP = %s AND TIME_END_W IS NULL",
                    (close_time, rab, ip)
                )
                dbm.decrement_workplace_cur(self.cursor, ip)
                count += 1
                log_message(f"Закрыта сессия сотрудника {rab} на IP {ip} "
                            f"(время окончания {close_time})")

            self.conn.commit()
            if count > 0:
                self.notify(f"Закрыто {count} сессий сотрудников за предыдущие "
                            f"дни (в 18:00 дня открытия).")
            else:
                self.entry.focus_set()
        except Exception as e:
            self.conn.rollback()
            self.notify(f"Не удалось закрыть предыдущие сессии сотрудников: {e}",
                        level='error')

    def close_all_worker_sessions(self):
        """Закрывает все открытые сессии на текущем рабочем месте."""
        try:
            self.cursor.execute(
                "SELECT RAB FROM WORKER_TIME "
                "WHERE IP = %s AND TIME_END_W IS NULL",
                (self.current_ip,)
            )
            sessions = self.cursor.fetchall()
            if not sessions:
                log_message("Нет открытых сессий на данном рабочем месте.")
                return

            count = 0
            for (rab,) in sessions:
                dbm.close_session(self.cursor, rab)
                if not dbm.decrement_workplace_cur(self.cursor, self.current_ip):
                    log_message(f"Не удалось уменьшить RAB_CUR для сотрудника {rab}")
                count += 1
                log_message(f"Закрыта сессия сотрудника {rab} на IP "
                            f"{self.current_ip} (время закрытия NOW())")
            self.conn.commit()
            log_message(f"Закрыто {count} сессий на рабочем месте "
                        f"{self.workplace_name}")
            self.update_workers_list()
        except Exception as e:
            self.conn.rollback()
            self.notify(f"Ошибка закрытия сессий: {e}", level='error')

    # Обновление информации на экране =============================================================
    def update_workers_list(self):
        """Обновляет таблицу сотрудников на рабочем месте."""
        for item in self.tree_workers.get_children():
            self.tree_workers.delete(item)

        try:
            workers = dbm.get_current_workers(self.cursor, self.current_ip)
            for idx, (rab, fio, start_time, total_sec) in enumerate(workers, start=1):
                start_str = start_time.strftime("%H:%M") if start_time else "--:--"
                hours   = total_sec // 3600
                minutes = (total_sec % 3600) // 60
                time_str = f"{hours}ч {minutes}м" if hours > 0 else f"{minutes}м"
                self.tree_workers.insert("", "end",
                                         values=(idx, fio, start_str, time_str))

            info = dbm.get_workplace_info(self.cursor, self.current_ip)
            if info:
                _, _, cur, _ = info
                self.rab_cur = cur
                self.info_label.config(
                    text=f"Максимум сотрудников: {self.rab_max} | "
                         f"Занято: {self.rab_cur}"
                )
            self.entry.focus_set()
        except Exception as e:
            self.notify(f"Не удалось обновить список сотрудников: {e}",
                        level='error')

    def update_stats_panel(self):
        """Обновляет статистику за смену (количество, периметр, площадь)."""
        try:
            count, total_perimeter, total_area = dbm.get_stats_for_shift(
                self.cursor, self.current_ip
            )
            self.stats_line1.config(text=f"Количество изделий: {count}")
            self.stats_line2.config(text=f"Суммарный периметр: {total_perimeter:.3f} м")
            self.stats_line3.config(text=f"Суммарная площадь: {total_area:.3f} м²")
            self.entry.focus_set()
        except Exception as e:
            self.notify(f"Ошибка получения статистики: {e}", level='error')

    def auto_update(self):
        """Автоматическое обновление списка сотрудников раз в минуту."""
        self.update_workers_list()
        self.root.after(AUTO_UPDATE_MS, self.auto_update)

    def clear_detal_info(self):
        """Очищает поля информации о детали."""
        for line in (self.info_line1, self.info_line2, self.info_line3,
                     self.info_line4, self.info_line5):
            line.config(text="")

    def set_detal_info(self, detal_info, width_mm, height_mm,
                       perimeter_m, area_m2, override_type=None):
        """Заполняет поля информации о детали переданными данными."""
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

        self.info_line1.config(text=line1)
        self.info_line2.config(text=line2)
        self.info_line3.config(text=line3)
        self.info_line4.config(text=type_text)
        self.info_line5.config(text=dims_text)

    # Обработчик сканирования ===================================================================
    def on_scan(self, event):
        """Обрабатывает ввод со сканера (или клавиатуры)."""
        if self.entry is None:
            return

        code = self.entry.get().strip()
        self.entry.delete(0, tk.END)
        if not code:
            self.entry.focus_set()
            return

        # До установки соединения разрешён только код выключения
        if self.conn is None or self.cursor is None:
            if code == CODE_POWEROFF:
                self.on_closing()
            else:
                self.show_auto_message("Нет подключения к БД.", "Ожидание",
                                       3000, msg_type='error')
                self.entry.focus_set()
            return

        # Основная логика после подключения
        if code == CODE_POWEROFF:
            self.close_all_worker_sessions()
            self.on_closing()
            return
        if code.startswith(PREFIX_WORKER):
            self.process_worker(code)
        else:
            self.process_detal(code)
        self.entry.focus_set()

    # Обработка сотрудника =====================================================================
    def process_worker(self, rab):
        """
        Обрабатывает сканирование штрих-кода сотрудника (префикс 2200).
        Регистрирует начало/окончание работы, перемещение между рабочими местами.
        """
        try:
            fio = dbm.get_worker_fio(self.cursor, rab)
            if fio is None:
                self.notify(f"Работник с кодом {rab} не найден в базе.",
                            level='error')
                self.conn.rollback()
                return

            open_session = dbm.get_open_session(self.cursor, rab)

            if open_session:
                old_ip, _ = open_session
                if old_ip == self.current_ip:
                    self._stop_worker_on_current_ip(rab, fio)
                else:
                    self._move_worker_from_other_ip(rab, fio, old_ip)
            else:
                self._register_worker_on_current_ip(rab, fio)

            self.update_workers_list()
        except Exception as e:
            self.conn.rollback()
            self.notify(f"Ошибка обработки сотрудника: {e}", level='error')

    def _stop_worker_on_current_ip(self, rab, fio):
        """Закрывает сессию сотрудника на текущем рабочем месте."""
        dbm.close_session(self.cursor, rab)
        if not dbm.decrement_workplace_cur(self.cursor, self.current_ip):
            self.conn.rollback()
            self.notify(f"Счётчик RAB_CUR на месте {self.workplace_name} "
                        f"уже равен 0. Операция отменена.", level='error')
            return
        self.conn.commit()
        self.notify(f"Работник {fio} завершил работу на {self.workplace_name}.")

    def _move_worker_from_other_ip(self, rab, fio, old_ip):
        """Перемещает сотрудника с другого рабочего места на текущее."""
        info = dbm.get_workplace_info(self.cursor, self.current_ip)
        if info is None:
            self.conn.rollback()
            self.notify("Текущее рабочее место не найдено.", level='error')
            return

        name, max_cur, cur_cur, _ = info
        if cur_cur >= max_cur:
            self.conn.rollback()
            self.notify(f"Место '{name}' заполнено (занято {cur_cur} из "
                        f"{max_cur}). Перемещение невозможно.", level='warn')
            return

        old_place_name = dbm.get_workplace_name(self.cursor, old_ip)

        dbm.close_session(self.cursor, rab)
        if not dbm.decrement_workplace_cur(self.cursor, old_ip):
            self.conn.rollback()
            self.notify("Счётчик RAB_CUR на старом месте уже равен 0. "
                        "Операция отменена.", level='error')
            return
        dbm.create_session(self.cursor, rab, self.current_ip)
        dbm.increment_workplace_cur(self.cursor, self.current_ip)
        self.conn.commit()
        self.notify(f"Работник {fio} перемещён с '{old_place_name}' "
                    f"на '{name}'.")

    def _register_worker_on_current_ip(self, rab, fio):
        """Регистрирует сотрудника на текущем рабочем месте."""
        info = dbm.get_workplace_info(self.cursor, self.current_ip)
        if info is None:
            self.conn.rollback()
            self.notify("Текущее рабочее место не найдено.", level='error')
            return

        name, max_cur, cur_cur, _ = info
        if cur_cur >= max_cur:
            self.conn.rollback()
            self.notify(f"Место '{name}' заполнено (занято {cur_cur} из "
                        f"{max_cur}). Регистрация невозможна.", level='warn')
            return

        dbm.create_session(self.cursor, rab, self.current_ip)
        dbm.increment_workplace_cur(self.cursor, self.current_ip)
        self.conn.commit()
        self.notify(f"Работник {fio} зарегистрирован на {name}.")

    # Обработка детали ===========================================================================
    def process_detal(self, detal):
        """
        Обрабатывает сканирование штрих-кода детали:
        - импост (GRI='3') игнорируется;
        - для GR 1-4 разрешена только «своя» группа (r или s);
        - для GR 5-6 разрешены и рамы, и створки, с проверкой дублей по BCI.
        """
        try:
            detal_info = dbm.get_detal_full_info(self.cursor, detal)
            if detal_info is None:
                self.notify(f"Деталь с кодом {detal} не найдена.", level='error')
                self.conn.rollback()
                self.clear_detal_info()
                return

            bci = detal_info['bci']
            gri = detal_info['gri']

            # Импост не регистрируется
            if gri == GRI_IMPOST:
                self.notify("Для регистрации отсканируйте деталь рамы или "
                            "створки. Импост не регистрируется.", level='warn')
                self.conn.rollback()
                self.clear_detal_info()
                return

            # Проверка разрешённой группы для 1-4
            if not self._validate_detal_group(gri):
                return

            # Уже зарегистрирована именно эта деталь на этом IP?
            if dbm.get_open_detal_session_at_ip(self.cursor, detal, self.current_ip):
                self._handle_already_registered(detal, detal_info, bci, gri)
                return

            # Проверка дубликата: для 5-6 — по BCI, для 1-4 — по BCI+GRI
            dup, dup_msg = self._check_duplicate(bci, gri, detal)
            if dup:
                self.notify(dup_msg, level='warn')
                self.conn.rollback()
                return

            self._register_detal(detal, detal_info, bci, gri)
        except Exception as e:
            self.conn.rollback()
            self.notify(f"Ошибка обработки детали: {e}", level='error')

    def _validate_detal_group(self, gri):
        """Проверяет, разрешена ли данная группа деталей на рабочем месте."""
        if self.gr in (1, 2, 3, 4) and gri not in self.allowed_gri:
            group_names = {GRI_FRAME: 'РАМЫ', GRI_SASH: 'СТВОРКИ'}
            allowed_names = ', '.join(group_names.get(g, g)
                                      for g in self.allowed_gri)
            if not allowed_names:
                allowed_names = "не разрешена регистрация деталей"
            self.notify(f"На данном рабочем месте разрешена регистрация "
                        f"только {allowed_names}, а вы сканируете "
                        f"{group_names.get(gri, gri)}.", level='warn')
            self.conn.rollback()
            self.clear_detal_info()
            return False
        return True

    def _handle_already_registered(self, detal, detal_info, bci, gri):
        """Показывает информацию о детали, которая уже зарегистрирована."""
        self.notify(f"Деталь {detal} (ZAKNUM:{detal_info['zaknum']}) уже "
                    f"зарегистрирована на {self.workplace_name}.", level='warn')
        self.conn.rollback()

        if self.gr in (5, 6):
            dims = dbm.get_dimensions_and_perimeter_area_for_bci_gri(
                self.cursor, bci, GRI_FRAME
            )
            if dims[0] is None or dims[1] is None:
                dims = dbm.get_dimensions_and_perimeter_area_for_bci_gri(
                    self.cursor, bci, GRI_SASH
                )
            self.set_detal_info(detal_info, *dims, override_type="Изделие")
        else:
            dims = dbm.get_dimensions_and_perimeter_area_for_bci_gri(
                self.cursor, bci, gri
            )
            self.set_detal_info(detal_info, *dims)
        self.update_image(detal_info['zaknum'], detal_info['konid'])

    def _check_duplicate(self, bci, gri, detal):
        """
        Проверяет, есть ли уже открытая сессия на это изделие.
        Возвращает (is_duplicate, message).
        """
        if self.gr in (5, 6):
            dup = dbm.has_open_detal_session_for_bci(
                self.cursor, bci, self.current_ip, exclude_detal=detal
            )
            msg = (f"Изделие с BCI={bci} уже зарегистрировано на "
                   f"{self.workplace_name} (другая деталь). "
                   f"Регистрация новой детали невозможна.")
        else:
            dup = dbm.has_open_detal_sessions_for_bci_gri(
                self.cursor, bci, gri, self.current_ip, exclude_detal=detal
            )
            msg = (f"Изделие (BCI={bci}, тип={gri}) уже зарегистрировано "
                   f"на {self.workplace_name} (другая деталь). "
                   f"Регистрация новой детали невозможна.")
        return dup, msg

    def _register_detal(self, detal, detal_info, bci, gri):
        """Регистрирует деталь и обновляет интерфейс."""
        if self.gr in (5, 6):
            dims = dbm.get_dimensions_and_perimeter_area_for_bci_gri(
                self.cursor, bci, GRI_FRAME
            )
            if dims[0] is None or dims[1] is None:
                dims = dbm.get_dimensions_and_perimeter_area_for_bci_gri(
                    self.cursor, bci, GRI_SASH
                )
            override_type = "Изделие"
        else:
            dims = dbm.get_dimensions_and_perimeter_area_for_bci_gri(
                self.cursor, bci, gri
            )
            override_type = None

        width_mm, height_mm, perimeter, area = dims
        if width_mm is None or height_mm is None:
            if self.gr in (5, 6):
                msg = ("Не удалось определить габариты изделия "
                       "(нет ни рамы, ни створки с ORIENT='Н' или 'П').")
            else:
                msg = "Не удалось определить габариты изделия (нет ORIENT='Н' или 'П')."
            self.notify(msg, level='error')
            self.conn.rollback()
            return

        dbm.create_detal_session(self.cursor, detal, self.current_ip, self.gr,
                                 bci, gri, perimeter, area)
        self.conn.commit()
        log_message(f"Деталь {detal} зарегистрирована на IP {self.current_ip} "
                    f"(BCI={bci}, GRI={gri})")

        self.set_detal_info(detal_info, width_mm, height_mm, perimeter, area,
                            override_type=override_type)
        self.update_image(detal_info['zaknum'], detal_info['konid'])
        self.notify(f"Зарегистрировано изделие\n"
                    f"Заказ: {detal_info['zaknum']}\n"
                    f"Конструкция: {detal_info['konname']}",
                    timeout=3000)
        self.update_workers_list()
        self.update_stats_panel()

    # Завершение работы ========================================================================
    def on_closing(self):
        """Закрывает соединение с БД и выключает компьютер."""
        log_message("=== Завершение программы ===")
        if self.conn:
            self.conn.close()
        os.system(f"{power_off}")
        self.root.destroy()
