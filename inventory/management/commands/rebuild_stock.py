from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventory.models import BuildingStock, GlobalStock, StockTransaction
from inventory.services import apply_transaction


class Command(BaseCommand):
    help = "Пересобирает GlobalStock и BuildingStock по журналу StockTransaction."

    def handle(self, *args, **options):
        qs = StockTransaction.objects.select_related("cartridge", "building").order_by("created_at", "id")

        with transaction.atomic():
            BuildingStock.objects.all().delete()
            GlobalStock.objects.all().delete()

            for tx in qs:
                try:
                    apply_transaction(tx)
                except Exception as e:
                    raise CommandError(f"Ошибка на транзакции id={tx.id}: {e}") from e

        self.stdout.write(self.style.SUCCESS("Остатки успешно пересобраны."))