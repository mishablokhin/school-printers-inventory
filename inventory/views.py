from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.db import transaction
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, TemplateView
from django.core.exceptions import ValidationError

from django.db import connection
from django.db.models import IntegerField, Value
from django.db.models.functions import Cast, Coalesce, NullIf
from django.db.models import Func

from .forms import (
    BuildingForm, RoomForm, PrinterModelForm, CartridgeModelForm, PrinterForm,
    StockInForm, StockOutForm
)
from .models import (
    Building, Room, PrinterModel, CartridgeModel, Printer,
    GlobalStock, BuildingStock, StockTransaction
)
from .services import apply_transaction


# -------------------------
# Остатки и журнал
# -------------------------

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        q = (self.request.GET.get("q") or "").strip()

        cartridges = (
            CartridgeModel.objects
            .prefetch_related("compatible_printers")
            .order_by("vendor", "code")
        )

        # Поиск по картриджу: vendor/code/title
        # Поиск по принтеру (совместимости): compatible_printers.vendor/model
        if q:
            cartridges = (
                cartridges
                .filter(
                    Q(vendor__icontains=q) |
                    Q(code__icontains=q) |
                    Q(title__icontains=q) |
                    Q(compatible_printers__vendor__icontains=q) |
                    Q(compatible_printers__model__icontains=q)
                )
                .distinct()
            )

        stock_map = {s.cartridge_id: s.qty for s in GlobalStock.objects.all()}
        buildings = list(Building.objects.order_by("name"))

        # (cartridge_id, building_id) -> qty
        bs_pairs = {
            (s.cartridge_id, s.building_id): s.qty
            for s in BuildingStock.objects.all()
        }

        # cartridge_id -> [{id, name, qty}, ...] (по всем корпусам, даже если 0)
        building_stock_rows = {}
        for c in cartridges:
            rows = []
            for b in buildings:
                rows.append({
                    "id": b.id,
                    "name": b.name,
                    "qty": bs_pairs.get((c.id, b.id), 0),
                })
            building_stock_rows[c.id] = rows

        ctx.update({
            "q": q,
            "cartridges": cartridges,
            "stock_map": stock_map,
            "buildings": buildings,
            "building_stock_rows": building_stock_rows,
        })
        return ctx


class BuildingStatsView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/building_stats.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        building = Building.objects.get(pk=kwargs["pk"])
        cartridges = CartridgeModel.objects.prefetch_related("compatible_printers").order_by("vendor", "code")
        stock_map = {s.cartridge_id: s.qty for s in BuildingStock.objects.filter(building=building)}
        ctx.update({"building": building, "cartridges": cartridges, "stock_map": stock_map})
        return ctx


class JournalView(LoginRequiredMixin, ListView):
    template_name = "inventory/journal.html"
    context_object_name = "txs"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            StockTransaction.objects
            .select_related("created_by", "cartridge", "building", "printer", "printer__room", "printer__printer_model")
            .order_by("-created_at")
        )
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(cartridge__code__icontains=q) |
                Q(cartridge__title__icontains=q) |
                Q(issued_to__icontains=q) |
                Q(printer__inventory_tag__icontains=q) |
                Q(printer__printer_model__model__icontains=q) |
                Q(printer__printer_model__vendor__icontains=q) |
                Q(building__name__icontains=q)
            )
        return qs


class StockInCreateView(LoginRequiredMixin, CreateView):
    template_name = "inventory/stock_in.html"
    form_class = StockInForm
    success_url = reverse_lazy("inventory:journal")

    def form_valid(self, form):
        tx = form.save(commit=False)
        tx.created_by = self.request.user
        tx.tx_type = StockTransaction.Type.IN

        try:
            with transaction.atomic():
                tx.full_clean()
                tx.save()
                apply_transaction(tx)
        except ValidationError as e:
            # ошибки модели (qty==0 и т.п.)
            for field, errors in (e.message_dict or {}).items():
                for msg in errors:
                    form.add_error(field if field in form.fields else None, msg)
            return self.form_invalid(form)
        except ValueError as e:
            # ошибки остатков из apply_transaction
            form.add_error(None, str(e))
            return self.form_invalid(form)

        return redirect(self.success_url)


class StockOutCreateView(LoginRequiredMixin, CreateView):
    template_name = "inventory/stock_out.html"
    form_class = StockOutForm
    success_url = reverse_lazy("inventory:journal")

    def _get_ids(self):
        src = self.request.POST if self.request.method == "POST" else self.request.GET
        building_id = src.get("building") or ""
        room_id = src.get("room") or ""
        printer_id = src.get("printer") or ""
        cartridge_id = src.get("cartridge") or ""
        return building_id, room_id, printer_id, cartridge_id

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        building_id, room_id, printer_id, _ = self._get_ids()
        kwargs.update(
            {
                "building_id": building_id or None,
                "room_id": room_id or None,
                "printer_id": printer_id or None,
            }
        )
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        building_id, room_id, printer_id, cartridge_id = self._get_ids()

        selected_building = Building.objects.filter(pk=building_id).first() if building_id else None
        selected_room = Room.objects.select_related("building").filter(pk=room_id).first() if room_id else None
        selected_printer = (
            Printer.objects.select_related("printer_model", "room", "room__building")
            .filter(pk=printer_id).first()
            if printer_id else None
        )

        printers_in_room = []
        if selected_room:
            printers_in_room = (
                Printer.objects.select_related("printer_model")
                .filter(room=selected_room)
                .order_by("printer_model__vendor", "printer_model__model", "inventory_tag")
            )

        selected_cartridge = None
        building_qty = None
        global_qty = None
        can_issue = True

        form = ctx.get("form")
        cartridge_qs = form.fields["cartridge"].queryset if form and "cartridge" in form.fields else None
        if cartridge_id and cartridge_qs is not None:
            selected_cartridge = cartridge_qs.filter(pk=cartridge_id).first()

        # Остаток в выбранном корпусе (куда выдаём)
        if selected_building and selected_cartridge:
            building_qty = (
                BuildingStock.objects
                .filter(building=selected_building, cartridge=selected_cartridge)
                .values_list("qty", flat=True)
                .first()
            )
            building_qty = 0 if building_qty is None else building_qty
            can_issue = building_qty > 0

        # Общий остаток
        if selected_cartridge:
            global_qty = (
                GlobalStock.objects
                .filter(cartridge=selected_cartridge)
                .values_list("qty", flat=True)
                .first()
            )
            global_qty = 0 if global_qty is None else global_qty

        # NEW: альтернативные корпуса-источники, где есть картриджи > 0
        available_source_buildings = []
        if selected_cartridge:
            source_rows = (
                BuildingStock.objects
                .select_related("building")
                .filter(cartridge=selected_cartridge, qty__gt=0)
                .order_by("building__name")
            )
            for row in source_rows:
                if selected_building and row.building_id == selected_building.id:
                    continue
                available_source_buildings.append({
                    "id": row.building_id,
                    "name": row.building.name,
                    "qty": row.qty,
                })

        # NEW: можно оформить выдачу, если:
        # - есть в выбранном корпусе
        # - или есть альтернативные корпуса-источники
        if building_qty is not None:
            can_issue = (building_qty > 0) or bool(available_source_buildings)

        # NEW: ограничим выпадающий список source_building только доступными складами
        if form and "source_building" in form.fields:
            ids = [x["id"] for x in available_source_buildings]
            form.fields["source_building"].queryset = Building.objects.filter(id__in=ids).order_by("name")
            # Можно проставить дефолт (первый доступный)
            if ids and not form.initial.get("source_building"):
                form.initial["source_building"] = ids[0]

        ctx.update(
            {
                "selected_building": selected_building,
                "selected_room": selected_room,
                "selected_printer": selected_printer,
                "printers_in_room": printers_in_room,
                "selected_cartridge": selected_cartridge,
                "building_qty": building_qty,
                "global_qty": global_qty,
                "can_issue": can_issue,
                "available_source_buildings": available_source_buildings,
            }
        )
        return ctx

    def form_valid(self, form):
        tx = form.save(commit=False)
        tx.created_by = self.request.user
        tx.tx_type = StockTransaction.Type.OUT

        # куда выдаём (назначение) – берём из принтера
        destination_building = tx.printer.room.building if tx.printer else None

        # NEW: откуда списываем (если выбрали)
        source_building = form.cleaned_data.get("source_building")

        # списание выполняем с source_building, если он выбран, иначе со “своего” корпуса назначения
        tx.building = source_building or destination_building

        # кому выдали
        tx.issued_to = (
            tx.printer.room.owner_name
            if (tx.printer and tx.printer.room and tx.printer.room.owner_name)
            else ""
        )

        # Проверка на сервере формы: остаток должен быть в КОРПУСЕ-ИСТОЧНИКЕ
        if tx.building_id and tx.cartridge_id:
            bqty = (
                BuildingStock.objects
                .filter(building_id=tx.building_id, cartridge_id=tx.cartridge_id)
                .values_list("qty", flat=True)
                .first()
            ) or 0
            if bqty <= 0:
                form.add_error(None, "Недостаточно картриджей в выбранном корпусе-складе.")
                return self.form_invalid(form)

        try:
            with transaction.atomic():
                tx.full_clean()
                tx.save()
                apply_transaction(tx)
        except ValidationError as e:
            for field, errors in (e.message_dict or {}).items():
                for msg in errors:
                    form.add_error(field if field in form.fields else None, msg)
            return self.form_invalid(form)
        except ValueError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

        return redirect(self.success_url)


# -------------------------
# CRUD справочников
# -------------------------

class BuildingList(LoginRequiredMixin, ListView):
    model = Building
    template_name = "inventory/crud/building_list.html"
    context_object_name = "items"
    paginate_by = 50
    ordering = ["name"]


class BuildingCreate(LoginRequiredMixin, CreateView):
    model = Building
    form_class = BuildingForm
    template_name = "inventory/crud/form.html"
    success_url = reverse_lazy("inventory:buildings")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Добавить корпус"
        return ctx


class BuildingUpdate(LoginRequiredMixin, UpdateView):
    model = Building
    form_class = BuildingForm
    template_name = "inventory/crud/form.html"
    success_url = reverse_lazy("inventory:buildings")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Редактировать корпус"
        return ctx


class BuildingDelete(LoginRequiredMixin, DeleteView):
    model = Building
    template_name = "inventory/crud/confirm_delete.html"
    success_url = reverse_lazy("inventory:buildings")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Удалить корпус"
        return ctx


class RoomList(LoginRequiredMixin, ListView):
    model = Room
    template_name = "inventory/crud/room_list.html"
    context_object_name = "items"
    paginate_by = 50

    def get_queryset(self):
        qs = Room.objects.select_related("building").order_by("building__name", "number")
        building_id = (self.request.GET.get("building") or "").strip()
        if building_id:
            qs = qs.filter(building_id=building_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["buildings"] = Building.objects.order_by("name")
        ctx["selected_building_id"] = (self.request.GET.get("building") or "").strip()
        return ctx


class RoomCreate(LoginRequiredMixin, CreateView):
    model = Room
    form_class = RoomForm
    template_name = "inventory/crud/form.html"
    success_url = reverse_lazy("inventory:rooms")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Добавить кабинет"
        return ctx


class RoomUpdate(LoginRequiredMixin, UpdateView):
    model = Room
    form_class = RoomForm
    template_name = "inventory/crud/form.html"
    success_url = reverse_lazy("inventory:rooms")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Редактировать кабинет"
        return ctx


class RoomDelete(LoginRequiredMixin, DeleteView):
    model = Room
    template_name = "inventory/crud/confirm_delete.html"
    success_url = reverse_lazy("inventory:rooms")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Удалить кабинет"
        return ctx


class PrinterModelList(LoginRequiredMixin, ListView):
    model = PrinterModel
    template_name = "inventory/crud/printer_model_list.html"
    context_object_name = "items"
    paginate_by = 50
    ordering = ["vendor", "model"]


class PrinterModelCreate(LoginRequiredMixin, CreateView):
    model = PrinterModel
    form_class = PrinterModelForm
    template_name = "inventory/crud/form.html"
    success_url = reverse_lazy("inventory:printer_models")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Добавить модель принтера"
        return ctx


class PrinterModelUpdate(LoginRequiredMixin, UpdateView):
    model = PrinterModel
    form_class = PrinterModelForm
    template_name = "inventory/crud/form.html"
    success_url = reverse_lazy("inventory:printer_models")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Редактировать модель принтера"
        return ctx


class PrinterModelDelete(LoginRequiredMixin, DeleteView):
    model = PrinterModel
    template_name = "inventory/crud/confirm_delete.html"
    success_url = reverse_lazy("inventory:printer_models")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Удалить модель принтера"
        return ctx


class CartridgeModelList(LoginRequiredMixin, ListView):
    model = CartridgeModel
    template_name = "inventory/crud/cartridge_model_list.html"
    context_object_name = "items"
    paginate_by = 50
    ordering = ["vendor", "code"]


class CartridgeModelCreate(LoginRequiredMixin, CreateView):
    model = CartridgeModel
    form_class = CartridgeModelForm
    template_name = "inventory/crud/form.html"
    success_url = reverse_lazy("inventory:cartridge_models")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Добавить модель картриджа"
        return ctx


class CartridgeModelUpdate(LoginRequiredMixin, UpdateView):
    model = CartridgeModel
    form_class = CartridgeModelForm
    template_name = "inventory/crud/form.html"
    success_url = reverse_lazy("inventory:cartridge_models")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Редактировать модель картриджа"
        return ctx


class CartridgeModelDelete(LoginRequiredMixin, DeleteView):
    model = CartridgeModel
    template_name = "inventory/crud/confirm_delete.html"
    success_url = reverse_lazy("inventory:cartridge_models")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Удалить модель картриджа"
        return ctx


class PrinterList(LoginRequiredMixin, ListView):
    model = Printer
    template_name = "inventory/crud/printer_list.html"
    context_object_name = "items"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            Printer.objects
            .select_related("room", "room__building", "printer_model")
        )

        building_id = (self.request.GET.get("building") or "").strip()
        if building_id:
            qs = qs.filter(room__building_id=building_id)

        # Нормальная сортировка кабинетов: корпус -> номер кабинета (числом) -> строкой
        # Реализуем "натуральную" сортировку для PostgreSQL.
        if connection.vendor == "postgresql":
            # Вытаскиваем только цифры из room.number: "2-14" -> "214", "101" -> "101"
            digits_only = Func(
                "room__number",
                Value(r"[^0-9]"),
                Value(""),
                Value("g"),
                function="regexp_replace",
            )

            qs = qs.annotate(
                room_num_int=Coalesce(
                    Cast(NullIf(digits_only, Value("")), IntegerField()),
                    Value(0),
                )
            ).order_by(
                "room__building__name",
                "room_num_int",
                "room__number",
                "printer_model__vendor",
                "printer_model__model",
                "inventory_tag",
            )
        else:
            # Фолбэк: без извлечения чисел (для SQLite/MySQL).
            qs = qs.order_by(
                "room__building__name",
                "room__number",
                "printer_model__vendor",
                "printer_model__model",
                "inventory_tag",
            )

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["buildings"] = Building.objects.order_by("name")
        ctx["selected_building_id"] = (self.request.GET.get("building") or "").strip()
        return ctx


class PrinterCreate(LoginRequiredMixin, CreateView):
    model = Printer
    form_class = PrinterForm
    template_name = "inventory/crud/printer_form.html"
    success_url = reverse_lazy("inventory:printers")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        building_id = (self.request.GET.get("building") or "").strip()
        kwargs["building_id"] = building_id or None
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Добавить принтер"

        building_id = (self.request.GET.get("building") or "").strip()
        ctx["selected_building_id"] = building_id
        return ctx


class PrinterUpdate(LoginRequiredMixin, UpdateView):
    model = Printer
    form_class = PrinterForm
    template_name = "inventory/crud/printer_form.html"
    success_url = reverse_lazy("inventory:printers")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        building_id = (self.request.GET.get("building") or "").strip()
        # Если в URL не передали building — оставляем None, форма сама подставит initial из instance.room.building
        kwargs["building_id"] = building_id or None
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Редактировать принтер"

        building_id = (self.request.GET.get("building") or "").strip()
        ctx["selected_building_id"] = building_id
        return ctx


class PrinterDelete(LoginRequiredMixin, DeleteView):
    model = Printer
    template_name = "inventory/crud/confirm_delete.html"
    success_url = reverse_lazy("inventory:printers")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Удалить принтер"
        return ctx