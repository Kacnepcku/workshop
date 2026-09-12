#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

"""
db.py — функции для работы с базой данных MySQL.

Все запросы выполняются через переданный cursor. Commit/rollback
делает вызывающая сторона (класс Application).
"""

from main import GRI_IMPOST, GRI_FRAME, GRI_SASH  # noqa: F401 (для читаемости)

# Сотрудники и рабочие места ====================================================================
def get_worker_fio(cursor, rab):
    """Получить ФИО сотрудника по его табельному номеру."""
    cursor.execute("SELECT FIO FROM WORKER WHERE RAB = %s", (rab,))
    row = cursor.fetchone()
    return row[0] if row else None

def get_workplace_name(cursor, ip):
    """Получить имя рабочего места по IP."""
    cursor.execute("SELECT NAME FROM WORKPLACE WHERE IP = %s", (ip,))
    row = cursor.fetchone()
    return row[0] if row else str(ip)

def get_workplace_info(cursor, ip):
    """Получить информацию о рабочем месте: NAME, RAB_MAX, RAB_CUR, GR."""
    cursor.execute(
        "SELECT NAME, RAB_MAX, RAB_CUR, GR FROM WORKPLACE WHERE IP = %s",
        (ip,)
    )
    return cursor.fetchone()

def get_open_session(cursor, rab):
    """Найти открытую сессию сотрудника за сегодня."""
    cursor.execute(
        "SELECT IP, TIME_START_W FROM WORKER_TIME "
        "WHERE RAB = %s AND DATE(TIME_START_W) = CURDATE() AND TIME_END_W IS NULL",
        (rab,)
    )
    return cursor.fetchone()

def close_session(cursor, rab):
    """Закрыть текущую открытую сессию сотрудника (TIME_END_W = NOW())."""
    cursor.execute(
        "UPDATE WORKER_TIME SET TIME_END_W = NOW() "
        "WHERE RAB = %s AND TIME_END_W IS NULL",
        (rab,)
    )

def create_session(cursor, rab, ip):
    """Создать новую сессию для сотрудника на данном рабочем месте."""
    cursor.execute(
        "INSERT INTO WORKER_TIME (RAB, IP, TIME_START_W, TIME_END_W) "
        "VALUES (%s, %s, NOW(), NULL)",
        (rab, ip)
    )

def decrement_workplace_cur(cursor, ip):
    """Уменьшить счётчик занятых мест на рабочем месте."""
    cursor.execute(
        "UPDATE WORKPLACE SET RAB_CUR = RAB_CUR - 1 WHERE IP = %s AND RAB_CUR > 0",
        (ip,)
    )
    return cursor.rowcount > 0

def increment_workplace_cur(cursor, ip):
    """Увеличить счётчик занятых мест на рабочем месте."""
    cursor.execute(
        "UPDATE WORKPLACE SET RAB_CUR = RAB_CUR + 1 WHERE IP = %s",
        (ip,)
    )

def get_current_workers(cursor, ip):
    """
    Список сотрудников, работающих сейчас на данном IP:
    табельный номер, ФИО, время начала и отработано секунд за сегодня.

    Один SQL-запрос вместо N+1: суммарное время считается подзапросом.
    """
    cursor.execute(
        "SELECT wt.RAB, w.FIO, wt.TIME_START_W, "
        "       (SELECT SUM(TIMESTAMPDIFF(SECOND, TIME_START_W, "
        "                                 IFNULL(TIME_END_W, NOW()))) "
        "        FROM WORKER_TIME "
        "        WHERE RAB = wt.RAB AND DATE(TIME_START_W) = CURDATE()) AS total_sec "
        "FROM WORKER_TIME wt "
        "JOIN WORKER w ON wt.RAB = w.RAB "
        "WHERE wt.IP = %s AND DATE(wt.TIME_START_W) = CURDATE() AND wt.TIME_END_W IS NULL",
        (ip,)
    )
    return [(rab, fio, start, total or 0)
            for rab, fio, start, total in cursor.fetchall()]

# Детали и статистика =============================================================================
def get_detal_full_info(cursor, detal):
    """Получить полную информацию о детали по её коду."""
    cursor.execute(
        "SELECT ZAKNUM, KONNAME, PRIMPROIZV, MATNAME, MATCOLOR, LENGTH, BCI, GRI, KONID "
        "FROM CCALC WHERE DETAL = %s",
        (detal,)
    )
    row = cursor.fetchone()
    if row:
        return {
            'zaknum':     row[0],
            'konname':    row[1],
            'primproizv': row[2],
            'matname':    row[3],
            'matcolor':   row[4],
            'length':     row[5],
            'bci':        row[6],
            'gri':        row[7],
            'konid':      row[8],
        }
    return None

def get_open_detal_session_at_ip(cursor, detal, ip):
    """Проверить, не зарегистрирована ли данная деталь на данном IP."""
    cursor.execute(
        "SELECT TIME_START_D FROM DETAL_TIME "
        "WHERE DETAL = %s AND IP = %s AND TIME_END_D IS NULL",
        (detal, ip)
    )
    return cursor.fetchone()

def has_open_detal_sessions_for_bci_gri(cursor, bci, gri, ip, exclude_detal=None):
    """
    Есть ли открытые сессии для данного BCI и GRI на указанном IP
    (исключая, возможно, текущую деталь).
    """
    if exclude_detal:
        cursor.execute(
            "SELECT COUNT(*) FROM DETAL_TIME dt "
            "JOIN CCALC cc ON dt.DETAL = cc.DETAL "
            "WHERE dt.IP = %s AND dt.TIME_END_D IS NULL "
            "AND cc.BCI = %s AND cc.GRI = %s AND dt.DETAL != %s",
            (ip, bci, gri, exclude_detal)
        )
    else:
        cursor.execute(
            "SELECT COUNT(*) FROM DETAL_TIME dt "
            "JOIN CCALC cc ON dt.DETAL = cc.DETAL "
            "WHERE dt.IP = %s AND dt.TIME_END_D IS NULL "
            "AND cc.BCI = %s AND cc.GRI = %s",
            (ip, bci, gri)
        )
    return cursor.fetchone()[0] > 0

def has_open_detal_session_for_bci(cursor, bci, ip, exclude_detal=None):
    """
    Есть ли открытые сессии для данного BCI (любой GRI) на IP.
    Используется для мест 5-6.
    """
    if exclude_detal:
        cursor.execute(
            "SELECT COUNT(*) FROM DETAL_TIME dt "
            "JOIN CCALC cc ON dt.DETAL = cc.DETAL "
            "WHERE dt.IP = %s AND dt.TIME_END_D IS NULL "
            "AND cc.BCI = %s AND dt.DETAL != %s",
            (ip, bci, exclude_detal)
        )
    else:
        cursor.execute(
            "SELECT COUNT(*) FROM DETAL_TIME dt "
            "JOIN CCALC cc ON dt.DETAL = cc.DETAL "
            "WHERE dt.IP = %s AND dt.TIME_END_D IS NULL "
            "AND cc.BCI = %s",
            (ip, bci)
        )
    return cursor.fetchone()[0] > 0

def get_dimensions_and_perimeter_area_for_bci_gri(cursor, bci, gri=None):
    """
    Возвращает (ширина_мм, высота_мм, периметр_м, площадь_м2) для BCI и группы.

    Если gri не задан — сначала ищет раму (GRI='r'), затем створку (GRI='s').
    Другие группы игнорируются.
    """
    def _calc(width_mm, height_mm):
        """Внутренняя функция: считает периметр и площадь по габаритам."""
        w_m = (width_mm - 6) / 1000.0
        h_m = (height_mm - 6) / 1000.0
        return width_mm, height_mm, 2 * (w_m + h_m), w_m * h_m

    def _query(where_gri_clause, params):
        """
        Выполняет запрос и возвращает (width_mm, height_mm).
        where_gri_clause — безопасный литерал (либо "GRI = %s", либо "GRI = 'r'").
        """
        cursor.execute(
            "SELECT ORIENT, LENGTH FROM CCALC "
            f"WHERE BCI = %s AND {where_gri_clause} AND ORIENT IN ('Н', 'П')",
            params
        )
        width_mm = height_mm = None
        for orient, length in cursor.fetchall():
            if orient == 'Н':
                width_mm = length
            elif orient == 'П':
                height_mm = length
        return width_mm, height_mm

    if gri is not None:
        width_mm, height_mm = _query("GRI = %s", (bci, gri))
        if width_mm is not None and height_mm is not None:
            return _calc(width_mm, height_mm)
        return None, None, None, None

    # Сначала рама
    width_mm, height_mm = _query("GRI = 'r'", (bci,))
    if width_mm is not None and height_mm is not None:
        return _calc(width_mm, height_mm)

    # Если рамы нет — пробуем створку
    width_mm, height_mm = _query("GRI = 's'", (bci,))
    if width_mm is not None and height_mm is not None:
        return _calc(width_mm, height_mm)

    return None, None, None, None

def create_detal_session(cursor, detal, ip, gr, bci, gri, perimeter, area):
    """Создать запись о регистрации детали (открытая сессия)."""
    cursor.execute(
        "INSERT INTO DETAL_TIME (IP, DETAL, TIME_START_D, TIME_END_D, GR, BCI, GRI, PP, SS) "
        "VALUES (%s, %s, NOW(), NULL, %s, %s, %s, %s, %s)",
        (ip, detal, gr, bci, gri, perimeter, area)
    )

def get_stats_for_shift(cursor, ip):
    """Статистика за сегодня: кол-во изделий, суммарный периметр и площадь."""
    cursor.execute(
        "SELECT COUNT(DISTINCT BCI), SUM(PP), SUM(SS) "
        "FROM DETAL_TIME "
        "WHERE IP = %s AND DATE(TIME_START_D) = CURDATE() AND BCI IS NOT NULL",
        (ip,)
    )
    row = cursor.fetchone()
    count           = row[0] if row[0] is not None else 0
    total_perimeter = row[1] if row[1] is not None else 0.0
    total_area      = row[2] if row[2] is not None else 0.0
    return count, total_perimeter, total_area
