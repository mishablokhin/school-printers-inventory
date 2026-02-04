from django.dispatch import receiver
from allauth.socialaccount.signals import social_account_added, social_account_updated

def _sync_full_name_from_extra_data(user, extra_data: dict):
    extra_data = extra_data or {}

    # В твоём Nextcloud "name" уже содержит "Фамилия Имя Отчество" корректно.
    display = (extra_data.get("name") or "").strip()

    if display:
        parts = [p for p in display.split() if p]
        # Сохраняем в стандартные поля Django максимально логично:
        # first_name = Имя, last_name = "Фамилия Отчество"
        if len(parts) >= 3:
            family, given, middle = parts[0], parts[1], " ".join(parts[2:])
            user.first_name = given
            user.last_name = f"{family} {middle}".strip()
        elif len(parts) == 2:
            family, given = parts
            user.first_name = given
            user.last_name = family
        else:
            user.first_name = display
        user.save(update_fields=["first_name", "last_name"])

@receiver(social_account_added)
def on_social_account_added(request, sociallogin, **kwargs):
    _sync_full_name_from_extra_data(sociallogin.user, sociallogin.account.extra_data)

@receiver(social_account_updated)
def on_social_account_updated(request, sociallogin, **kwargs):
    _sync_full_name_from_extra_data(sociallogin.user, sociallogin.account.extra_data)
