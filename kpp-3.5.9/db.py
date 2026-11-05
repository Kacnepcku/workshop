#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

"""
db.py — функции для работы с базой данных MySQL.

Все запросы выполняются через переданный cursor.
Commit/rollback делает вызывающая сторона.
"""
import math    # ← для расчёта площади полукруга

# Сотрудники и рабочие места ======================================================
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
    """
    Получить информацию о рабочем месте: NAME, RAB_MAX, GR.
    Поле RAB_CUR больше не читается из WORKPLACE —
    актуальное количество считается отдельно (см. get_occupied_count).
    """
    cursor.execute(
        "SELECT NAME, RAB_MAX, GR FROM WORKPLACE WHERE IP = %s",
        (ip,)
    )
    return cursor.fetchone()

def get_occupied_count(cursor, ip):
    """Количество открытых сессий на данном IP за сегодня (аналог RAB_CUR)."""
    cursor.execute(
        "SELECT COUNT(*) FROM WORKER_TIME "
        "WHERE IP = %s AND TIME_END_W IS NULL "
        "AND DATE(TIME_START_W) = CURDATE()",
        (ip,)
    )
    return cursor.fetchone()[0]

def get_open_session(cursor, rab):
    """Найти открытую сессию сотрудника за сегодня."""
    cursor.execute(
        "SELECT IP, TIME_START_W FROM WORKER_TIME "
        "WHERE RAB = %s AND DATE(TIME_START_W) = CURDATE() AND TIME_END_W IS NULL",
        (rab,)
    )
    return cursor.fetchone()

def close_session(cursor, rab):
    """Закрыть текущую открытую сессию сотрудника за сегодня (TIME_END_W = NOW())."""
    cursor.execute(
        "UPDATE WORKER_TIME SET TIME_END_W = NOW() "
        "WHERE RAB = %s AND DATE(TIME_START_W) = CURDATE() AND TIME_END_W IS NULL",
        (rab,)
    )

def get_stale_sessions(cursor, ip=None, rab=None):
    """
    Найти незакрытые сессии за предыдущие дни (до полуночи сегодняшнего дня).
    Можно фильтровать по IP рабочего места и/или по табельному номеру RAB.
    """
    query = (
        "SELECT RAB, IP, TIME_START_W FROM WORKER_TIME "
        "WHERE TIME_END_W IS NULL AND DATE(TIME_START_W) < CURDATE()"
    )
    params = []
    if ip is not None:
        query += " AND IP = %s"
        params.append(ip)
    if rab is not None:
        query += " AND RAB = %s"
        params.append(rab)

    cursor.execute(query, tuple(params))
    return cursor.fetchall()

def close_stale_session(cursor, rab, ip, start_time, close_time):
    """Точечно закрыть конкретную зависшую сессию."""
    cursor.execute(
        "UPDATE WORKER_TIME SET TIME_END_W = %s "
        "WHERE RAB = %s AND IP = %s AND TIME_START_W = %s AND TIME_END_W IS NULL",
        (close_time, rab, ip, start_time)
    )

def create_session(cursor, rab, ip):
    """Создать новую сессию для сотрудника на данном рабочем месте."""
    cursor.execute(
        "INSERT INTO WORKER_TIME (RAB, IP, TIME_START_W, TIME_END_W) "
        "VALUES (%s, %s, NOW(), NULL)",
        (rab, ip)
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

# Детали и статистика ==============================================================
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
    !!!!!!!!!!!! ВНИАНИЕ 'В' 'П' 'Н' ЭТО КИРИЛЛИЦА !!!!!!!!!!!!!!!!!!!!!!!!!!!

    Возвращает (ширина_мм, высота_мм, периметр_м, площадь_м2) для BCI и группы.

    ─── Прямоугольное изделие ───
    • ширина  = длина детали ORIENT='В' (верхняя рама/створка)
    • высота  = длина детали ORIENT='П' (правая боковая)
    • периметр = 2 × (w + h)
    • площадь  = w × h

    ─── Полукруглое изделие ───
    Условие: нет ORIENT='П', но есть верхняя деталь с DUGA=1 и есть ORIENT='Н'.
    • периметр = L(Н) + L(В)
    • площадь  = L(Н)² × π / 8
    • возвращаем (L(Н), L(В), периметр, площадь) —
        в UI «ширина» = основание, «высота» = дуга.

    Из каждой длины вычитается 6 мм, потом перевод в метры.

    Если gri не задан — сначала ищет раму (GRI='r'), затем створку (GRI='s').
    """

    # ---------- БЛОК РАСЧЁТА: прямоугольник ----------
    def _calc_rect(width_mm, height_mm):
        w_m = (width_mm - 6) / 1000.0
        h_m = (height_mm - 6) / 1000.0
        return width_mm, height_mm, 2 * (w_m + h_m), w_m * h_m

    # ---------- БЛОК РАСЧЁТА: полукруг ----------
    def _calc_arc(bottom_mm, top_mm):
        """
        Полукруг:
            периметр = L(Н) + L(В)              [в метрах после −6 мм]
            площадь  = L(Н)² × π / 8            [в м² после −6 мм]
        Для UI: width_mm = L(Н), height_mm = L(В).
        """
        lb_m = (bottom_mm - 6) / 1000.0
        lt_m = (top_mm - 6) / 1000.0
        perimeter = lb_m + lt_m
        area = (lb_m ** 2) * math.pi / 8
        return bottom_mm, top_mm, perimeter, area

    # ---------- Проверка DUGA=1 (учитывает None / '1' / 1 / '\N') ----------
    def _is_duga(duga):
        if duga is None:
            return False
        try:
            return int(duga) == 1
        except (ValueError, TypeError):
            return False

    # ---------- Запрос: берём все три ориентации + DUGA ----------
    def _query(where_gri_clause, params):
        """
        Возвращает (width_mm, height_mm, bottom_mm, top_duga).
        width_mm  — L(В)
        height_mm — L(П)
        bottom_mm — L(Н)
        top_duga  — True, если у верхней детали DUGA=1
        """
        cursor.execute(
            "SELECT ORIENT, LENGTH, DUGA FROM CCALC "
            f"WHERE BCI = %s AND {where_gri_clause} "
            "AND ORIENT IN ('В', 'П', 'Н')",
            params
        )
        width_mm = height_mm = bottom_mm = None
        top_duga = False
        for orient, length, duga in cursor.fetchall():
            if orient == 'В':
                width_mm = length
                if _is_duga(duga):
                    top_duga = True
            elif orient == 'П':
                height_mm = length
            elif orient == 'Н':
                bottom_mm = length
        return width_mm, height_mm, bottom_mm, top_duga

    # ---------- Общая логика выбора формулы ----------
    def _compute(where_gri_clause, params):
        width_mm, height_mm, bottom_mm, top_duga = _query(where_gri_clause, params)

        # 1) Прямоугольник: есть и верх, и право
        if width_mm is not None and height_mm is not None:
            return _calc_rect(width_mm, height_mm)

        # 2) Полукруг: нет права, но верх с DUGA=1 и есть низ
        if top_duga and width_mm is not None and bottom_mm is not None:
            return _calc_arc(bottom_mm, width_mm)

        # 3) Иначе данных недостаточно
        return None, None, None, None

    # ---------- Явно указанная группа (для GR 1–4) ----------
    if gri is not None:
        result = _compute("GRI = %s", (bci, gri))
        return result if result[0] is not None else (None, None, None, None)

    # ---------- Группа не указана (для GR 5–6): рама → створка ----------
    result = _compute("GRI = 'r'", (bci,))
    if result[0] is not None:
        return result

    result = _compute("GRI = 's'", (bci,))
    if result[0] is not None:
        return result

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

def get_last_detal_time_on_ip(cursor, ip, target_date=None):
    """
    Время последней зарегистрированной детали на указанном IP.

    target_date=None  → за сегодня (DATE = CURDATE())
    target_date=date  → за указанную дату

    Возвращает datetime или None, если деталей не было.
    """
    if target_date is None:
        cursor.execute(
            "SELECT MAX(TIME_START_D) FROM DETAL_TIME "
            "WHERE IP = %s AND DATE(TIME_START_D) = CURDATE()",
            (ip,)
        )
    else:
        cursor.execute(
            "SELECT MAX(TIME_START_D) FROM DETAL_TIME "
            "WHERE IP = %s AND DATE(TIME_START_D) = %s",
            (ip, target_date)
        )
    row = cursor.fetchone()
    return row[0] if row and row[0] else None

def close_sessions_on_ip_at_time(cursor, ip, close_time):
    """
    Закрывает ВСЕ открытые сессии на указанном IP временем close_time.

    Если close_time окажется меньше TIME_START_W конкретной сессии,
    для неё применяется TIME_START_W (чтобы не получить отрицательное время).

    Возвращает количество закрытых записей.
    """
    cursor.execute(
        "UPDATE WORKER_TIME SET TIME_END_W = "
        "  CASE WHEN %s < TIME_START_W THEN TIME_START_W ELSE %s END "
        "WHERE IP = %s AND TIME_END_W IS NULL",
        (close_time, close_time, ip)
    )
    return cursor.rowcount