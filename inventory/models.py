from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import UniqueConstraint


class Building(models.Model):
    name = models.CharField(max_length=120, unique=True)  # «Корпус 1», «ШО-1», и т. п.
    address = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name


class Room(models.Model):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name="rooms")
    number = models.CharField(max_length=30)  # «101», «2-14», «кабинет информатики»
    owner_name = models.CharField(max_length=255, blank=True)  # ФИО ответственного (можно текстом)
    owner_email = models.EmailField(blank=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["building", "number"], name="uniq_room_in_building")
        ]

    def __str__(self):
        return f"{self.building} – {self.number}"


class PrinterModel(models.Model):
    vendor = models.CharField(max_length=80)   # HP, Canon…
    model = models.CharField(max_length=120)  # M428fdw…

    class Meta:
        constraints = [
            UniqueConstraint(fields=["vendor", "model"], name="uniq_printer_model")
        ]

    def __str__(self):
        return f"{self.vendor} {self.model}"


class CartridgeModel(models.Model):
    vendor = models.CharField(max_length=80)   # HP, Canon…
    code = models.CharField(max_length=120)    # CE285A, CF259X…
    title = models.CharField(max_length=255, blank=True)  # описание
    # совместимость задаём через M2M
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
    inventory_tag = models.CharField(max_length=80, blank=True)  # инв. номер/метка
    note = models.TextField(blank=True)

    def __str__(self):
        inv = f" ({self.inventory_tag})" if self.inventory_tag else ""
        return f"{self.printer_model}{inv} – {self.room}"


class GlobalStock(models.Model):
    cartridge = models.OneToOneField(CartridgeModel, on_delete=models.CASCADE, related_name="global_stock")
    qty = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.cartridge}: {self.qty}"


class BuildingStock(models.Model):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name="stocks")
    cartridge = models.ForeignKey(CartridgeModel, on_delete=models.CASCADE, related_name="building_stocks")
    qty = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["building", "cartridge"], name="uniq_building_stock")
        ]

    def __str__(self):
        return f"{self.building} – {self.cartridge}: {self.qty}"


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

    # Куда относится движение (для статистики по корпусам)
    building = models.ForeignKey(Building, on_delete=models.PROTECT, null=True, blank=True)

    # Для выдачи – конкретный принтер/кабинет
    printer = models.ForeignKey(Printer, on_delete=models.PROTECT, null=True, blank=True)
    issued_to = models.CharField(max_length=255, blank=True)  # кому выдали (ФИО)
    comment = models.TextField(blank=True)

    def clean(self):
        if self.qty == 0:
            raise ValidationError("Количество должно быть больше 0.")

        if self.tx_type == self.Type.OUT:
            if not self.printer:
                raise ValidationError("Для выдачи нужно указать принтер.")
            # building можно вывести из printer.room.building, но поле оставляем для статистики
        if self.tx_type == self.Type.IN:
            # приход может быть «общий» (без корпуса) или в корпус
            pass

        # Проверка совместимости
        if self.printer and self.cartridge:
            pm = self.printer.printer_model
            if not self.cartridge.compatible_printers.filter(pk=pm.pk).exists():
                raise ValidationError("Этот картридж не подходит к выбранному принтеру.")

    def __str__(self):
        return f"{self.get_tx_type_display()} – {self.cartridge} × {self.qty}"