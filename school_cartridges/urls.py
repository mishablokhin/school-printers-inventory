from django.contrib import admin
from django.urls import path, include
from core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", core_views.home, name="home"),
    path("me/", core_views.me, name="me"),
    path("logout/", core_views.logout_view, name="logout"),
    path("inventory/", include("inventory.urls")),
]
