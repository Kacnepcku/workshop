#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

from typing import Optional
import tkinter as tk
from tkinter import ttk

from config import FONTS
from models import Detal, Dimensions, ShiftStats, WorkerSession, DetailGroup


class DetalInfoPanel(ttk.LabelFrame):
    """Карточка информации о последней отсканированной детали."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent, text="Информация о детали / изделии", padding=10)
        self.line1 = tk.Label(self, text="", font=FONTS["f1b"], fg="darkblue", anchor="w")
        self.line2 = tk.Label(self, text="", font=FONTS["f1b"], fg="darkblue", anchor="w")
        self.line3 = tk.Label(self, text="", font=FONTS["f4b"], fg="darkblue", anchor="w")
        self.line4 = tk.Label(self, text="", font=FONTS["f2b"], fg="green", anchor="w")
        self.line5 = tk.Label(self, text="", font=FONTS["f2b"], fg="darkred", anchor="w")

        for line in (self.line1, self.line2, self.line3, self.line4, self.line5):
            line.pack(fill=tk.X, padx=10, pady=2, anchor="w")

    def clear(self) -> None:
        for line in (self.line1, self.line2, self.line3, self.line4, self.line5):
            line.config(text="")

    def show_detal(
        self, detal: Detal, dims: Optional[Dimensions], override_type: Optional[str] = None
    ) -> None:
        self.line1.config(text=f"{detal.zaknum}  {detal.konname}  {detal.matcolor}")
        self.line2.config(text=f"{detal.matname}  {detal.cut_length}")
        self.line3.config(text=detal.primproizv or "")

        if override_type:
            type_text = override_type
        elif detal.gri == DetailGroup.FRAME.value:
            type_text = "Тип: РАМА"
        elif detal.gri == DetailGroup.SASH.value:
            type_text = "Тип: СТВОРКА"
        elif detal.gri == DetailGroup.IMPOST.value:
            type_text = "Тип: ИМПОСТ"
        else:
            type_text = f"Тип: {detal.gri}"

        if dims is not None:
            w_m = (dims.width_mm - 6) / 1000.0
            h_m = (dims.height_mm - 6) / 1000.0
            dims_text = (
                f"Шир: {w_m:.3f} м  Выс: {h_m:.3f} м  "
                f"Пр: {dims.perimeter_m:.3f} м  Пл: {dims.area_m2:.3f} м²"
            )
        else:
            dims_text = "Габариты: данные отсутствуют"

        self.line4.config(text=type_text)
        self.line5.config(text=dims_text)


class StatsPanel(ttk.LabelFrame):
    """Панель статистики за смену."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent, text="Статистика за смену", padding=10)
        self.line1 = tk.Label(self, text="Количество изделий: 0", font=FONTS["f1"], anchor="w")
        self.line2 = tk.Label(self, text="Суммарный периметр: 0.000 м", font=FONTS["f1"], anchor="w")
        self.line3 = tk.Label(self, text="Суммарная площадь: 0.000 м²", font=FONTS["f1"], anchor="w")

        for line in (self.line1, self.line2, self.line3):
            line.pack(fill=tk.X, padx=10, pady=2, anchor="w")

    def update_stats(self, stats: ShiftStats) -> None:
        self.line1.config(text=f"Количество изделий: {stats.count}")
        self.line2.config(text=f"Суммарный периметр: {stats.total_perimeter:.3f} м")
        self.line3.config(text=f"Суммарная площадь: {stats.total_area:.3f} м²")


class WorkersTablePanel(ttk.LabelFrame):
    """Таблица активных сотрудников на рабочем месте."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent, text="Сотрудники на рабочем месте", padding=5)

        style = ttk.Style()
        style.configure("Treeview", font=FONTS["f3"], rowheight=30)
        style.configure("Treeview.Heading", font=FONTS["f4"])

        container = tk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(
            container, columns=("num", "fio", "start", "total"), show="headings", height=6
        )
        self.tree.heading("num", text="№")
        self.tree.heading("fio", text="ФИО")
        self.tree.heading("start", text="Начало")
        self.tree.heading("total", text="Всего")
        self.tree.column("num", width=30, anchor="center")
        self.tree.column("fio", width=250, anchor="w")
        self.tree.column("start", width=60, anchor="center")
        self.tree.column("total", width=60, anchor="center")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.config(yscrollcommand=scrollbar.set)

    def update_workers(self, workers: list[WorkerSession]) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx, w in enumerate(workers, start=1):
            self.tree.insert(
                "", "end", values=(idx, w.fio, w.formatted_start, w.formatted_total)
            )


class StatusIndicator(tk.Canvas):
    """Квадратный индикатор состояния сети, основной БД и БД чертежей CCALC (7x7 мм)."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent, width="7m", height="7m", highlightthickness=0, bd=0)
        px = self.winfo_fpixels("7m")
        self._rect = self.create_rectangle(
            1, 1, px - 1, px - 1, fill="#43a047", outline="#555555", width=2
        )

    def set_state(self, db_ok: bool, ccalc_ok: bool) -> None:
        if not db_ok:
            color = "#e53935"  # Красный: нет основной БД / сети
        elif not ccalc_ok:
            color = "#fdd835"  # Жёлтый: недоступна БД CCALC (чертежи)
        else:
            color = "#43a047"  # Зелёный: всё в порядке
        self.itemconfig(self._rect, fill=color)