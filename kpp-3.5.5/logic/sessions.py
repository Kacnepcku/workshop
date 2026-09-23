# -*- coding: utf-8 -*-

"""
sessions.py — чистая бизнес-логика сессий сотрудников и деталей.

Функции здесь не знают ни про Tkinter, ни про MySQL: они принимают данные
и возвращают решения («что сделать и что сказать оператору»). Менеджеры UI
(WorkerSessionManager / DetalProcessor) лишь исполняют эти решения через db.py.
Это делает правила тестируемыми юнит-тестами.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import config
from db import DetalInfo, WorkplaceInfo
from logic.workplace_policy import WorkplacePolicy


# --------------------------------------------------------------------------- #
#  Сценарии сканирования сотрудника                                             #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WorkerAction:
    """Решение по результату сканирования бейджа сотрудника."""
    kind: str                 # 'stop' | 'move' | 'register' | 'not_found'
    message: Optional[str] = None
    level: str = "info"


def decide_worker_action(rab: int, current_ip: int,
                         open_session_ip: Optional[int]) -> WorkerAction:
    """
    Открытая сессия на этом же месте → остановка;
    на другом месте → перемещение; нет сессии → регистрация.
    """
    if open_session_ip is None:
        return WorkerAction(kind="register")
    if open_session_ip == current_ip:
        return WorkerAction(kind="stop")
    return WorkerAction(kind="move")


def check_capacity(info: WorkplaceInfo) -> Optional[str]:
    """Сообщение-предупреждение, если место заполнено (None — можно)."""
    if info.rab_cur >= info.rab_max:
        return (f"Место '{info.name}' заполнено (занято {info.rab_cur} из "
                f"{info.rab_max}).")
    return None


# --------------------------------------------------------------------------- #
#  Сценарии сканирования детали                                                 #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DetalDecision:
    """Вердикт валидации сканируемой детали до обращения к БД-дублям."""
    allowed: bool
    message: Optional[str] = None
    level: str = "warn"


def validate_detal(info: DetalInfo, policy: WorkplacePolicy,
                   impost_gri: str) -> DetalDecision:
    """Импост игнорируется; неразрешённая для места группа — отказ."""
    if info.gri == impost_gri:
        return DetalDecision(
            allowed=False, level="warn",
            message="Для регистрации отсканируйте деталь рамы или створки. "
                    "Импост не регистрируется.")
    if not policy.allows(info.gri):
        group_names = {config.GRI_FRAME: "РАМЫ", config.GRI_SASH: "СТВОРКИ"}
        scanned = group_names.get(info.gri, info.gri)
        return DetalDecision(
            allowed=False, level="warn",
            message=f"На данном рабочем месте разрешена регистрация только "
                    f"{policy.allowed_names}, а вы сканируете {scanned}.")
    return DetalDecision(allowed=True)


def duplicate_message(bci: str, gri: str, workplace_name: str,
                      by_bci_only: bool) -> str:
    """Текст предупреждения о дубликате (BCI целиком или BCI+GRI)."""
    if by_bci_only:
        return (f"Изделие с BCI={bci} уже зарегистрировано на "
                f"{workplace_name} (другая деталь). "
                f"Регистрация новой детали невозможна.")
    return (f"Изделие (BCI={bci}, тип={gri}) уже зарегистрировано на "
            f"{workplace_name} (другая деталь). "
            f"Регистрация новой детали невозможна.")


def registered_message(detal: str, info: DetalInfo,
                       workplace_name: str) -> str:
    return (f"Деталь {detal} (ZAKNUM:{info.zaknum}) уже зарегистрирована "
            f"на {workplace_name}.")


def missing_dimensions_message(show_product: bool) -> str:
    if show_product:
        return ("Не удалось определить габариты изделия "
                "(нет ни рамы, ни створки с ORIENT='Н' или 'П').")
    return ("Не удалось определить габариты изделия "
            "(нет ORIENT='Н' или 'П').")
