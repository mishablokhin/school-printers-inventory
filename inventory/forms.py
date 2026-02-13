from django import forms
from django.db import connection
from django.db.models import IntegerField, Value
from django.db.models.functions import Cast, Coalesce, NullIf
from django.db.models import Func

from .models import (
    Building, Room, Printer, PrinterModel, CartridgeModel,
    StockTransaction
)


# -------------------------
# Helpers: сортировка кабинетов
# -------------------------

def order_rooms_queryset(qs):
    """
    Сортировка кабинетов: сначала по корпусу, затем по номеру кабинета "как число",
    затем по строке (для случаев типа "2-14", "кабинет информатики" и т.д.)
    """
    qs = qs.select_related("building")

    # PostgreSQL: можно аккуратно вытащить цифры regexp_replace и сортировать числом
    if connection.vendor == "postgresql":
        digits_only = Func(
            "number",
            Value(r"[^0-9]"),
            Value(""),
            Value("g"),
            function="regexp_replace",
        )

        qs = qs.annotate(
            number_int=Coalesce(
                Cast(NullIf(digits_only, Value("")), IntegerField()),
                Value(0),
            )
        ).order_by("building__name", "number_int", "number")

        return qs

    # Fallback для SQLite/MySQL (без regexp_replace)
    return qs.order_by("building__name", "number")


# -------------------------
# CRUD-формы
# -------------------------

class BuildingForm(forms.ModelForm):
    class Meta:
        model = Building
        fields = ["name", "address"]
        labels = {
            "name": "Название корпуса",
            "address": "Адрес",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
        }


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["building", "number", "owner_name", "owner_email"]
        labels = {
            "building": "Корпус",
            "number": "Номер кабинета",
            "owner_name": "Ответственный",
            "owner_email": "Электронная почта",
        }
        widgets = {
            "building": forms.Select(attrs={"class": "form-select"}),
            "number": forms.TextInput(attrs={"class": "form-control"}),
            "owner_name": forms.TextInput(attrs={"class": "form-control"}),
            "owner_email": forms.EmailInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["building"].queryset = Building.objects.order_by("name")


class PrinterModelForm(forms.ModelForm):
    class Meta:
        model = PrinterModel
        fields = ["vendor", "model"]
        labels = {
            "vendor": "Производитель",
            "model": "Модель принтера",
        }
        widgets = {
            "vendor": forms.TextInput(attrs={"class": "form-control"}),
            "model": forms.TextInput(attrs={"class": "form-control"}),
        }


class CartridgeModelForm(forms.ModelForm):
    class Meta:
        model = CartridgeModel
        fields = ["vendor", "code", "title", "compatible_printers"]
        labels = {
            "vendor": "Производитель",
            "code": "Код картриджа",
            "title": "Описание / название",
            "compatible_printers": "Совместимые модели принтеров",
        }
        widgets = {
            "vendor": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "compatible_printers": forms.SelectMultiple(
                attrs={"class": "form-select", "size": "10"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["compatible_printers"].queryset = PrinterModel.objects.order_by("vendor", "model")


class PrinterForm(forms.ModelForm):
    class Meta:
        model = Printer
        fields = ["room", "printer_model", "inventory_tag", "note"]
        labels = {
            "room": "Кабинет",
            "printer_model": "Модель принтера",
            "inventory_tag": "Инвентарный номер",
            "note": "Примечание",
        }
        widgets = {
            "room": forms.Select(attrs={"class": "form-select"}),
            "printer_model": forms.Select(attrs={"class": "form-select"}),
            "inventory_tag": forms.TextInput(attrs={"class": "form-control"}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = order_rooms_queryset(Room.objects.all())
        self.fields["printer_model"].queryset = PrinterModel.objects.order_by("vendor", "model")


# -------------------------
# Движения склада
# -------------------------

class StockInForm(forms.ModelForm):
    class Meta:
        model = StockTransaction
        fields = ["cartridge", "qty", "building", "comment"]
        labels = {
            "cartridge": "Картридж",
            "qty": "Количество",
            "building": "Корпус (склад)",
            "comment": "Комментарий",
        }
        widgets = {
            "cartridge": forms.Select(attrs={"class": "form-select"}),
            "qty": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "building": forms.Select(attrs={"class": "form-select", "required": True}),
            "comment": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["cartridge"].queryset = CartridgeModel.objects.order_by("vendor", "code")
        self.fields["building"].queryset = Building.objects.order_by("name")

        self.fields["building"].required = True
        self.fields["building"].empty_label = "— выберите корпус —"
        self.fields["building"].error_messages = {
            "required": "Выберите корпус, в который поступили картриджи."
        }


class StockOutForm(forms.ModelForm):
    # дополнительные поля, которых нет в модели StockTransaction
    building = forms.ModelChoiceField(
        queryset=Building.objects.none(),
        required=True,
        label="Корпус",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    room = forms.ModelChoiceField(
        queryset=Room.objects.none(),
        required=True,
        label="Кабинет",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    # NEW: откуда списывать (если в “куда выдаём” ноль)
    source_building = forms.ModelChoiceField(
        queryset=Building.objects.none(),
        required=False,
        label="Выдать со склада (корпуса)",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = StockTransaction
        fields = ["building", "room", "printer", "cartridge", "qty", "comment"]
        labels = {
            "printer": "Принтер",
            "cartridge": "Картридж",
            "qty": "Количество",
            "comment": "Комментарий",
        }
        widgets = {
            "printer": forms.Select(attrs={"class": "form-select"}),
            "cartridge": forms.Select(attrs={"class": "form-select"}),
            "qty": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "comment": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        building_id = kwargs.pop("building_id", None)
        room_id = kwargs.pop("room_id", None)
        printer_id = kwargs.pop("printer_id", None)
        super().__init__(*args, **kwargs)

        # сортировка корпуса — всегда
        self.fields["building"].queryset = Building.objects.order_by("name")

        # NEW: источники (список корпусов) — заполняем всегда, а показывать/фильтровать будем в view
        self.fields["source_building"].queryset = Building.objects.order_by("name")

        # По умолчанию: ничего не показываем, пока не выбрали корпус/кабинет
        self.fields["printer"].queryset = Printer.objects.none()
        self.fields["cartridge"].queryset = CartridgeModel.objects.none()

        # Корпус → фильтруем кабинеты (и сортируем "правильно")
        if building_id:
            rooms_qs = Room.objects.filter(building_id=building_id)
            rooms_qs = order_rooms_queryset(rooms_qs)
            self.fields["room"].queryset = rooms_qs
            self.initial["building"] = building_id
        else:
            self.fields["room"].queryset = Room.objects.none()

        # Кабинет → фильтруем принтеры
        if room_id:
            self.fields["printer"].queryset = (
                Printer.objects.select_related("printer_model", "room", "room__building")
                .filter(room_id=room_id)
                .order_by("printer_model__vendor", "printer_model__model", "inventory_tag")
            )
            self.initial["room"] = room_id

        # Принтер → фильтруем картриджи по совместимости
        if printer_id:
            try:
                printer = Printer.objects.select_related("printer_model").get(pk=printer_id)
                self.fields["cartridge"].queryset = (
                    CartridgeModel.objects.filter(compatible_printers=printer.printer_model)
                    .order_by("vendor", "code")
                )
                self.initial["printer"] = printer_id
            except Printer.DoesNotExist:
                pass