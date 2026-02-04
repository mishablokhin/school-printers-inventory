from django.db import transaction
from django.db.models import F

from .models import GlobalStock, BuildingStock, StockTransaction


@transaction.atomic
def apply_transaction(tx: StockTransaction):
    # Глобальный остаток
    gs, _ = GlobalStock.objects.select_for_update().get_or_create(cartridge=tx.cartridge)

    # Остаток корпуса (если задан корпус)
    bs = None
    if tx.building_id:
        bs, _ = BuildingStock.objects.select_for_update().get_or_create(
            building=tx.building, cartridge=tx.cartridge
        )

    if tx.tx_type == StockTransaction.Type.IN:
        gs.qty = F("qty") + tx.qty
        gs.save(update_fields=["qty"])
        if bs:
            bs.qty = F("qty") + tx.qty
            bs.save(update_fields=["qty"])
        return

    # OUT
    # списываем из глобального
    if gs.qty < tx.qty:
        raise ValueError("Недостаточно картриджей в общем остатке.")
    gs.qty = F("qty") - tx.qty
    gs.save(update_fields=["qty"])

    # и из остатка корпуса (если ведём корпусной склад)
    if bs:
        if bs.qty < tx.qty:
            raise ValueError("Недостаточно картриджей в остатке корпуса.")
        bs.qty = F("qty") - tx.qty
        bs.save(update_fields=["qty"])