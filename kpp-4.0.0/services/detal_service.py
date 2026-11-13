#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

from dataclasses import dataclass
from typing import Optional
from database.connection import Database, DatabaseError
from database.repository import WorkshopRepository
from models import Workplace, Detal, Dimensions, ShiftStats, DetailGroup, ActionResult
from log import log_message


@dataclass(frozen=True)
class DetalDisplayData:
    """Данные для отображения карточки детали и картинки в UI."""
    detal: Detal
    dims: Optional[Dimensions]
    override_type: Optional[str] = None


class DetalService:
    """Бизнес-логика регистрации деталей и расчёта статистики."""

    GROUP_NAMES = {
        DetailGroup.FRAME.value: "РАМЫ",
        DetailGroup.SASH.value: "СТВОРКИ",
    }

    def __init__(self, db: Database, repo: WorkshopRepository):
        self.db = db
        self.repo = repo

    def get_shift_stats(self, ip: int) -> ShiftStats:
        with self.db.transaction() as cursor:
            return self.repo.get_stats_for_shift(cursor, ip)

    def handle_detal_scan(self, code: str, workplace: Workplace) -> ActionResult:
        """
        Обрабатывает сканирование детали.
        В случае успеха или повторного сканирования возвращает DetalDisplayData в payload.
        """
        try:
            with self.db.transaction() as cursor:
                detal = self.repo.get_detal_full_info(cursor, code)
                if detal is None:
                    return ActionResult(
                        success=False,
                        message=f"Деталь с кодом {code} не найдена.",
                        level="error",
                    )

                if detal.is_impost:
                    return ActionResult(
                        success=False,
                        message=(
                            "Для регистрации отсканируйте деталь рамы или "
                            "створки. Импост не регистрируется."
                        ),
                        level="warn",
                    )

                if not workplace.is_group_allowed(detal.gri):
                    allowed_names = (
                        ", ".join(self.GROUP_NAMES.get(g.value, g.value) for g in workplace.allowed_groups)
                        or "не разрешена регистрация деталей"
                    )
                    scanned_name = self.GROUP_NAMES.get(detal.gri, detal.gri)
                    return ActionResult(
                        success=False,
                        message=(
                            f"На данном рабочем месте разрешена регистрация "
                            f"только {allowed_names}, а вы сканируете {scanned_name}."
                        ),
                        level="warn",
                    )

                target_gri = None if workplace.is_universal else detal.gri
                override_type = "Изделие" if workplace.is_universal else None

                # 1. Эта деталь уже была отсканирована на этом рабочем месте —
                # показываем её карточку и чертёж, чтобы работник мог свериться
                if self.repo.is_detal_registered_at_ip(cursor, code, workplace.ip):
                    dims = self.repo.get_dimensions(cursor, detal.bci, target_gri)
                    return ActionResult(
                        success=False,
                        message=(
                            f"Деталь {code} (ZAKNUM:{detal.zaknum}) уже "
                            f"зарегистрирована на {workplace.name}."
                        ),
                        level="warn",
                        payload=DetalDisplayData(detal, dims, override_type),
                    )

                # 2. Другая деталь этого же изделия уже отсканирована
                is_dup = self.repo.has_open_detal_session(
                    cursor,
                    bci=detal.bci,
                    ip=workplace.ip,
                    gri=target_gri,
                    exclude_detal=code,
                )
                if is_dup:
                    dims = self.repo.get_dimensions(cursor, detal.bci, target_gri)
                    if workplace.is_universal:
                        dup_msg = (
                            f"Изделие с BCI={detal.bci} уже зарегистрировано на "
                            f"{workplace.name} (другая деталь). Регистрация новой детали невозможна."
                        )
                    else:
                        dup_msg = (
                            f"Изделие (BCI={detal.bci}, тип={detal.gri}) уже зарегистрировано "
                            f"на {workplace.name} (другая деталь). Регистрация новой детали невозможна."
                        )
                    return ActionResult(
                        success=False,
                        message=dup_msg,
                        level="warn",
                        payload=DetalDisplayData(detal, dims, override_type),
                    )

                # 3. Расчёт габаритов и регистрация
                dims = self.repo.get_dimensions(cursor, detal.bci, target_gri)
                if dims is None:
                    err_msg = (
                        "Не удалось определить габариты изделия (нет ни рамы, ни створки с ORIENT='Н' или 'П')."
                        if workplace.is_universal
                        else "Не удалось определить габариты изделия (нет ORIENT='Н' или 'П')."
                    )
                    return ActionResult(success=False, message=err_msg, level="error")

                self.repo.create_detal_session(cursor, detal, workplace.ip, workplace.gr, dims)
                log_message(
                    f"Деталь {code} зарегистрирована на IP {workplace.ip} "
                    f"(BCI={detal.bci}, GRI={detal.gri})"
                )

                return ActionResult(
                    success=True,
                    message=(
                        f"Зарегистрировано изделие\n"
                        f"Заказ: {detal.zaknum}\n"
                        f"Конструкция: {detal.konname}"
                    ),
                    level="info",
                    timeout_ms=3000,
                    payload=DetalDisplayData(detal, dims, override_type),
                )

        except DatabaseError as e:
            return ActionResult(False, str(e), level="error")
        except Exception as e:
            log_message(f"Ошибка обработки детали {code}: {e}")
            return ActionResult(False, f"Ошибка обработки детали: {e}", level="error")
