from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import BuildingStock, GlobalStock, StockTransaction


@dataclass(frozen=True)
class StockDelta:
    """Удобно для отладки / логов."""
    global_before: int
    global_after: int
    building_before: int
    building_after: int


@transaction.atomic
def apply_transaction(tx: StockTransaction) -> StockDelta:
    """
    Применяет транзакцию к остаткам:
      - GlobalStock (по школе)
      - BuildingStock (по корпусу)

    Ожидания по полям:
      - tx.cartridge обязателен
      - tx.on_balance определяет «на балансе / нет»
      - tx.building:
          * для IN — корпус, куда поступило (склад)
          * для OUT — корпус, с чьего склада выдали (склад)
    """
    if not tx.cartridge_id:
        raise ValidationError("В транзакции не указан картридж (cartridge).")

    if not tx.building_id:
        raise ValidationError("В транзакции не указан корпус склада (building).")

    if tx.qty <= 0:
        raise ValidationError("Количество должно быть больше 0.")

    flag = bool(tx.on_balance)

    g, _ = GlobalStock.objects.select_for_update().get_or_create(
        cartridge_id=tx.cartridge_id,
        on_balance=flag,
        defaults={"qty": 0},
    )
    b, _ = BuildingStock.objects.select_for_update().get_or_create(
        building_id=tx.building_id,
        cartridge_id=tx.cartridge_id,
        on_balance=flag,
        defaults={"qty": 0},
    )

    gb = g.qty
    bb = b.qty

    if tx.tx_type == StockTransaction.Type.IN:
        g.qty = gb + tx.qty
        b.qty = bb + tx.qty

    elif tx.tx_type == StockTransaction.Type.OUT:
        if gb < tx.qty:
            raise ValidationError(
                f"Недостаточно картриджей в общем остатке: есть {gb}, нужно {tx.qty}."
            )
        if bb < tx.qty:
            raise ValidationError(
                f"Недостаточно картриджей на складе корпуса: есть {bb}, нужно {tx.qty}."
            )
        g.qty = gb - tx.qty
        b.qty = bb - tx.qty

    else:
        raise ValidationError("Неизвестный тип транзакции.")

    g.save(update_fields=["qty"])
    b.save(update_fields=["qty"])

    return StockDelta(
        global_before=gb,
        global_after=g.qty,
        building_before=bb,
        building_after=b.qty,
    )