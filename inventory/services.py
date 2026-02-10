from django.db import transaction
from django.db.models import F

from .models import GlobalStock, BuildingStock, StockTransaction


@transaction.atomic
def apply_transaction(tx: StockTransaction):
    # гарантируем строки остатков
    GlobalStock.objects.select_for_update().get_or_create(cartridge=tx.cartridge)

    bs_exists = False
    if tx.building_id:
        BuildingStock.objects.select_for_update().get_or_create(
            building=tx.building, cartridge=tx.cartridge
        )
        bs_exists = True

    if tx.tx_type == StockTransaction.Type.IN:
        GlobalStock.objects.filter(cartridge=tx.cartridge).update(qty=F("qty") + tx.qty)
        if bs_exists:
            BuildingStock.objects.filter(
                building=tx.building, cartridge=tx.cartridge
            ).update(qty=F("qty") + tx.qty)
        return

    # OUT: атомарно списываем (не даём уйти в минус)
    updated = GlobalStock.objects.filter(
        cartridge=tx.cartridge, qty__gte=tx.qty
    ).update(qty=F("qty") - tx.qty)
    if updated == 0:
        raise ValueError("Недостаточно картриджей в общем остатке.")

    if bs_exists:
        updated = BuildingStock.objects.filter(
            building=tx.building, cartridge=tx.cartridge, qty__gte=tx.qty
        ).update(qty=F("qty") - tx.qty)
        if updated == 0:
            # транзакция откатит и глобальное списание тоже
            raise ValueError("Недостаточно картриджей в остатке корпуса.")