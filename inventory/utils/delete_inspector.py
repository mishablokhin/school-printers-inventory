# inventory/utils/delete_inspector.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Type

from django.db import router
from django.db.models import Model
from django.db.models.deletion import Collector, ProtectedError


@dataclass
class DeleteBlocker:
    title: str
    details: str
    actions: List[str]


@dataclass
class DeleteReport:
    can_delete: bool
    consequences: List[str]
    blockers: List[DeleteBlocker]


def _count_protected(collector: Collector) -> Dict[Type[Model], int]:
    counts: Dict[Type[Model], int] = {}
    # collector.protected может быть set объектов; считаем по классам
    for obj in getattr(collector, "protected", []) or []:
        cls = obj.__class__
        counts[cls] = counts.get(cls, 0) + 1
    return counts


def build_delete_report(obj: Model) -> DeleteReport:
    using = router.db_for_write(obj.__class__)
    collector = Collector(using=using)

    try:
        collector.collect([obj])
        protected_counts = _count_protected(collector)
        can_delete = len(getattr(collector, "protected", []) or []) == 0
    except ProtectedError:
        # ✅ На некоторых версиях Django collect() может бросать ProtectedError.
        # Для нас это просто "удалять нельзя".
        protected_counts = {}
        can_delete = False

    consequences: List[str] = ["Удаление необратимо."]
    blockers: List[DeleteBlocker] = []

    from inventory.models import (
        Building, Room, PrinterModel, CartridgeModel, Printer,
        StockTransaction
    )

    if can_delete:
        if isinstance(obj, CartridgeModel):
            consequences.extend([
                "Будут очищены остатки этого картриджа по всем корпусам (склады).",
                "Будут очищены глобальные остатки этого картриджа (на балансе / не на балансе).",
                "Будет удалена история приходов/выдач этого картриджа (записи журнала).",
                "Точность учёта по данному картриджу будет потеряна.",
            ])
        elif isinstance(obj, Building):
            consequences.extend([
                "Будут удалены кабинеты этого корпуса (каскадом).",
                "Будут удалены складские остатки по этому корпусу (каскадом).",
            ])
        elif isinstance(obj, Room):
            consequences.append("Кабинет будет удалён. Если в нём есть принтеры — удаление будет запрещено.")
        elif isinstance(obj, PrinterModel):
            consequences.extend([
                "Модель будет удалена из системы.",
                "Связи совместимости с картриджами будут удалены.",
                "Если есть принтеры с этой моделью — удаление будет запрещено.",
            ])
        elif isinstance(obj, Printer):
            consequences.extend([
                "Принтер будет удалён из системы.",
                "Если в журнале есть записи, ссылающиеся на принтер — удаление будет запрещено.",
            ])
        else:
            consequences.append("Будут удалены связанные данные согласно правилам связей в базе данных.")
    else:
        # Если collect() упал или protected есть — формируем универсальные блокеры
        blockers.append(DeleteBlocker(
            title="Есть связанные записи",
            details="Объект используется в других сущностях системы, поэтому удаление запрещено (PROTECT).",
            actions=[
                "Сначала удалите/перенесите связанные объекты (например, принтеры из кабинета).",
                "Затем повторите удаление.",
            ],
        ))

    return DeleteReport(
        can_delete=can_delete,
        consequences=consequences if can_delete else [],
        blockers=blockers if not can_delete else [],
    )


def get_deleteability_map(items: Iterable[Model]) -> Dict[int, bool]:
    items = list(items)
    if not items:
        return {}

    using = router.db_for_write(items[0].__class__)
    result: Dict[int, bool] = {}

    for obj in items:
        collector = Collector(using=using)
        try:
            collector.collect([obj])
            result[obj.pk] = len(getattr(collector, "protected", []) or []) == 0
        except ProtectedError:
            # ✅ Важно: НЕ падать на списках.
            result[obj.pk] = False

    return result