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

        cartridges_qs = (
            CartridgeModel.objects
            .prefetch_related("compatible_printers")
            .order_by("vendor", "code")
        )

        if q:
            cartridges_qs = (
                cartridges_qs.filter(
                    Q(vendor__icontains=q) |
                    Q(code__icontains=q) |
                    Q(title__icontains=q) |
                    Q(compatible_printers__vendor__icontains=q) |
                    Q(compatible_printers__model__icontains=q)
                ).distinct()
            )

        cartridges = list(cartridges_qs)
        buildings = list(Building.objects.order_by("name"))

        # global stock: "cartridge_id:0/1" -> qty
        stock_map = {
            f"{s.cartridge_id}:{1 if s.on_balance else 0}": s.qty
            for s in GlobalStock.objects.all()
        }

        # building stock: "cartridge_id:building_id" -> {"on": qty, "off": qty}
        building_stock_map = {}
        for s in BuildingStock.objects.all():
            key = f"{s.cartridge_id}:{s.building_id}"
            bucket = building_stock_map.setdefault(key, {"on": 0, "off": 0})
            if s.on_balance:
                bucket["on"] = s.qty
            else:
                bucket["off"] = s.qty

        # ✅ одна строка = одна модель картриджа
        stock_rows = [{"cartridge": c} for c in cartridges]

        ctx.update({
            "q": q,
            "stock_rows": stock_rows,
            "stock_map": stock_map,
            "buildings": buildings,
            "building_stock_map": building_stock_map,
        })
        return ctx


class BuildingStatsView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/building_stats.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        building = Building.objects.get(pk=kwargs["pk"])
        cartridges = (
            CartridgeModel.objects
            .prefetch_related("compatible_printers")
            .order_by("vendor", "code")
        )

        # "cartridge_id" -> {"on": qty, "off": qty}
        stock_map = {}
        for s in BuildingStock.objects.filter(building=building):
            bucket = stock_map.setdefault(s.cartridge_id, {"on": 0, "off": 0})
            if s.on_balance:
                bucket["on"] = s.qty
            else:
                bucket["off"] = s.qty

        ctx.update({
            "building": building,
            "cartridges": cartridges,
            "stock_map": stock_map,
        })
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
            for field, errors in (e.message_dict or {}).items():
                for msg in errors:
                    form.add_error(field if field in form.fields else None, msg)
            return self.form_invalid(form)
        except ValueError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

        return redirect(self.success_url)


class StockOutCreateView(LoginRequiredMixin, CreateView):
    template_name = "inventory/stock_out.html"
    form_class = StockOutForm
    success_url = reverse_lazy("inventory:journal")

    def _get_ids(self):
        src = self.request.POST if self.request.method == "POST" else self.request.GET
        building_id = (src.get("building") or "").strip()
        room_id = (src.get("room") or "").strip()
        printer_id = (src.get("printer") or "").strip()
        cartridge_variant = (src.get("cartridge_variant") or "").strip()
        return building_id, room_id, printer_id, cartridge_variant

    def _parse_variant(self, cartridge_variant: str):
        if cartridge_variant and ":" in cartridge_variant:
            c_id, flag = cartridge_variant.split(":", 1)
            if c_id.isdigit() and flag in ("0", "1"):
                return int(c_id), (flag == "1")
        return None, None

    def _calc_stock(self, cartridge_id: int, on_balance: bool, building_id: int | None):
        global_qty = (
            GlobalStock.objects
            .filter(cartridge_id=cartridge_id, on_balance=on_balance)
            .values_list("qty", flat=True)
            .first()
        )
        global_qty = int(global_qty or 0)

        building_qty = None
        if building_id:
            building_qty = (
                BuildingStock.objects
                .filter(building_id=building_id, cartridge_id=cartridge_id, on_balance=on_balance)
                .values_list("qty", flat=True)
                .first()
            )
            building_qty = int(building_qty or 0)

        # корпуса-источники (где qty > 0), кроме выбранного корпуса назначения
        src_qs = (
            BuildingStock.objects
            .select_related("building")
            .filter(cartridge_id=cartridge_id, on_balance=on_balance, qty__gt=0)
        )
        if building_id:
            src_qs = src_qs.exclude(building_id=building_id)

        available_source_buildings = [
            {"id": s.building_id, "name": s.building.name, "qty": s.qty}
            for s in src_qs.order_by("building__name")
        ]

        return global_qty, building_qty, available_source_buildings

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        building_id, room_id, printer_id, cartridge_variant = self._get_ids()

        # посчитаем доступные корпуса-источники, чтобы ограничить queryset source_building
        src_ids = None
        c_id, on_balance = self._parse_variant(cartridge_variant)
        if c_id and on_balance is not None:
            try:
                b_id_int = int(building_id) if building_id else None
            except ValueError:
                b_id_int = None

            _, _, available = self._calc_stock(c_id, on_balance, b_id_int)
            src_ids = [x["id"] for x in available]

        kwargs.update({
            "building_id": building_id or None,
            "room_id": room_id or None,
            "printer_id": printer_id or None,
            "source_building_ids": src_ids,  # ✅ важно
        })
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        building_id, room_id, printer_id, cartridge_variant = self._get_ids()

        selected_building = Building.objects.filter(pk=building_id).first() if building_id else None
        selected_room = (
            Room.objects.select_related("building")
            .filter(pk=room_id).first()
            if room_id else None
        )
        selected_printer = (
            Printer.objects.select_related("printer_model", "room", "room__building")
            .filter(pk=printer_id).first()
            if printer_id else None
        )

        printers_in_room = []
        if selected_room:
            printers_in_room = (
                Printer.objects
                .select_related("printer_model")
                .filter(room=selected_room)
                .order_by("printer_model__vendor", "printer_model__model", "inventory_tag")
            )

        selected_cartridge = None
        selected_on_balance = None
        building_qty = None
        global_qty = None
        available_source_buildings = []
        can_issue = True

        c_id, on_balance = self._parse_variant(cartridge_variant)
        if c_id and on_balance is not None:
            selected_cartridge = CartridgeModel.objects.filter(pk=c_id).first()
            selected_on_balance = on_balance

            if selected_building and selected_cartridge:
                global_qty, building_qty, available_source_buildings = self._calc_stock(
                    cartridge_id=selected_cartridge.id,
                    on_balance=selected_on_balance,
                    building_id=selected_building.id,
                )

                # можно ли выдать: либо есть в выбранном корпусе, либо есть в других (и общий остаток позволяет)
                try:
                    desired_qty = int(self.request.GET.get("qty") or self.request.POST.get("qty") or 1)
                except Exception:
                    desired_qty = 1

                can_issue = (building_qty >= desired_qty) or (len(available_source_buildings) > 0 and global_qty >= desired_qty)

                # важно: если список источников есть, ограничим поле в форме (вдобавок к get_form_kwargs)
                form = ctx.get("form")
                if form:
                    if available_source_buildings:
                        form.fields["source_building"].queryset = Building.objects.filter(
                            id__in=[x["id"] for x in available_source_buildings]
                        ).order_by("name")
                    else:
                        form.fields["source_building"].queryset = Building.objects.none()

        ctx.update({
            "selected_building": selected_building,
            "selected_room": selected_room,
            "selected_printer": selected_printer,
            "printers_in_room": printers_in_room,

            "selected_cartridge": selected_cartridge,
            "selected_on_balance": selected_on_balance,

            "building_qty": building_qty,
            "global_qty": global_qty,
            "available_source_buildings": available_source_buildings,
            "can_issue": can_issue,
        })
        return ctx

    def form_valid(self, form):
        tx = form.save(commit=False)
        tx.created_by = self.request.user
        tx.tx_type = StockTransaction.Type.OUT

        # куда выдаём (корпус назначения) – по принтеру
        destination_building = tx.printer.room.building if tx.printer else None

        # откуда списываем (корпус-склад)
        source_building = form.cleaned_data.get("source_building")

        # по умолчанию списываем из корпуса назначения
        tx.building = source_building or destination_building

        # cartridge/on_balance проставлены в форме
        if not tx.cartridge_id:
            form.add_error("cartridge_variant", "Выберите картридж.")
            return self.form_invalid(form)

        tx.issued_to = (
            tx.printer.room.owner_name
            if (tx.printer and tx.printer.room and tx.printer.room.owner_name)
            else ""
        )

        # проверка остатков в корпусе-источнике
        bqty = (
            BuildingStock.objects
            .filter(building_id=tx.building_id, cartridge_id=tx.cartridge_id, on_balance=tx.on_balance)
            .values_list("qty", flat=True)
            .first()
        ) or 0

        if bqty < tx.qty:
            form.add_error(None, "Недостаточно картриджей выбранного типа (баланс/не баланс) в корпусе-складе.")
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