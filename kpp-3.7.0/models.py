#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

import math
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Any


class DetailGroup(str, Enum):
    IMPOST = "3"
    FRAME = "r"
    SASH = "s"


@dataclass(frozen=True)
class Workplace:
    ip: int
    name: str
    rab_max: int
    gr: int

    @property
    def allowed_groups(self) -> list[DetailGroup]:
        mapping = {
            1: [DetailGroup.FRAME],
            2: [DetailGroup.FRAME],
            3: [DetailGroup.SASH],
            4: [DetailGroup.SASH],
            5: [DetailGroup.FRAME, DetailGroup.SASH],
            6: [DetailGroup.FRAME, DetailGroup.SASH],
        }
        return mapping.get(self.gr, [])

    @property
    def is_universal(self) -> bool:
        """Рабочие места групп 5 и 6 принимают и рамы, и створки."""
        return self.gr in (5, 6)

    def is_group_allowed(self, gri: str) -> bool:
        return any(g.value == gri for g in self.allowed_groups)


@dataclass(frozen=True)
class WorkerSession:
    rab: str
    fio: str
    start_time: Optional[datetime]
    total_seconds: int

    @property
    def formatted_start(self) -> str:
        return self.start_time.strftime("%H:%M") if self.start_time else "--:--"

    @property
    def formatted_total(self) -> str:
        hours = self.total_seconds // 3600
        minutes = (self.total_seconds % 3600) // 60
        return f"{hours}ч {minutes}м" if hours > 0 else f"{minutes}м"


@dataclass(frozen=True)
class StaleSession:
    rab: str
    ip: int
    start_time: datetime


@dataclass(frozen=True)
class Detal:
    code: str
    zaknum: str
    konname: str
    primproizv: str
    matname: str
    matcolor: str
    length: Optional[int]
    bci: str
    gri: str
    konid: Any

    @property
    def is_impost(self) -> bool:
        return self.gri == DetailGroup.IMPOST.value

    @property
    def cut_length(self) -> int:
        return (self.length - 6) if self.length is not None else 0


@dataclass(frozen=True)
class Dimensions:
    width_mm: float
    height_mm: float
    perimeter_m: float
    area_m2: float

    @classmethod
    def from_rectangle(cls, width_mm: float, height_mm: float) -> "Dimensions":
        w_m = (width_mm - 6) / 1000.0
        h_m = (height_mm - 6) / 1000.0
        return cls(
            width_mm=width_mm,
            height_mm=height_mm,
            perimeter_m=2 * (w_m + h_m),
            area_m2=w_m * h_m,
        )

    @classmethod
    def from_arc(cls, bottom_mm: float, top_mm: float) -> "Dimensions":
        """Полукруг: основание (Н) + дуга (В)."""
        lb_m = (bottom_mm - 6) / 1000.0
        lt_m = (top_mm - 6) / 1000.0
        return cls(
            width_mm=bottom_mm,
            height_mm=top_mm,
            perimeter_m=lb_m + lt_m,
            area_m2=(lb_m ** 2) * math.pi / 8,
        )


@dataclass(frozen=True)
class ShiftStats:
    count: int = 0
    total_perimeter: float = 0.0
    total_area: float = 0.0


@dataclass
class ActionResult:
    """Универсальный результат выполнения операции бизнес-логики для UI."""
    success: bool
    message: str
    level: str = "info"          # 'info' | 'warn' | 'error'
    timeout_ms: int = 5000
    payload: Optional[Any] = None
