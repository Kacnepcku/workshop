#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

from datetime import datetime
from typing import Optional
from config import AppConfig
from database.connection import Database, DatabaseError
from database.repository import WorkshopRepository
from models import Workplace, WorkerSession, ActionResult
from log import log_message


class WorkerService:
    """Бизнес-логика учёта рабочего времени и контроля простоя."""

    def __init__(self, db: Database, repo: WorkshopRepository, cfg: AppConfig):
        self.db = db
        self.repo = repo
        self.cfg = cfg

    def get_workplace(self, ip: int) -> Optional[Workplace]:
        with self.db.transaction() as cursor:
            return self.repo.get_workplace_info(cursor, ip)

    def get_dashboard_data(self, ip: int) -> tuple[list[WorkerSession], int]:
        """Возвращает (список активных сотрудников, количество занятых мест)."""
        with self.db.transaction() as cursor:
            workers = self.repo.get_current_workers(cursor, ip)
            occupied = self.repo.get_occupied_count(cursor, ip)
            return workers, occupied

    def handle_worker_scan(self, rab: str, workplace: Workplace) -> ActionResult:
        """Регистрирует приход, уход или перемещение сотрудника."""
        try:
            with self.db.transaction() as cursor:
                fio = self.repo.get_worker_fio(cursor, rab)
                if fio is None:
                    return ActionResult(
                        success=False,
                        message=f"Работник с кодом {rab} не найден в базе.",
                        level="error",
                    )

                # Закрываем зависшие сессии этого сотрудника со вчерашнего дня
                self._close_stale_in_cursor(cursor, rab=rab, silent=True)

                open_session = self.repo.get_open_session(cursor, rab)
                if open_session:
                    old_ip, _ = open_session
                    if old_ip == workplace.ip:
                        self.repo.close_session(cursor, rab)
                        return ActionResult(
                            success=True,
                            message=f"Работник {fio} завершил работу на {workplace.name}.",
                        )
                    return self._move_worker(cursor, rab, fio, old_ip, workplace)

                return self._register_worker(cursor, rab, fio, workplace)

        except DatabaseError as e:
            return ActionResult(False, str(e), level="error")
        except Exception as e:
            log_message(f"Ошибка обработки сотрудника {rab}: {e}")
            return ActionResult(False, f"Ошибка обработки сотрудника: {e}", level="error")

    def _move_worker(
        self, cursor, rab: str, fio: str, old_ip: int, target: Workplace
    ) -> ActionResult:
        cur_occupied = self.repo.get_occupied_count(cursor, target.ip)
        if cur_occupied >= target.rab_max:
            return ActionResult(
                success=False,
                message=(
                    f"Место '{target.name}' заполнено (занято {cur_occupied} из "
                    f"{target.rab_max}). Перемещение невозможно."
                ),
                level="warn",
            )

        old_place_name = self.repo.get_workplace_name(cursor, old_ip)
        self.repo.close_session(cursor, rab)
        self.repo.create_session(cursor, rab, target.ip)
        return ActionResult(
            success=True,
            message=f"Работник {fio} перемещён с '{old_place_name}' на '{target.name}'.",
        )

    def _register_worker(
        self, cursor, rab: str, fio: str, target: Workplace
    ) -> ActionResult:
        cur_occupied = self.repo.get_occupied_count(cursor, target.ip)
        if cur_occupied >= target.rab_max:
            return ActionResult(
                success=False,
                message=(
                    f"Место '{target.name}' заполнено (занято {cur_occupied} из "
                    f"{target.rab_max}). Регистрация невозможна."
                ),
                level="warn",
            )

        self.repo.create_session(cursor, rab, target.ip)
        return ActionResult(
            success=True,
            message=f"Работник {fio} зарегистрирован на {target.name}.",
        )

    def close_stale_sessions(
        self, ip: Optional[int] = None, rab: Optional[str] = None, silent: bool = False
    ) -> int:
        """Закрывает зависшие сессии за предыдущие дни."""
        try:
            with self.db.transaction() as cursor:
                return self._close_stale_in_cursor(cursor, ip=ip, rab=rab, silent=silent)
        except Exception as e:
            log_message(f"Не удалось закрыть предыдущие сессии: {e}")
            return 0

    def _close_stale_in_cursor(
        self, cursor, ip: Optional[int] = None, rab: Optional[str] = None, silent: bool = False
    ) -> int:
        sessions = self.repo.get_stale_sessions(cursor, ip=ip, rab=rab)
        if not sessions:
            if not silent:
                log_message("Нет зависших сессий сотрудников за предыдущие дни.")
            return 0

        for s in sessions:
            last_detal = self.repo.get_last_detal_time_on_ip(
                cursor, s.ip, s.start_time.date()
            )
            if last_detal and last_detal >= s.start_time:
                close_time = last_detal
            else:
                close_time = s.start_time.replace(hour=18, minute=0, second=0, microsecond=0)
                if s.start_time > close_time:
                    close_time = s.start_time

            self.repo.close_stale_session(cursor, s, close_time)
            log_message(
                f"Закрыта сессия сотрудника {s.rab} на IP {s.ip} "
                f"(старт {s.start_time}, окончание {close_time})"
            )

        log_message(f"Закрыто {len(sessions)} сессий за предыдущие дни")
        return len(sessions)

    def close_all_on_workplace(self, workplace: Workplace) -> None:
        """Закрывает все сессии на рабочем месте при ручном выключении ПК."""
        try:
            with self.db.transaction() as cursor:
                closed = self.repo.close_all_sessions_on_ip_now(cursor, workplace.ip)
                log_message(f"Закрыто {closed} сессий на рабочем месте {workplace.name}")
        except Exception as e:
            log_message(f"Ошибка закрытия сессий при выключении: {e}")

    def check_idle_and_close_if_needed(self, ip: int) -> bool:
        """
        Проверяет простой после 17:00.
        Возвращает True, если простой превысил лимит, сессии закрыты и пора выключать ПК.
        """
        now = datetime.now()
        if now.hour < self.cfg.idle_after_hour:
            return False

        try:
            with self.db.transaction() as cursor:
                open_sessions = self.repo.get_open_sessions_on_ip(cursor, ip)
                if not open_sessions:
                    return False

                last_detal = self.repo.get_last_detal_time_on_ip(cursor, ip)
                if last_detal:
                    last_activity = close_time = last_detal
                    base_desc = f"последняя деталь {last_detal}"
                else:
                    oldest_start = min(start for _, start in open_sessions)
                    last_activity = close_time = oldest_start
                    base_desc = f"нет деталей, старт сессии {oldest_start}"

                idle_seconds = (now - last_activity).total_seconds()
                if idle_seconds >= self.cfg.idle_timeout_sec:
                    log_message(
                        f"Простой {(idle_seconds // 60):.0f} мин ({base_desc}). "
                        f"Принудительное закрытие сессий на IP {ip} временем {close_time}."
                    )
                    closed = self.repo.close_sessions_on_ip_at_time(cursor, ip, close_time)
                    log_message(f"Закрыто {closed} сессий на IP {ip}")
                    return True

        except Exception as e:
            log_message(f"Ошибка проверки простоя: {e}")

        return False
