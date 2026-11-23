#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

from datetime import date, datetime
from typing import Optional
from models import (
    Workplace,
    WorkerSession,
    StaleSession,
    Detal,
    Dimensions,
    ShiftStats,
    DetailGroup,
)


class WorkshopRepository:
    """Слой доступа к данным MySQL (чистый SQL без логики UI)."""

    # === Сотрудники и рабочие места ==========================================

    def get_worker_fio(self, cursor, rab: str) -> Optional[str]:
        cursor.execute("SELECT FIO FROM WORKER WHERE RAB = %s", (rab,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_workplace_name(self, cursor, ip: int) -> str:
        cursor.execute("SELECT NAME FROM WORKPLACE WHERE IP = %s", (ip,))
        row = cursor.fetchone()
        return row[0] if row else str(ip)

    def get_workplace_info(self, cursor, ip: int) -> Optional[Workplace]:
        cursor.execute(
            "SELECT NAME, RAB_MAX, GR FROM WORKPLACE WHERE IP = %s",
            (ip,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return Workplace(ip=ip, name=row[0], rab_max=row[1], gr=row[2])

    def get_occupied_count(self, cursor, ip: int) -> int:
        cursor.execute(
            "SELECT COUNT(*) FROM WORKER_TIME "
            "WHERE IP = %s AND TIME_END_W IS NULL "
            "AND DATE(TIME_START_W) = CURDATE()",
            (ip,),
        )
        return cursor.fetchone()[0]

    def get_open_session(self, cursor, rab: str) -> Optional[tuple[int, datetime]]:
        cursor.execute(
            "SELECT IP, TIME_START_W FROM WORKER_TIME "
            "WHERE RAB = %s AND DATE(TIME_START_W) = CURDATE() AND TIME_END_W IS NULL",
            (rab,),
        )
        return cursor.fetchone()

    def get_open_sessions_on_ip(self, cursor, ip: int) -> list[tuple[str, datetime]]:
        """Перенесено из WorkerSessionManager: список (RAB, TIME_START_W) на IP."""
        cursor.execute(
            "SELECT RAB, TIME_START_W FROM WORKER_TIME "
            "WHERE IP = %s AND TIME_END_W IS NULL",
            (ip,),
        )
        return cursor.fetchall()

    def create_session(self, cursor, rab: str, ip: int) -> None:
        cursor.execute(
            "INSERT INTO WORKER_TIME (RAB, IP, TIME_START_W, TIME_END_W) "
            "VALUES (%s, %s, NOW(), NULL)",
            (rab, ip),
        )

    def close_session(self, cursor, rab: str) -> None:
        cursor.execute(
            "UPDATE WORKER_TIME SET TIME_END_W = NOW() "
            "WHERE RAB = %s AND DATE(TIME_START_W) = CURDATE() AND TIME_END_W IS NULL",
            (rab,),
        )

    def close_all_sessions_on_ip_now(self, cursor, ip: int) -> int:
        """Перенесено из WorkerSessionManager.close_all: закрыть все сессии на IP текущим временем."""
        cursor.execute(
            "UPDATE WORKER_TIME SET TIME_END_W = NOW() "
            "WHERE IP = %s AND TIME_END_W IS NULL",
            (ip,),
        )
        return cursor.rowcount

    def close_sessions_on_ip_at_time(self, cursor, ip: int, close_time: datetime) -> int:
        cursor.execute(
            "UPDATE WORKER_TIME SET TIME_END_W = "
            "  CASE WHEN %s < TIME_START_W THEN TIME_START_W ELSE %s END "
            "WHERE IP = %s AND TIME_END_W IS NULL",
            (close_time, close_time, ip),
        )
        return cursor.rowcount

    def get_stale_sessions(
        self, cursor, ip: Optional[int] = None, rab: Optional[str] = None
    ) -> list[StaleSession]:
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
        return [StaleSession(rab=r[0], ip=r[1], start_time=r[2]) for r in cursor.fetchall()]

    def close_stale_session(
        self, cursor, session: StaleSession, close_time: datetime
    ) -> None:
        cursor.execute(
            "UPDATE WORKER_TIME SET TIME_END_W = %s "
            "WHERE RAB = %s AND IP = %s AND TIME_START_W = %s AND TIME_END_W IS NULL",
            (close_time, session.rab, session.ip, session.start_time),
        )

    def get_current_workers(self, cursor, ip: int) -> list[WorkerSession]:
        cursor.execute(
            "SELECT wt.RAB, w.FIO, wt.TIME_START_W, "
            "       (SELECT SUM(TIMESTAMPDIFF(SECOND, TIME_START_W, "
            "                                 IFNULL(TIME_END_W, NOW()))) "
            "        FROM WORKER_TIME "
            "        WHERE RAB = wt.RAB AND DATE(TIME_START_W) = CURDATE()) AS total_sec "
            "FROM WORKER_TIME wt "
            "JOIN WORKER w ON wt.RAB = w.RAB "
            "WHERE wt.IP = %s AND DATE(wt.TIME_START_W) = CURDATE() AND wt.TIME_END_W IS NULL",
            (ip,),
        )
        return [
            WorkerSession(rab=r[0], fio=r[1], start_time=r[2], total_seconds=r[3] or 0)
            for r in cursor.fetchall()
        ]

    # === Детали и статистика =================================================

    def get_detal_full_info(self, cursor, detal_code: str) -> Optional[Detal]:
        cursor.execute(
            "SELECT ZAKNUM, KONNAME, PRIMPROIZV, MATNAME, MATCOLOR, LENGTH, BCI, GRI, KONID "
            "FROM CCALC WHERE DETAL = %s",
            (detal_code,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return Detal(
            code=detal_code,
            zaknum=row[0],
            konname=row[1],
            primproizv=row[2],
            matname=row[3],
            matcolor=row[4],
            length=row[5],
            bci=row[6],
            gri=row[7],
            konid=row[8],
        )

    def is_detal_registered_at_ip(self, cursor, detal_code: str, ip: int) -> bool:
        cursor.execute(
            "SELECT 1 FROM DETAL_TIME "
            "WHERE DETAL = %s AND IP = %s AND TIME_END_D IS NULL LIMIT 1",
            (detal_code, ip),
        )
        return cursor.fetchone() is not None

    def has_open_detal_session(
        self,
        cursor,
        bci: str,
        ip: int,
        gri: Optional[str] = None,
        exclude_detal: Optional[str] = None,
    ) -> bool:
        """Объединенная проверка дублей (по BCI для мест 5-6, или по BCI+GRI для 1-4)."""
        query = (
            "SELECT COUNT(*) FROM DETAL_TIME dt "
            "JOIN CCALC cc ON dt.DETAL = cc.DETAL "
            "WHERE dt.IP = %s AND dt.TIME_END_D IS NULL AND cc.BCI = %s"
        )
        params: list = [ip, bci]

        if gri is not None:
            query += " AND cc.GRI = %s"
            params.append(gri)
        if exclude_detal is not None:
            query += " AND dt.DETAL != %s"
            params.append(exclude_detal)

        cursor.execute(query, tuple(params))
        return cursor.fetchone()[0] > 0

    def get_dimensions(
        self, cursor, bci: str, gri: Optional[str] = None
    ) -> Optional[Dimensions]:
        """
        Рассчитывает габариты изделия (прямоугольник или полукруг).
        ВНИМАНИЕ: 'В', 'П', 'Н' в запросе — кириллица.
        """
        def _is_duga(duga) -> bool:
            if duga is None:
                return False
            try:
                return int(duga) == 1
            except (ValueError, TypeError):
                return False

        def _compute_for_group(target_gri: str) -> Optional[Dimensions]:
            cursor.execute(
                "SELECT ORIENT, LENGTH, DUGA FROM CCALC "
                "WHERE BCI = %s AND GRI = %s AND ORIENT IN ('В', 'П', 'Н')",
                (bci, target_gri),
            )
            width_mm = height_mm = bottom_mm = None
            top_duga = False

            for orient, length, duga in cursor.fetchall():
                if orient == "В":
                    width_mm = length
                    if _is_duga(duga):
                        top_duga = True
                elif orient == "П":
                    height_mm = length
                elif orient == "Н":
                    bottom_mm = length

            if width_mm is not None and height_mm is not None:
                return Dimensions.from_rectangle(width_mm, height_mm)

            if top_duga and width_mm is not None and bottom_mm is not None:
                return Dimensions.from_arc(bottom_mm, width_mm)

            return None

        if gri is not None:
            return _compute_for_group(gri)

        # Для универсальных мест (GR 5-6): сначала пробуем раму, затем створку
        return (
            _compute_for_group(DetailGroup.FRAME.value)
            or _compute_for_group(DetailGroup.SASH.value)
        )

    def create_detal_session(
        self,
        cursor,
        detal: Detal,
        ip: int,
        gr: int,
        dims: Dimensions,
    ) -> None:
        cursor.execute(
            "INSERT INTO DETAL_TIME (IP, DETAL, TIME_START_D, TIME_END_D, GR, BCI, GRI, PP, SS) "
            "VALUES (%s, %s, NOW(), NULL, %s, %s, %s, %s, %s)",
            (ip, detal.code, gr, detal.bci, detal.gri, dims.perimeter_m, dims.area_m2),
        )

    def get_stats_for_shift(self, cursor, ip: int) -> ShiftStats:
        cursor.execute(
            "SELECT COUNT(DISTINCT BCI), SUM(PP), SUM(SS) "
            "FROM DETAL_TIME "
            "WHERE IP = %s AND DATE(TIME_START_D) = CURDATE() AND BCI IS NOT NULL",
            (ip,),
        )
        row = cursor.fetchone()
        if not row:
            return ShiftStats()
        return ShiftStats(
            count=row[0] or 0,
            total_perimeter=float(row[1] or 0.0),
            total_area=float(row[2] or 0.0),
        )

    def get_last_detal_time_on_ip(
        self, cursor, ip: int, target_date: Optional[date] = None
    ) -> Optional[datetime]:
        if target_date is None:
            cursor.execute(
                "SELECT MAX(TIME_START_D) FROM DETAL_TIME "
                "WHERE IP = %s AND DATE(TIME_START_D) = CURDATE()",
                (ip,),
            )
        else:
            cursor.execute(
                "SELECT MAX(TIME_START_D) FROM DETAL_TIME "
                "WHERE IP = %s AND DATE(TIME_START_D) = %s",
                (ip, target_date),
            )
        row = cursor.fetchone()
        return row[0] if row and row[0] else None
