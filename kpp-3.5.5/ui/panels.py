# -*- coding: utf-8 -*-

"""
panels.py — инкапсулированные виджеты главного окна kpp 3.5.5.

Каждая панель владеет своими Tk-виджетами и предоставляет узкий API;
никто извне не лезит в чужие Label (в 3.5.4 app.stats_line1.config(...)
вызывался прямо из StatsPanel, а app.tree_workers — из менеджеров).

Состав:
    DetalInfoPanel  — блок «Информация о детали / изделии» (5 строк)
    StatsPanel      — статистика за смену (3 строки) + set(stats)
    CapacityLabel   — счётчик «Максимум | Занято»
    WorkersTree     — таблица сотрудников; точечное обновление вместо
                      полного пересоздания всех строк каждые 60 секунд
    ImageDisplay    — правая панель изображений: кеш образов по пути файла
                      + антидребезг <Configure> (алгоритм ресайза LANCZOS
                      сохранён без изменений)
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageFile

import config
from db import CurrentWorker, DetalInfo, Dimensions, ShiftStats
from logic.formatting import detal_lines, format_start, format_worked_time, stats_lines
from ui.fonts import font0, font1, font1b, font2b, font3, font4, font4b

ImageFile.LOAD_TRUNCATED_IMAGES = True


class DetalInfoPanel(ttk.LabelFrame):
    """Пять строк информации о детали/изделии."""

    def __init__(self, master) -> None:
        super().__init__(master, text="Информация о детали / изделии", padding=10)
        specs = [
            (font1b, "darkblue"),
            (font1b, "darkblue"),
            (font4b, "darkblue"),
            (font2b, "green"),
            (font2b, "darkred"),
        ]
        self._labels: List[tk.Label] = []
        for font, color in specs:
            lbl = tk.Label(self, text="", font=font, fg=color, anchor="w")
            lbl.pack(fill=tk.X, padx=10, pady=2, anchor="w")
            self._labels.append(lbl)

    def clear(self) -> None:
        for lbl in self._labels:
            lbl.config(text="")

    def show(self, info: DetalInfo, dims: Dimensions,
             override_type: Optional[str] = None) -> None:
        lines = detal_lines(info, dims, override_type)
        for lbl, text in zip(self._labels, lines):
            lbl.config(text=text)


class StatsPanel(ttk.LabelFrame):
    """Статистика за смену."""

    def __init__(self, master) -> None:
        super().__init__(master, text="Статистика за смену", padding=10)
        self._labels = []
        for text in ("Количество изделий: 0",
                     "Суммарный периметр: 0.000 м",
                     "Суммарная площадь: 0.000 м²"):
            lbl = tk.Label(self, text=text, font=font1, anchor="w")
            lbl.pack(fill=tk.X, padx=10, pady=2, anchor="w")
            self._labels.append(lbl)

    def set(self, stats: ShiftStats) -> None:
        for lbl, text in zip(self._labels,
                             stats_lines(stats.count, stats.total_perimeter,
                                         stats.total_area)):
            lbl.config(text=text)


class CapacityLabel(tk.Label):
    """«Максимум сотрудников: N | Занято: M»."""

    def __init__(self, master, rab_max: int, rab_cur: int) -> None:
        self._rab_max = rab_max
        super().__init__(master, font=font4)
        self.set(rab_cur)

    def set(self, rab_cur: int) -> None:
        self.config(text=f"Максимум сотрудников: {self._rab_max} | "
                         f"Занято: {rab_cur}")


class WorkplaceHeader(tk.Frame):
    """Шапка левой панели: название места + счётчик занятости."""

    def __init__(self, master, workplace_name: str,
                 rab_max: int, rab_cur: int) -> None:
        super().__init__(master)
        tk.Label(self, text=workplace_name, font=font0, fg="blue") \
            .pack(side=tk.LEFT, padx=20)
        self.capacity = CapacityLabel(self, rab_max, rab_cur)
        self.capacity.pack(side=tk.RIGHT, padx=20)


class WorkersTree(ttk.LabelFrame):
    """
    Таблица сотрудников на рабочем месте.

    update_workers() обновляет строки точечно (item()/delete() лишних),
    а не удаляет и пересоздаёт все строки при каждой автообновке.
    """

    _COLUMNS = ("num", "fio", "start", "total")

    def __init__(self, master) -> None:
        super().__init__(master, text="Сотрудники на рабочем месте", padding=5)
        style = ttk.Style()
        style.configure("Treeview", font=font3, rowheight=30)
        style.configure("Treeview.Heading", font=font4)

        frame = tk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True)

        self._tree = ttk.Treeview(frame, columns=self._COLUMNS,
                                  show="headings", height=6)
        headings = {"num": "№", "fio": "ФИО",
                    "start": "Начало", "total": "Всего"}
        widths = {"num": 30, "fio": 250, "start": 60, "total": 60}
        anchors = {"num": "center", "fio": "w",
                   "start": "center", "total": "center"}
        for col in self._COLUMNS:
            self._tree.heading(col, text=headings[col])
            self._tree.column(col, width=widths[col], anchor=anchors[col])
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                                  command=self._tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.config(yscrollcommand=scrollbar.set)

    def update_workers(self, workers: List[CurrentWorker]) -> None:
        desired = [
            (str(idx), w.fio, format_start(w.time_start),
             format_worked_time(w.total_sec))
            for idx, w in enumerate(workers, start=1)
        ]
        existing = self._tree.get_children()
        # Обновляем совпадающие по индексу строки, досоздаём новые,
        # удаляем лишние — без «delete all + insert all».
        for i, values in enumerate(desired):
            if i < len(existing):
                self._tree.item(existing[i], values=values)
            else:
                self._tree.insert("", "end", values=values)
        for extra in existing[len(desired):]:
            self._tree.delete(extra)


class ImageDisplay(ttk.Frame):
    """
    Правая панель: показ изображений конструкции.

    * Кеш PIL-образов по пути файла: повторные показа того же файла
      не читают диск заново (размер кеша ограничен IMAGE_CACHE_MAX).
    * Антидребезг <Configure>: тяжёлая перерисовка выполняется через
      RESIZE_DEBOUNCE_MS после последнего события ресайза.
    * Алгоритм масштабирования (thumbnail + LANCZOS) оставлен без изменений.
    """

    IMAGE_CACHE_MAX = 12
    CROP_MARGIN_PX = 40
    PADDING_PX = 5

    def __init__(self, master) -> None:
        super().__init__(master)
        self._label = tk.Label(self, bg=master.cget("bg"))
        self._label.pack(expand=True, fill=tk.BOTH)
        self._cache: Dict[str, Image.Image] = {}
        self.current_path: Optional[str] = None
        self._resize_job: Optional[str] = None
        self.bind("<Configure>", self._on_resize_event)

    # -- публичный API ---------------------------------------------------------
    def show_default(self) -> None:
        default_path = os.path.join(config.image_folder, "ROSHAN.png")
        if self._show_file(default_path):
            from logging_setup import log_message
            log_message("Отображено стандартное изображение ROSHAN.png")
        else:
            self.clear()

    def show_detal(self, zaknum: str, konid: str) -> None:
        filepath = os.path.join(config.image_folder,
                                f"{zaknum} ({konid}).jpg")
        if not self._show_file(filepath):
            from logging_setup import log_message
            log_message(f"Файл изображения не найден: {filepath}")
            self.show_default()

    def clear(self) -> None:
        self.current_path = None
        self._label.config(image="", text="")
        self._label.image = None

    # -- внутреннее ------------------------------------------------------------
    def _load(self, path: str) -> Optional[Image.Image]:
        """Образ из кеша либо с диска (кеш — по исходному файлу до кропа)."""
        img = self._cache.get(path)
        if img is not None:
            return img.copy()  # copy: thumbnail/crop мутируют образ
        if not os.path.exists(path):
            return None
        try:
            img = Image.open(path)
            img.load()
        except Exception as e:
            from logging_setup import log_message
            log_message(f"Ошибка открытия {path}: {e}")
            return None
        if len(self._cache) >= self.IMAGE_CACHE_MAX:
            self._cache.pop(next(iter(self._cache)))
        self._cache[path] = img
        return img.copy()

    def _show_file(self, path: str) -> bool:
        img = self._load(path)
        if img is None:
            return False
        self.current_path = path
        self._display(img)
        return True

    def _display(self, img: Image.Image) -> None:
        width, height = img.size
        margin = self.CROP_MARGIN_PX
        if width > 2 * margin and height > 2 * margin:
            img = img.crop((margin, margin, width - margin, height - margin))

        fw = self.winfo_width()
        fh = self.winfo_height()
        if fw < 20 or fh < 20:
            fw, fh = 400, 300

        pad = self.PADDING_PX
        dw, dh = fw - 2 * pad, fh - 2 * pad
        if dw < 50 or dh < 50:
            dw, dh = fw - 10, fh - 10

        img.thumbnail((dw, dh), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self._label.config(image=photo, text="")
        self._label.image = photo

    def _on_resize_event(self, event) -> None:
        """Антидребезг: перерисовка только после последнего <Configure>."""
        if event.widget is not self or self.current_path is None:
            return
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(config.RESIZE_DEBOUNCE_MS,
                                      self._redraw_current)

    def _redraw_current(self) -> None:
        self._resize_job = None
        if self.current_path is None:
            return
        img = self._load(self.current_path)
        if img is not None:
            self._display(img)
