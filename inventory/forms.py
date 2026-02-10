from django import forms
from .models import (
    Building, Room, Printer, PrinterModel, CartridgeModel,
    StockTransaction
)



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
            "building": forms.Select(attrs={"class": "form-select"}),
            "comment": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class StockOutForm(forms.ModelForm):
    # дополнительные поля, которых нет в модели StockTransaction
    building = forms.ModelChoiceField(
        queryset=Building.objects.order_by("name"),
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

    class Meta:
        model = StockTransaction
        # issued_to убираем — будет подставляться автоматически
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

        # По умолчанию: ничего не показываем, пока не выбрали корпус/кабинет
        self.fields["printer"].queryset = Printer.objects.none()
        self.fields["cartridge"].queryset = CartridgeModel.objects.none()

        # Корпус → фильтруем кабинеты
        if building_id:
            self.fields["room"].queryset = Room.objects.filter(building_id=building_id).order_by("number")
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