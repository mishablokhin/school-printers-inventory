from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from datetime import datetime


def home(request):
    if request.user.is_authenticated:
        return redirect("me")
    return render(request, "login.html")


@login_required
def me(request):
    sa = request.user.socialaccount_set.first()
    extra = sa.extra_data if sa else {}

    full_name = (
        extra.get("userinfo", {}).get("name")
        or extra.get("id_token", {}).get("name")
        or request.user.get_username()
    )

    hour = datetime.now().hour
    if 5 <= hour < 12:
        greeting = "Доброе утро"
    elif 12 <= hour < 18:
        greeting = "Добрый день"
    else:
        greeting = "Добрый вечер"

    return render(
        request,
        "me.html",
        {
            "greeting": greeting,
            "full_name": full_name,
        },
    )


def logout_view(request):
    logout(request)
    return redirect("home")