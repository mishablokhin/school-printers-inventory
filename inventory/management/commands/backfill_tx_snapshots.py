from django.core.management.base import BaseCommand
from django.db import transaction, models

from inventory.models import StockTransaction


class Command(BaseCommand):
    help = "Заполняет snapshot-поля в StockTransaction для уже созданных записей."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Не сохранять изменения, только показать сколько записей будет обновлено",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Ограничить количество обновляемых записей (0 = без ограничения)",
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        limit = int(options["limit"] or 0)

        qs = (
            StockTransaction.objects
            .select_related(
                "building",
                "printer",
                "printer__printer_model",
                "printer__room",
                "printer__room__building",
            )
            .order_by("id")
        )

        # обновляем только те, где есть пустые snapshot-поля
        qs = qs.filter(
            # хотя бы одно из важного пустое
            # (для IN достаточно building_snapshot, для OUT – несколько полей)
            # делаем шире, чтобы дозаполнить всё аккуратно
            models.Q(building_snapshot="") |
            models.Q(room_snapshot="") |
            models.Q(printer_model_snapshot="") |
            models.Q(issued_to_snapshot="")
        )

        if limit > 0:
            qs = qs[:limit]

        updated = 0
        checked = 0

        self.stdout.write(self.style.NOTICE("Backfill snapshot-полей..."))

        try:
            with transaction.atomic():
                for tx in qs:
                    checked += 1
                    changed = False

                    # IN: корпус обычно в tx.building
                    if not tx.building_snapshot:
                        if tx.tx_type == StockTransaction.Type.IN:
                            if tx.building:
                                tx.building_snapshot = tx.building.name
                                changed = True
                        else:
                            # OUT: приоритет — корпус из printer.room.building
                            if tx.printer and tx.printer.room and tx.printer.room.building:
                                tx.building_snapshot = tx.printer.room.building.name
                                changed = True
                            elif tx.building:
                                tx.building_snapshot = tx.building.name
                                changed = True

                    if tx.tx_type == StockTransaction.Type.OUT:
                        # кабинет
                        if not tx.room_snapshot and tx.printer and tx.printer.room:
                            tx.room_snapshot = tx.printer.room.number or ""
                            changed = True

                        # модель принтера
                        if not tx.printer_model_snapshot and tx.printer and tx.printer.printer_model:
                            pm = tx.printer.printer_model
                            tx.printer_model_snapshot = f"{pm.vendor} {pm.model}".strip()
                            changed = True

                        # инв. номер
                        if not tx.printer_inventory_tag_snapshot and tx.printer:
                            tx.printer_inventory_tag_snapshot = tx.printer.inventory_tag or ""
                            changed = True

                        # кому выдали (у тебя уже есть issued_to – можно зафиксировать его)
                        if not tx.issued_to_snapshot:
                            if tx.issued_to:
                                tx.issued_to_snapshot = tx.issued_to
                                changed = True
                            elif tx.printer and tx.printer.room and tx.printer.room.owner_name:
                                tx.issued_to_snapshot = tx.printer.room.owner_name
                                changed = True

                    # IN: issued_to/printer/room обычно не нужны, оставим как есть

                    if changed:
                        updated += 1
                        if not dry_run:
                            tx.save(update_fields=[
                                "building_snapshot",
                                "room_snapshot",
                                "printer_model_snapshot",
                                "printer_inventory_tag_snapshot",
                                "issued_to_snapshot",
                            ])

                if dry_run:
                    # откатываем транзакцию, чтобы ничего не записалось
                    raise RuntimeError("DRY_RUN_ROLLBACK")

        except RuntimeError as e:
            if str(e) != "DRY_RUN_ROLLBACK":
                raise

        self.stdout.write(self.style.SUCCESS(
            f"Проверено: {checked}. Будет обновлено: {updated}. {'(dry-run)' if dry_run else ''}"
        ))