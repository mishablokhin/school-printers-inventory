from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, TemplateView

from .forms import (
    BuildingForm, RoomForm, PrinterModelForm, CartridgeModelForm, PrinterForm,
    StockInForm, StockOutForm
)
from .models import (
    Building, Room, PrinterModel, CartridgeModel, Printer,
    GlobalStock, BuildingStock, StockTransaction
)


# -------------------------
# Остатки и журнал
# -------------------------

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cartridges = CartridgeModel.objects.prefetch_related("compatible_printers").order_by("vendor", "code")
        stock_map = {s.cartridge_id: s.qty for s in GlobalStock.objects.all()}
        buildings = Building.objects.order_by("name")
        ctx.update({"cartridges": cartridges, "stock_map": stock_map, "buildings": buildings})
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
        tx.save()
        return redirect(self.success_url)


class StockOutCreateView(LoginRequiredMixin, CreateView):
    template_name = "inventory/stock_out.html"
    form_class = StockOutForm
    success_url = reverse_lazy("inventory:journal")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        # Фильтрация списка картриджей по выбранному принтеру (двухшаговая форма)
        printer_id = self.request.GET.get("printer") or self.request.POST.get("printer")
        if printer_id:
            try:
                printer = Printer.objects.select_related("printer_model", "room__building").get(pk=printer_id)
                compatible = CartridgeModel.objects.filter(compatible_printers=printer.printer_model).order_by("vendor", "code")
                form.fields["cartridge"].queryset = compatible
                form.initial["printer"] = printer
            except Printer.DoesNotExist:
                pass
        return form

    def form_valid(self, form):
        tx = form.save(commit=False)
        tx.created_by = self.request.user
        tx.tx_type = StockTransaction.Type.OUT
        tx.building = tx.printer.room.building if tx.printer else None
        tx.save()
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
            .order_by("room__building__name", "room__number", "printer_model__vendor", "printer_model__model")
        )
        building_id = (self.request.GET.get("building") or "").strip()
        if building_id:
            qs = qs.filter(room__building_id=building_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["buildings"] = Building.objects.order_by("name")
        ctx["selected_building_id"] = (self.request.GET.get("building") or "").strip()
        return ctx


class PrinterCreate(LoginRequiredMixin, CreateView):
    model = Printer
    form_class = PrinterForm
    template_name = "inventory/crud/form.html"
    success_url = reverse_lazy("inventory:printers")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Добавить принтер"
        return ctx


class PrinterUpdate(LoginRequiredMixin, UpdateView):
    model = Printer
    form_class = PrinterForm
    template_name = "inventory/crud/form.html"
    success_url = reverse_lazy("inventory:printers")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Редактировать принтер"
        return ctx


class PrinterDelete(LoginRequiredMixin, DeleteView):
    model = Printer
    template_name = "inventory/crud/confirm_delete.html"
    success_url = reverse_lazy("inventory:printers")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Удалить принтер"
        return ctx