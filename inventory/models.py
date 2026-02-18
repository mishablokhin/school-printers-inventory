from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import UniqueConstraint


class Building(models.Model):
    name = models.CharField(max_length=120, unique=True)
    address = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name


class Room(models.Model):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name="rooms")
    number = models.CharField(max_length=30)
    owner_name = models.CharField(max_length=255, blank=True)
    owner_email = models.EmailField(blank=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["building", "number"], name="uniq_room_in_building")
        ]

    def __str__(self):
        return f"{self.building} – {self.number}"


class PrinterModel(models.Model):
    vendor = models.CharField(max_length=80)
    model = models.CharField(max_length=120)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["vendor", "model"], name="uniq_printer_model")
        ]

    def __str__(self):
        return f"{self.vendor} {self.model}"


class CartridgeModel(models.Model):
    vendor = models.CharField(max_length=80)
    code = models.CharField(max_length=120)
    title = models.CharField(max_length=255, blank=True)
    compatible_printers = models.ManyToManyField(
        PrinterModel,
        related_name="compatible_cartridges",
        blank=True,
    )

    class Meta:
        constraints = [
            UniqueConstraint(fields=["vendor", "code"], name="uniq_cartridge_model")
        ]

    def __str__(self):
        return f"{self.vendor} {self.code}"


class Printer(models.Model):
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="printers")
    printer_model = models.ForeignKey(PrinterModel, on_delete=models.PROTECT, related_name="printers")
    inventory_tag = models.CharField(max_length=80, blank=True)
    note = models.TextField(blank=True)

    def __str__(self):
        inv = f" ({self.inventory_tag})" if self.inventory_tag else ""
        return f"{self.printer_model}{inv} – {self.room}"


# ✅ Теперь глобальный остаток хранится раздельно: на балансе / не на балансе
class GlobalStock(models.Model):
    cartridge = models.ForeignKey(
        CartridgeModel,
        on_delete=models.CASCADE,
        related_name="global_stocks",
    )
    on_balance = models.BooleanField(default=False)
    qty = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["cartridge", "on_balance"], name="uniq_global_stock_cartridge_balance")
        ]

    def __str__(self):
        flag = " (на балансе)" if self.on_balance else ""
        return f"{self.cartridge}{flag}: {self.qty}"


# ✅ Теперь склад по корпусу тоже раздельно по балансу
class BuildingStock(models.Model):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name="stocks")
    cartridge = models.ForeignKey(CartridgeModel, on_delete=models.CASCADE, related_name="building_stocks")
    on_balance = models.BooleanField(default=False)
    qty = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["building", "cartridge", "on_balance"], name="uniq_building_stock_balance")
        ]

    def __str__(self):
        flag = " (на балансе)" if self.on_balance else ""
        return f"{self.building} – {self.cartridge}{flag}: {self.qty}"


class StockTransaction(models.Model):
    class Type(models.TextChoices):
        IN = "IN", "Приход"
        OUT = "OUT", "Выдача"

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stock_transactions"
    )

    tx_type = models.CharField(max_length=3, choices=Type.choices)
    cartridge = models.ForeignKey(CartridgeModel, on_delete=models.PROTECT, related_name="transactions")
    qty = models.PositiveIntegerField()

    # ✅ Новый флаг: эта партия на балансе школы
    on_balance = models.BooleanField(default=False)

    building = models.ForeignKey(Building, on_delete=models.PROTECT, null=True, blank=True)
    printer = models.ForeignKey(Printer, on_delete=models.PROTECT, null=True, blank=True)
    issued_to = models.CharField(max_length=255, blank=True)
    comment = models.TextField(blank=True)

    def clean(self):
        if self.qty == 0:
            raise ValidationError("Количество должно быть больше 0.")

        if self.tx_type == self.Type.OUT:
            if not self.printer:
                raise ValidationError("Для выдачи нужно указать принтер.")

        # Проверка совместимости
        if self.printer and self.cartridge:
            pm = self.printer.printer_model
            if not self.cartridge.compatible_printers.filter(pk=pm.pk).exists():
                raise ValidationError("Этот картридж не подходит к выбранному принтеру.")

    def __str__(self):
        flag = " (на балансе)" if self.on_balance else ""
        return f"{self.get_tx_type_display()} – {self.cartridge}{flag} × {self.qty}"