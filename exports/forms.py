from django import forms
from inventory.models import Building


class ExportIssuesForm(forms.Form):
    BALANCE_CHOICES = [
        ("all", "Все картриджи"),
        ("balance", "Только на балансе"),
        ("non_balance", "Только не на балансе"),
    ]

    date_from = forms.DateField(
        required=True,
        label="Дата начала",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    date_to = forms.DateField(
        required=True,
        label="Дата окончания",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    building = forms.ModelChoiceField(
        queryset=Building.objects.order_by("name"),
        required=False,
        label="Корпус",
        empty_label="Все корпуса",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    balance_type = forms.ChoiceField(
        required=True,
        label="Состав выгрузки",
        choices=BALANCE_CHOICES,
        initial="all",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def clean(self):
        cleaned = super().clean()
        date_from = cleaned.get("date_from")
        date_to = cleaned.get("date_to")

        if date_from and date_to and date_from > date_to:
            raise forms.ValidationError("Дата начала не может быть позже даты окончания.")

        return cleaned


class ExportStocksForm(forms.Form):
    BALANCE_CHOICES = [
        ("all", "Все картриджи"),
        ("balance", "Только на балансе"),
        ("non_balance", "Только не на балансе"),
    ]

    balance_type = forms.ChoiceField(
        label="Состав выгрузки",
        choices=BALANCE_CHOICES,
        initial="all",
        widget=forms.Select(attrs={"class": "form-select"}),
    )