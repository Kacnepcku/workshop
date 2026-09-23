# -*- coding: utf-8 -*-

"""
formatting.py — чистое форматирование строк интерфейса (без Tkinter/БД).
Все «f-шаблоны» сообщений и подписей собраны здесь, чтобы тексты было
легко менять и покрывать тестами.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import config
from db import DetalInfo, Dimensions


def format_worked_time(total_sec: int) -> str:
    """'1ч 23м' или '5м' из отработанных секунд."""
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    return f"{hours}ч {minutes}м" if hours > 0 else f"{minutes}м"


def format_start(time_start: Optional[datetime]) -> str:
    return time_start.strftime("%H:%M") if time_start else "--:--"


def format_capacity(rab_max: int, rab_cur: int) -> str:
    return f"Максимум сотрудников: {rab_max} | Занято: {rab_cur}"


def _minus_profile(length_mm) -> float:
    """Длина детали за вычетом ширины профиля (бывшая магическая «6»)."""
    if length_mm is None:
        return 0
    return length_mm - config.PROFILE_OFFSET_MM


def detal_lines(info: DetalInfo, dims: Dimensions,
                override_type: Optional[str] = None) -> tuple[str, str, str, str, str]:
    """Пять строк блока «Информация о детали / изделии»."""
    from logic.workplace_policy import detals_type_text  # локально — циклов нет

    line1 = f"{info.zaknum}  {info.konname}  {info.matcolor}"
    line2 = f"{info.matname}  {_minus_profile(info.length)}"
    line3 = info.primproizv or ""
    line4 = override_type if override_type else detals_type_text(info.gri)

    if dims.is_known:
        off = config.PROFILE_OFFSET_MM
        w_m = (dims.width_mm - off) / 1000.0
        h_m = (dims.height_mm - off) / 1000.0
        line5 = (f"Шир: {w_m:.3f} м  Выс: {h_m:.3f} м  "
                 f"Пр: {dims.perimeter_m:.3f} м  Пл: {dims.area_m2:.3f} м²")
    else:
        line5 = "Габариты: данные отсутствуют (нет ORIENT='Н' или 'П')"
    return line1, line2, line3, line4, line5


def stats_lines(count: int, perimeter: float, area: float) -> tuple[str, str, str]:
    return (
        f"Количество изделий: {count}",
        f"Суммарный периметр: {perimeter:.3f} м",
        f"Суммарная площадь: {area:.3f} м²",
    )
