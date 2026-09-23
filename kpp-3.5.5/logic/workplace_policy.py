# -*- coding: utf-8 -*-

"""
workplace_policy.py — политики рабочих мест (чистая логика, тестируется без UI/БД).

Ранее поведение зашивалось ветвлениями вида `if gr in (5, 6)` и словарём
allowed_gri прямо в UIBuilder/DetalProcessor. Теперь каждая группа мест (GR)
описана одной записью WORKPLACE_POLICIES.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional

import config


@dataclass(frozen=True)
class WorkplacePolicy:
    """Что разрешено и как проверяются дубли на рабочем месте группы GR."""
    allowed_gri: FrozenSet[str] = field(default_factory=frozenset)
    # Проверять дубли по всему BCI (места 5-6 собирают и рамы, и створки),
    # а не по паре BCI+GRI:
    dup_check_by_bci_only: bool = False
    # Показывать габариты изделия «целиком» (рама → створка), а не детали:
    show_product_dimensions: bool = False

    def allows(self, gri: str) -> bool:
        return gri in self.allowed_gri

    @property
    def allowed_names(self) -> str:
        names = {config.GRI_FRAME: "РАМЫ", config.GRI_SASH: "СТВОРКИ"}
        parts = [names[g] for g in sorted(self.allowed_gri) if g in names]
        if not parts:
            return "регистрация деталей не разрешена"
        return " и ".join(parts)


WORKPLACE_POLICIES: Dict[int, WorkplacePolicy] = {
    1: WorkplacePolicy(frozenset({config.GRI_FRAME})),
    2: WorkplacePolicy(frozenset({config.GRI_FRAME})),
    3: WorkplacePolicy(frozenset({config.GRI_SASH})),
    4: WorkplacePolicy(frozenset({config.GRI_SASH})),
    5: WorkplacePolicy(frozenset({config.GRI_FRAME, config.GRI_SASH}),
                       dup_check_by_bci_only=True,
                       show_product_dimensions=True),
    6: WorkplacePolicy(frozenset({config.GRI_FRAME, config.GRI_SASH}),
                       dup_check_by_bci_only=True,
                       show_product_dimensions=True),
}

DEFAULT_POLICY = WorkplacePolicy()  # ничего не разрешено


def get_policy(gr: Optional[int]) -> WorkplacePolicy:
    """Политика для группы рабочего места (неизвестная группа — запрет)."""
    if gr is None:
        return DEFAULT_POLICY
    return WORKPLACE_POLICIES.get(gr, DEFAULT_POLICY)


def detals_type_text(gri: str) -> str:
    """Подпись типа детали для панели информации."""
    if gri == config.GRI_FRAME:
        return "Тип: РАМА"
    if gri == config.GRI_SASH:
        return "Тип: СТВОРКА"
    if gri == config.GRI_IMPOST:
        return "Тип: ИМПОСТ"
    return f"Тип: {gri}"


def product_group_order() -> List[str]:
    """Порядок поиска габаритов изделия целиком: сначала рама, потом створка."""
    return [config.GRI_FRAME, config.GRI_SASH]
