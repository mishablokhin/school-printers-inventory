from django import forms
from django.db import connection
from django.db.models import IntegerField, Value
from django.db.models.functions import Cast, Coalesce, NullIf
from django.db.models import Func

from .models import (
    Building, Room, Printer, PrinterModel, CartridgeModel,
    StockTransaction, GlobalStock
)


# -------------------------
# Helpers: сортировка кабинетов
# -------------------------

def order_rooms_queryset(qs):
    qs = qs.select_related("building")

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
        building_id = kwargs.pop("building_id", None)  # ✅ важно
        super().__init__(*args, **kwargs)

        rooms_qs = Room.objects.all()
        if building_id:
            rooms_qs = rooms_qs.filter(building_id=building_id)

        self.fields["room"].queryset = order_rooms_queryset(rooms_qs)
        self.fields["printer_model"].queryset = PrinterModel.objects.order_by("vendor", "model")

        # Если редактируем и building_id не передан – оставляем всё как есть
        # Если building_id передан – удобно проставить initial
        if building_id and not self.initial.get("room") and self.instance and self.instance.pk:
            self.initial["room"] = self.instance.room_id


# -------------------------
# Движения склада
# -------------------------

class StockInForm(forms.ModelForm):
    class Meta:
        model = StockTransaction
        fields = ["cartridge", "qty", "building", "on_balance", "comment"]
        labels = {
            "cartridge": "Картридж",
            "qty": "Количество",
            "building": "Корпус (склад)",
            "on_balance": "На балансе школы",
            "comment": "Комментарий",
        }
        widgets = {
            "cartridge": forms.Select(attrs={"class": "form-select"}),
            "qty": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "building": forms.Select(attrs={"class": "form-select", "required": True}),
            "on_balance": forms.CheckboxInput(attrs={"class": "form-check-input"}),
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

    source_building = forms.ModelChoiceField(
        queryset=Building.objects.none(),
        required=False,
        label="Выдать со склада (корпуса)",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    cartridge_variant = forms.ChoiceField(
        required=True,
        label="Картридж",
        choices=[],
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = StockTransaction
        fields = ["building", "room", "printer", "qty", "comment"]
        labels = {
            "printer": "Принтер",
            "qty": "Количество",
            "comment": "Комментарий",
        }
        widgets = {
            "printer": forms.Select(attrs={"class": "form-select"}),
            "qty": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "comment": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        building_id = kwargs.pop("building_id", None)
        room_id = kwargs.pop("room_id", None)
        printer_id = kwargs.pop("printer_id", None)

        # optional: список корпусов-источников от view
        source_building_ids = kwargs.pop("source_building_ids", None)

        super().__init__(*args, **kwargs)

        self.fields["building"].queryset = Building.objects.order_by("name")

        # source_building по умолчанию пустой (а если view передал ids — ограничим)
        if source_building_ids is not None:
            self.fields["source_building"].queryset = Building.objects.filter(id__in=source_building_ids).order_by("name")
        else:
            self.fields["source_building"].queryset = Building.objects.order_by("name")

        self.fields["printer"].queryset = Printer.objects.none()
        self.fields["room"].queryset = Room.objects.none()
        self.fields["cartridge_variant"].choices = [("", "— выберите картридж —")]

        if building_id:
            rooms_qs = order_rooms_queryset(Room.objects.filter(building_id=building_id))
            self.fields["room"].queryset = rooms_qs
            self.initial["building"] = building_id

        if room_id:
            self.fields["printer"].queryset = (
                Printer.objects.select_related("printer_model", "room", "room__building")
                .filter(room_id=room_id)
                .order_by("printer_model__vendor", "printer_model__model", "inventory_tag")
            )
            self.initial["room"] = room_id

        if printer_id:
            try:
                printer = Printer.objects.select_related("printer_model").get(pk=printer_id)

                base_qs = (
                    CartridgeModel.objects
                    .filter(compatible_printers=printer.printer_model)
                    .order_by("vendor", "code")
                )

                # Остатки по школе для формирования вариантов
                gs_map = {
                    f"{s.cartridge_id}:{1 if s.on_balance else 0}": s.qty
                    for s in GlobalStock.objects.all()
                }

                choices = [("", "— выберите картридж —")]
                for c in base_qs:
                    on_qty = gs_map.get(f"{c.id}:1", 0)
                    off_qty = gs_map.get(f"{c.id}:0", 0)

                    # показываем оба варианта, если они в принципе встречались или есть остаток
                    # (если хочешь строго “как раньше”: показывать вариант с пометкой “(на балансе)” только при наличии)
                    if off_qty > 0 or on_qty == 0:
                        choices.append((f"{c.id}:0", f"{c.vendor} {c.code}"))
                    if on_qty > 0:
                        choices.append((f"{c.id}:1", f"{c.vendor} {c.code} (на балансе)"))

                    # если вообще всё 0, оставим хотя бы один вариант "не на балансе"
                    if on_qty == 0 and off_qty == 0:
                        # гарантируем, что "не на балансе" есть
                        if (f"{c.id}:0", f"{c.vendor} {c.code}") not in choices:
                            choices.append((f"{c.id}:0", f"{c.vendor} {c.code}"))

                self.fields["cartridge_variant"].choices = choices
                self.initial["printer"] = printer_id

            except Printer.DoesNotExist:
                pass

    def clean_cartridge_variant(self):
        val = (self.cleaned_data.get("cartridge_variant") or "").strip()
        if not val or ":" not in val:
            raise forms.ValidationError("Выберите картридж.")
        c_id, flag = val.split(":", 1)
        if not c_id.isdigit() or flag not in ("0", "1"):
            raise forms.ValidationError("Некорректный тип картриджа.")
        return val

    def clean(self):
        cleaned = super().clean()

        # Проставить instance.cartridge и instance.on_balance
        variant = cleaned.get("cartridge_variant")
        if variant and ":" in variant:
            c_id, flag = variant.split(":", 1)
            try:
                self.instance.cartridge = CartridgeModel.objects.get(pk=int(c_id))
                self.instance.on_balance = (flag == "1")
            except (CartridgeModel.DoesNotExist, ValueError):
                self.add_error("cartridge_variant", "Выбранный картридж не найден.")
        return cleaned