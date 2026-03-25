from django.urls import path

from .views import (
    ExportHomeView,
    ExportTransactionsExcelView,
    ExportStocksExcelView,
)

app_name = "exports"

urlpatterns = [
    path("", ExportHomeView.as_view(), name="home"),
    path("transactions/", ExportTransactionsExcelView.as_view(), name="transactions"),
    path("stocks/", ExportStocksExcelView.as_view(), name="stocks"),
]