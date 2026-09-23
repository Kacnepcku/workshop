#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

"""
db.py — слой доступа к данным (только SQL) для kpp 3.5.5.

Отличия от kpp-3.5.4:
  * все функции принимают ConnectionHolder (курсор и транзакции — внутри);
  * результаты — dataclass-ы вместо «голых» кортежей/словарей;
  * COALESCE в статистике, SELECT 1 вместо COUNT(*) где достаточно факта;
  * пакетные UPDATE вместо циклов (закрытие зависших/всех сессий);
  * единая параметризованная проверка дублей вместо двух почти одинаковых.
Commit/rollback выполняет вызывающая сторона через holder.transaction().
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import config


# --------------------------------------------------------------------------- #
#  Типы результатов                                                            #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WorkplaceInfo:
    name: str
    rab_max: int
    rab_cur: int
    gr: int


@dataclass(frozen=True)
class OpenSession:
    ip: int
    time_start: datetime


@dataclass(frozen=True)
class CurrentWorker:
    rab: int
    fio: str
    time_start: Optional[datetime]
    total_sec: int


@dataclass(frozen=True)
class DetalInfo:
    detal: str
    zaknum: str
    konname: str
    primproizv: str
    matname: str
    matcolor: str
    length: Optional[float]
    bci: str
    gri: str
    konid: str


@dataclass(frozen=True)
class Dimensions:
    """Габариты изделия; width_mm/height_mm могут быть None — данных нет."""
    width_mm: Optional[int]
    height_mm: Optional[int]
    perimeter_m: Optional[float]
    area_m2: Optional[float]

    @property
    def is_known(self) -> bool:
        return self.width_mm is not None and self.height_mm is not None


@dataclass(frozen=True)
class ShiftStats:
    count: int
    total_perimeter: float
    total_area: float


@dataclass(frozen=True)
class StaleSession:
    rab: int
    ip: int
    time_start: datetime


# --------------------------------------------------------------------------- #
#  Сотрудники и рабочие места                                                  #
# --------------------------------------------------------------------------- #
def get_worker_fio(holder, rab: int) -> Optional[str]:
    """ФИО сотрудника по табельному номеру."""
    with holder.cursor() as cur:
        cur.execute("SELECT FIO FROM WORKER WHERE RAB = %s", (rab,))
        row = cur.fetchone()
    return row[0] if row else None


def get_workplace_name(holder, ip: int) -> str:
    """Имя рабочего места по IP (или сам IP, если место не заведено)."""
    info = get_workplace_info(holder, ip)
    return info.name if info else str(ip)


def get_workplace_info(holder, ip: int) -> Optional[WorkplaceInfo]:
    """NAME, RAB_MAX, RAB_CUR, GR рабочего места."""
    with holder.cursor() as cur:
        cur.execute(
            "SELECT NAME, RAB_MAX, RAB_CUR, GR FROM WORKPLACE WHERE IP = %s",
            (ip,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return WorkplaceInfo(name=row[0], rab_max=row[1], rab_cur=row[2], gr=row[3])


def get_open_session(holder, rab: int) -> Optional[OpenSession]:
    """Открытая сессия сотрудника за сегодня."""
    with holder.cursor() as cur:
        cur.execute(
            "SELECT IP, TIME_START_W FROM WORKER_TIME "
            "WHERE RAB = %s AND DATE(TIME_START_W) = CURDATE() "
            "AND TIME_END_W IS NULL",
            (rab,),
        )
        row = cur.fetchone()
    return OpenSession(ip=row[0], time_start=row[1]) if row else None


def close_session(holder, rab: int) -> None:
    """Закрыть текущую открытую сессию сотрудника (TIME_END_W = NOW())."""
    with holder.cursor() as cur:
        cur.execute(
            "UPDATE WORKER_TIME SET TIME_END_W = NOW() "
            "WHERE RAB = %s AND TIME_END_W IS NULL",
            (rab,),
        )


def create_session(holder, rab: int, ip: int) -> None:
    """Новая сессия сотрудника на рабочем месте."""
    with holder.cursor() as cur:
        cur.execute(
            "INSERT INTO WORKER_TIME (RAB, IP, TIME_START_W, TIME_END_W) "
            "VALUES (%s, %s, NOW(), NULL)",
            (rab, ip),
        )


def decrement_workplace_cur(holder, ip: int) -> bool:
    """Уменьшить счётчик занятых мест; False, если он уже был 0."""
    with holder.cursor() as cur:
        cur.execute(
            "UPDATE WORKPLACE SET RAB_CUR = RAB_CUR - 1 "
            "WHERE IP = %s AND RAB_CUR > 0",
            (ip,),
        )
        return cur.rowcount > 0


def increment_workplace_cur(holder, ip: int) -> None:
    """Увеличить счётчик занятых мест."""
    with holder.cursor() as cur:
        cur.execute(
            "UPDATE WORKPLACE SET RAB_CUR = RAB_CUR + 1 WHERE IP = %s",
            (ip,),
        )


def get_current_workers(holder, ip: int) -> list[CurrentWorker]:
    """
    Сотрудники, работающие сейчас на данном IP (N+1 устранён: суммарное
    время считается одним подзапросом).
    """
    with holder.cursor() as cur:
        cur.execute(
            "SELECT wt.RAB, w.FIO, wt.TIME_START_W, "
            "       COALESCE((SELECT SUM(TIMESTAMPDIFF(SECOND, TIME_START_W, "
            "                                 IFNULL(TIME_END_W, NOW()))) "
            "                 FROM WORKER_TIME "
            "                 WHERE RAB = wt.RAB "
            "                   AND DATE(TIME_START_W) = CURDATE()), 0) AS total_sec "
            "FROM WORKER_TIME wt "
            "JOIN WORKER w ON wt.RAB = w.RAB "
            "WHERE wt.IP = %s AND DATE(wt.TIME_START_W) = CURDATE() "
            "  AND wt.TIME_END_W IS NULL",
            (ip,),
        )
        rows = cur.fetchall()
    return [CurrentWorker(rab=r[0], fio=r[1], time_start=r[2], total_sec=r[3])
            for r in rows]


def get_stale_sessions(holder) -> list[StaleSession]:
    """Открытые сессии сотрудников за предыдущие дни (зависшие)."""
    with holder.cursor() as cur:
        cur.execute(
            "SELECT RAB, IP, TIME_START_W FROM WORKER_TIME "
            "WHERE TIME_END_W IS NULL AND DATE(TIME_START_W) < CURDATE()"
        )
        rows = cur.fetchall()
    return [StaleSession(rab=r[0], ip=r[1], time_start=r[2]) for r in rows]


def close_stale_sessions_batch(holder) -> int:
    """
    Пакетно закрыть все зависшие сессии за предыдущие дни
    (TIME_END_W = 18:00 дня открытия, но не раньше начала сессии)
    и синхронно пересчитать RAB_CUR во всех WORKPLACE.
    Возвращает число закрытых сессий. Раньше — цикл из N UPDATE + N UPDATE
    счётчика; теперь два запроса, без рассинхрона RAB_CUR.
    """
    with holder.cursor() as cur:
        cur.execute(
            "UPDATE WORKER_TIME "
            "SET TIME_END_W = GREATEST(DATE_ADD(DATE(TIME_START_W), "
            "                          INTERVAL 18 HOUR), TIME_START_W) "
            "WHERE TIME_END_W IS NULL AND DATE(TIME_START_W) < CURDATE()"
        )
        closed = cur.rowcount
        cur.execute(
            "UPDATE WORKPLACE wp "
            "SET wp.RAB_CUR = GREATEST("
            "  (SELECT COUNT(*) FROM WORKER_TIME wt "
            "    WHERE wt.IP = wp.IP AND wt.TIME_END_W IS NULL), 0)"
        )
    return closed


def get_open_session_rabs_at_ip(holder, ip: int) -> list[int]:
    """Табельные сотрудников с открытыми сессиями на данном IP."""
    with holder.cursor() as cur:
        cur.execute(
            "SELECT RAB FROM WORKER_TIME "
            "WHERE IP = %s AND TIME_END_W IS NULL",
            (ip,),
        )
        rows = cur.fetchall()
    return [r[0] for r in rows]


def close_all_sessions_at_ip(holder, ip: int) -> int:
    """Пакетно закрыть все открытые сессии на рабочем месте; вернуть их число."""
    with holder.cursor() as cur:
        cur.execute(
            "UPDATE WORKER_TIME SET TIME_END_W = NOW() "
            "WHERE IP = %s AND TIME_END_W IS NULL",
            (ip,),
        )
        closed = cur.rowcount
        cur.execute(
            "UPDATE WORKPLACE SET RAB_CUR = 0 WHERE IP = %s AND RAB_CUR > 0",
            (ip,),
        )
    return closed


# --------------------------------------------------------------------------- #
#  Детали и статистика                                                          #
# --------------------------------------------------------------------------- #
def get_detal_full_info(holder, detal: str) -> Optional[DetalInfo]:
    """Полная информация о детали по её коду."""
    with holder.cursor() as cur:
        cur.execute(
            "SELECT ZAKNUM, KONNAME, PRIMPROIZV, MATNAME, MATCOLOR, "
            "       LENGTH, BCI, GRI, KONID "
            "FROM CCALC WHERE DETAL = %s",
            (detal,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return DetalInfo(
        detal=detal, zaknum=row[0], konname=row[1], primproizv=row[2],
        matname=row[3], matcolor=row[4], length=row[5],
        bci=row[6], gri=row[7], konid=row[8],
    )


def has_open_detal_session_at_ip(holder, detal: str, ip: int) -> bool:
    """Зарегистрирована ли уже именно эта деталь на данном IP."""
    with holder.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM DETAL_TIME "
            "WHERE DETAL = %s AND IP = %s AND TIME_END_D IS NULL LIMIT 1",
            (detal, ip),
        )
        return cur.fetchone() is not None


def has_open_duplicate(holder, bci: str, ip: int,
                       gri: Optional[str] = None,
                       exclude_detal: Optional[str] = None) -> bool:
    """
    Есть ли открытая сессия на изделие BCI (опционально — конкретной группы
    GRI) на данном IP, исключая саму деталь. Единая параметризованная функция
    вместо двух почти идентичных (has_open_detal_session_for_bci / _for_bci_gri).
    """
    sql = ("SELECT 1 FROM DETAL_TIME dt "
           "JOIN CCALC cc ON dt.DETAL = cc.DETAL "
           "WHERE dt.IP = %s AND dt.TIME_END_D IS NULL AND cc.BCI = %s")
    params: list = [ip, bci]
    if gri is not None:
        sql += " AND cc.GRI = %s"
        params.append(gri)
    if exclude_detal is not None:
        sql += " AND dt.DETAL != %s"
        params.append(exclude_detal)
    sql += " LIMIT 1"
    with holder.cursor() as cur:
        cur.execute(sql, tuple(params))
        return cur.fetchone() is not None


def get_dimensions_for_bci_gri(holder, bci: str,
                               gri: Optional[str] = None) -> Dimensions:
    """
    Габариты (Ш×В, периметр, площадь) для BCI и группы.
    Если gri=None — сначала рама ('r'), затем створка ('s').
    Периметр/площадь считаются по габариту минус ширина профиля
    (config.PROFILE_OFFSET_MM — бывшая «магическая шестёрка»).
    """
    def _fetch(params: tuple) -> tuple[Optional[int], Optional[int]]:
        """Габариты по BCI+GRI; ORIENT 'Н' — ширина, 'П' — высота."""
        with holder.cursor() as cur:
            cur.execute(
                "SELECT ORIENT, LENGTH FROM CCALC "
                "WHERE BCI = %s AND GRI = %s AND ORIENT IN ('Н', 'П')",
                params,
            )
            width_mm = height_mm = None
            for orient, length in cur.fetchall():
                if orient == "Н":
                    width_mm = length
                elif orient == "П":
                    height_mm = length
        return width_mm, height_mm

    def _calc(width_mm, height_mm) -> Dimensions:
        off = config.PROFILE_OFFSET_MM
        w_m = (width_mm - off) / 1000.0
        h_m = (height_mm - off) / 1000.0
        return Dimensions(width_mm, height_mm, 2 * (w_m + h_m), w_m * h_m)

    if gri is not None:
        candidates: list[tuple] = [(bci, gri)]
    else:
        candidates = [(bci, config.GRI_FRAME), (bci, config.GRI_SASH)]

    for params in candidates:
        width_mm, height_mm = _fetch(params)
        if width_mm is not None and height_mm is not None:
            return _calc(width_mm, height_mm)
    return Dimensions(None, None, None, None)


def create_detal_session(holder, detal: str, ip: int, gr: int,
                         bci: str, gri: str,
                         perimeter: float, area: float) -> None:
    """Создать запись о регистрации детали (открытая сессия)."""
    with holder.cursor() as cur:
        cur.execute(
            "INSERT INTO DETAL_TIME "
            "(IP, DETAL, TIME_START_D, TIME_END_D, GR, BCI, GRI, PP, SS) "
            "VALUES (%s, %s, NOW(), NULL, %s, %s, %s, %s, %s)",
            (ip, detal, gr, bci, gri, perimeter, area),
        )


def get_stats_for_shift(holder, ip: int) -> ShiftStats:
    """Статистика за сегодня: изделия, суммарный периметр и площадь."""
    with holder.cursor() as cur:
        cur.execute(
            "SELECT COUNT(DISTINCT BCI), COALESCE(SUM(PP), 0), "
            "       COALESCE(SUM(SS), 0) "
            "FROM DETAL_TIME "
            "WHERE IP = %s AND DATE(TIME_START_D) = CURDATE() "
            "  AND BCI IS NOT NULL",
            (ip,),
        )
        row = cur.fetchone()
    return ShiftStats(count=int(row[0]), total_perimeter=float(row[1]),
                      total_area=float(row[2]))
