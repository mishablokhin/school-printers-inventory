from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple, Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db import models
from django.db import transaction as db_transaction

from inventory.models import BuildingStock, GlobalStock, StockTransaction
from inventory.services import apply_transaction


# --- helpers for diff ---------------------------------------------------------

GlobalKey = Tuple[int, bool]                 # (cartridge_id, on_balance)
BuildingKey = Tuple[int, int, bool]          # (building_id, cartridge_id, on_balance)


@dataclass(frozen=True)
class DiffStats:
    added: int
    removed: int
    changed_qty: int

    @property
    def total_affected(self) -> int:
        return self.added + self.removed + self.changed_qty


def _snapshot_global() -> Dict[GlobalKey, int]:
    return {
        (row["cartridge_id"], row["on_balance"]): row["qty"]
        for row in GlobalStock.objects.values("cartridge_id", "on_balance", "qty")
    }


def _snapshot_building() -> Dict[BuildingKey, int]:
    return {
        (row["building_id"], row["cartridge_id"], row["on_balance"]): row["qty"]
        for row in BuildingStock.objects.values("building_id", "cartridge_id", "on_balance", "qty")
    }


def _diff(old: Dict[Tuple, int], new: Dict[Tuple, int]) -> DiffStats:
    old_keys = set(old.keys())
    new_keys = set(new.keys())

    added_keys = new_keys - old_keys
    removed_keys = old_keys - new_keys

    changed_qty = 0
    for k in (old_keys & new_keys):
        if old[k] != new[k]:
            changed_qty += 1

    return DiffStats(
        added=len(added_keys),
        removed=len(removed_keys),
        changed_qty=changed_qty,
    )


def _pretty_flag(on_balance: bool) -> str:
    return "на балансе" if on_balance else "не на балансе"


def _printer_building(tx: StockTransaction):
    # queryset должен быть с select_related printer__room__building, иначе будет N+1
    if tx.printer_id:
        return tx.printer.room.building
    return None


def _effective_building(tx: StockTransaction):
    # приоритет: tx.building (если указан явно), иначе корпус принтера
    return tx.building or _printer_building(tx)


# --- management command -------------------------------------------------------

class Command(BaseCommand):
    help = "Пересобирает GlobalStock и BuildingStock по журналу StockTransaction."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Прогон без сохранения: пересобирает остатки внутри транзакции и откатывает, выводит, что изменится.",
        )
        parser.add_argument(
            "--progress-every",
            type=int,
            default=200,
            help="Печатать прогресс каждые N транзакций (по умолчанию 200).",
        )

    def handle(self, *args, **options):
        dry_run: bool = bool(options["dry_run"])
        progress_every: int = int(options["progress_every"])

        qs = (
            StockTransaction.objects
            .select_related(
                "cartridge",
                "building",
                "printer",
                "printer__room",
                "printer__room__building",
                "created_by",
            )
            .order_by("created_at", "id")
        )

        total = qs.count()
        if total == 0:
            self.stdout.write("В журнале StockTransaction нет записей – пересчитывать нечего.")
            return

        mode = "DRY-RUN (без сохранения)" if dry_run else "LIVE (с сохранением)"
        self.stdout.write(f"=== Пересчёт остатков по журналу StockTransaction ===")
        self.stdout.write(f"Режим: {mode}")
        self.stdout.write(f"Транзакций в журнале: {total}")
        self.stdout.write(f"Progress-every: {progress_every}")
        self.stdout.write("----------------------------------------------------")

        # Снимки "до" (нужно для dry-run отчёта и для общего контроля)
        old_global = _snapshot_global()
        old_building = _snapshot_building()

        old_gs_count = len(old_global)
        old_bs_count = len(old_building)
        old_gs_sum = sum(old_global.values())
        old_bs_sum = sum(old_building.values())

        self.stdout.write(f"Состояние ДО: GlobalStock строк={old_gs_count}, qty_sum={old_gs_sum}")
        self.stdout.write(f"Состояние ДО: BuildingStock строк={old_bs_count}, qty_sum={old_bs_sum}")
        self.stdout.write("----------------------------------------------------")

        try:
            with db_transaction.atomic():
                # В dry-run мы тоже делаем реальную пересборку, но потом откатываем.
                GlobalStock.objects.all().delete()
                BuildingStock.objects.all().delete()

                self.stdout.write("Очищено: GlobalStock и BuildingStock (в рамках текущей транзакции).")
                self.stdout.write("Начинаю применение транзакций...")

                for i, tx in enumerate(qs.iterator(chunk_size=1000), start=1):
                    eff_building = _effective_building(tx)
                    pb = _printer_building(tx)

                    # предупреждение: tx.building указан и не совпадает с корпусом принтера
                    if tx.building_id and pb and tx.building_id != pb.id:
                        self.stdout.write(
                            f"[WARN] tx id={tx.id}: tx.building={tx.building} "
                            f"не совпадает с printer.building={pb}"
                        )

                    # подробный лог по транзакции
                    flag = _pretty_flag(bool(tx.on_balance))
                    printer_str = str(tx.printer) if tx.printer_id else "–"
                    building_str = str(eff_building) if eff_building else "–"
                    issued_to = tx.issued_to.strip() if tx.issued_to else ""
                    issued_part = f", кому: {issued_to}" if issued_to else ""
                    comment_part = f", коммент: {tx.comment.strip()}" if tx.comment else ""

                    self.stdout.write(
                        f"[{i}/{total}] tx id={tx.id} "
                        f"{tx.created_at:%Y-%m-%d %H:%M:%S} – {tx.get_tx_type_display()} – "
                        f"{tx.cartridge} × {tx.qty} ({flag}) – "
                        f"корпус: {building_str} – принтер: {printer_str}"
                        f"{issued_part}{comment_part}"
                    )

                    try:
                        apply_transaction(tx)
                    except Exception as e:
                        raise CommandError(f"Ошибка на транзакции id={tx.id}: {e}") from e

                    if i % progress_every == 0:
                        self.stdout.write(f"Прогресс: {i}/{total}")

                # Снимки "после пересборки"
                new_global = _snapshot_global()
                new_building = _snapshot_building()

                new_gs_count = len(new_global)
                new_bs_count = len(new_building)
                new_gs_sum = sum(new_global.values())
                new_bs_sum = sum(new_building.values())

                self.stdout.write("----------------------------------------------------")
                self.stdout.write(f"Состояние ПОСЛЕ: GlobalStock строк={new_gs_count}, qty_sum={new_gs_sum}")
                self.stdout.write(f"Состояние ПОСЛЕ: BuildingStock строк={new_bs_count}, qty_sum={new_bs_sum}")

                # diff-отчёт
                gdiff = _diff(old_global, new_global)
                bdiff = _diff(old_building, new_building)

                self.stdout.write("----------------------------------------------------")
                self.stdout.write("Что изменится в остатках (сравнение ДО → ПОСЛЕ):")
                self.stdout.write(
                    f"GlobalStock: добавится={gdiff.added}, удалится={gdiff.removed}, qty изменится={gdiff.changed_qty} "
                    f"(затронуто строк всего={gdiff.total_affected})"
                )
                self.stdout.write(
                    f"BuildingStock: добавится={bdiff.added}, удалится={bdiff.removed}, qty изменится={bdiff.changed_qty} "
                    f"(затронуто строк всего={bdiff.total_affected})"
                )

                # Детализация важных кейсов: что будет удалено (то, о чём ты просил)
                removed_global_keys = set(old_global.keys()) - set(new_global.keys())
                removed_building_keys = set(old_building.keys()) - set(new_building.keys())

                if removed_global_keys or removed_building_keys:
                    self.stdout.write("----------------------------------------------------")
                    self.stdout.write("Остатки, которые будут УДАЛЕНЫ (были ДО, но по журналу их быть не должно):")

                    if removed_global_keys:
                        # подтянем имена картриджей пачкой
                        cartridge_ids = sorted({k[0] for k in removed_global_keys})
                        cartridges = {
                            c.id: str(c)
                            for c in StockTransaction._meta.get_field("cartridge").remote_field.model.objects.filter(id__in=cartridge_ids)
                        }
                        for (cartridge_id, on_balance) in sorted(removed_global_keys, key=lambda x: (x[0], x[1])):
                            name = cartridges.get(cartridge_id, f"cartridge_id={cartridge_id}")
                            qty = old_global[(cartridge_id, on_balance)]
                            self.stdout.write(f"  GlobalStock: {name} ({_pretty_flag(on_balance)}) qty={qty} → будет удалён")

                    if removed_building_keys:
                        building_ids = sorted({k[0] for k in removed_building_keys})
                        cartridge_ids = sorted({k[1] for k in removed_building_keys})

                        Building = BuildingStock._meta.get_field("building").remote_field.model
                        CartridgeModel = BuildingStock._meta.get_field("cartridge").remote_field.model

                        buildings = {b.id: str(b) for b in Building.objects.filter(id__in=building_ids)}
                        cartridges = {c.id: str(c) for c in CartridgeModel.objects.filter(id__in=cartridge_ids)}

                        for (building_id, cartridge_id, on_balance) in sorted(
                            removed_building_keys, key=lambda x: (x[0], x[1], x[2])
                        ):
                            bname = buildings.get(building_id, f"building_id={building_id}")
                            cname = cartridges.get(cartridge_id, f"cartridge_id={cartridge_id}")
                            qty = old_building[(building_id, cartridge_id, on_balance)]
                            self.stdout.write(
                                f"  BuildingStock: {bname} – {cname} ({_pretty_flag(on_balance)}) qty={qty} → будет удалён"
                            )
                else:
                    self.stdout.write("----------------------------------------------------")
                    self.stdout.write("Удалений строк остатков не будет (все текущие остатки подтверждаются журналом).")

                if dry_run:
                    # откатываем изменения (delete + rebuild) полностью
                    db_transaction.set_rollback(True)
                    self.stdout.write("----------------------------------------------------")
                    self.stdout.write(self.style.WARNING("DRY-RUN завершён: изменения НЕ сохранены (транзакция откатана)."))
                    return

            # сюда попадаем только в LIVE режиме
            self.stdout.write("----------------------------------------------------")
            self.stdout.write(self.style.SUCCESS("LIVE пересчёт завершён: изменения сохранены."))

        except CommandError:
            raise
        except Exception as e:
            raise CommandError(f"Неожиданная ошибка пересчёта: {e}") from e