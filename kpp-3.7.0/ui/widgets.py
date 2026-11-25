#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageFile

from config import FONTS
from models import Detal, Dimensions, ShiftStats, WorkerSession, DetailGroup
from log import log_message

ImageFile.LOAD_TRUNCATED_IMAGES = True


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
    """Квадратный индикатор состояния сети, БД и папки картинок (7x7 мм)."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent, width="7m", height="7m", highlightthickness=0, bd=0)
        px = self.winfo_fpixels("7m")
        self._rect = self.create_rectangle(
            1, 1, px - 1, px - 1, fill="#43a047", outline="#555555", width=2
        )

    def set_state(self, db_ok: bool, images_ok: bool) -> None:
        if not db_ok:
            color = "#e53935"  # Красный: нет БД / сети
        elif not images_ok:
            color = "#fdd835"  # Жёлтый: недоступна SMB-папка
        else:
            color = "#43a047"  # Зелёный: всё в порядке
        self.itemconfig(self._rect, fill=color)


class ImageViewerPanel(ttk.Frame):
    """Правая панель отображения чертежей с фоновой (неблокирующей) загрузкой с SMB."""

    def __init__(self, parent: tk.Misc, image_folder: str):
        super().__init__(parent)
        self.image_folder = image_folder
        self._current_path: Optional[str] = None
        self._request_id = 0
        self._executor = ThreadPoolExecutor(max_workers=1)

        self.label = tk.Label(self, bg=parent.winfo_toplevel().cget("bg"))
        self.label.pack(expand=True, fill=tk.BOTH)
        self.bind("<Configure>", self._on_resize)

    def show_default(self) -> None:
        default_path = os.path.join(self.image_folder, "ROSHAN.png")
        self._load_async(default_path, fallback_to_default=False)

    def show_construction(self, zaknum: str, konid) -> None:
        filepath = os.path.join(self.image_folder, f"{zaknum} ({konid}).jpg")
        self._load_async(filepath, fallback_to_default=True)

    def _on_resize(self, _event) -> None:
        if self._current_path:
            self._load_async(self._current_path, fallback_to_default=False)

    def _load_async(self, filepath: str, fallback_to_default: bool) -> None:
        self._request_id += 1
        req_id = self._request_id
        fw = max(self.winfo_width(), 400)
        fh = max(self.winfo_height(), 300)

        def _worker():
            try:
                if not os.path.exists(filepath):
                    if fallback_to_default:
                        default_path = os.path.join(self.image_folder, "ROSHAN.png")
                        if os.path.exists(default_path):
                            return self._prepare_pil(default_path, fw, fh), default_path
                    return None, None
                return self._prepare_pil(filepath, fw, fh), filepath
            except Exception as e:
                log_message(f"Ошибка загрузки изображения {filepath}: {e}")
                return None, None

        def _done(future):
            if req_id != self._request_id or not self.winfo_exists():
                return
            pil_img, resolved_path = future.result()
            self.after(0, lambda: self._apply_image(pil_img, resolved_path))

        future = self._executor.submit(_worker)
        future.add_done_callback(_done)

    @staticmethod
    def _prepare_pil(path: str, fw: int, fh: int) -> Image.Image:
        img = Image.open(path)
        img.load()
        w, h = img.size
        if w > 80 and h > 80:
            img = img.crop((40, 40, w - 40, h - 40))

        display_w = max(fw - 10, 50)
        display_h = max(fh - 10, 50)
        img.thumbnail((display_w, display_h), Image.Resampling.LANCZOS)
        return img

    def _apply_image(self, pil_img: Optional[Image.Image], resolved_path: Optional[str]) -> None:
        if pil_img is None:
            self._current_path = None
            self.label.config(image="", text="")
            self.label.image = None
            return

        self._current_path = resolved_path
        photo = ImageTk.PhotoImage(pil_img)
        self.label.config(image=photo, text="")
        self.label.image = photo

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
