from django.urls import path
from . import views

app_name = "inventory"

urlpatterns = [
    # Остатки/журнал/движения
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("building/<int:pk>/", views.BuildingStatsView.as_view(), name="building_stats"),
    path("stock/in/", views.StockInCreateView.as_view(), name="stock_in"),
    path("stock/out/", views.StockOutCreateView.as_view(), name="stock_out"),
    path("journal/", views.JournalView.as_view(), name="journal"),

    # CRUD – корпуса школы
    path("buildings/", views.BuildingList.as_view(), name="buildings"),
    path("buildings/add/", views.BuildingCreate.as_view(), name="building_add"),
    path("buildings/<int:pk>/edit/", views.BuildingUpdate.as_view(), name="building_edit"),
    path("buildings/<int:pk>/delete/", views.BuildingDelete.as_view(), name="building_delete"),

    # CRUD – кабинеты
    path("rooms/", views.RoomList.as_view(), name="rooms"),
    path("rooms/add/", views.RoomCreate.as_view(), name="room_add"),
    path("rooms/<int:pk>/edit/", views.RoomUpdate.as_view(), name="room_edit"),
    path("rooms/<int:pk>/delete/", views.RoomDelete.as_view(), name="room_delete"),

    # CRUD – модели принтеров
    path("printer-models/", views.PrinterModelList.as_view(), name="printer_models"),
    path("printer-models/add/", views.PrinterModelCreate.as_view(), name="printer_model_add"),
    path("printer-models/<int:pk>/edit/", views.PrinterModelUpdate.as_view(), name="printer_model_edit"),
    path("printer-models/<int:pk>/delete/", views.PrinterModelDelete.as_view(), name="printer_model_delete"),

    # CRUD – модели картриджей и совместимость
    path("cartridge-models/", views.CartridgeModelList.as_view(), name="cartridge_models"),
    path("cartridge-models/add/", views.CartridgeModelCreate.as_view(), name="cartridge_model_add"),
    path("cartridge-models/<int:pk>/edit/", views.CartridgeModelUpdate.as_view(), name="cartridge_model_edit"),
    path("cartridge-models/<int:pk>/delete/", views.CartridgeModelDelete.as_view(), name="cartridge_model_delete"),

    # CRUD – принтеры
    path("printers/", views.PrinterList.as_view(), name="printers"),
    path("printers/add/", views.PrinterCreate.as_view(), name="printer_add"),
    path("printers/<int:pk>/edit/", views.PrinterUpdate.as_view(), name="printer_edit"),
    path("printers/<int:pk>/delete/", views.PrinterDelete.as_view(), name="printer_delete"),
]