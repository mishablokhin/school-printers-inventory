from django import template

register = template.Library()

@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except Exception:
        return None

@register.filter
def short_fio(value):
    """
    Сокращение полного ФИО до фамилии и инициалов
    """
    if not value:
        return value

    parts = value.strip().split()

    if len(parts) == 1:
        return parts[0]

    last_name = parts[0]
    initials = []

    for p in parts[1:]:
        if p:
            initials.append(p[0] + ".")

    return f"{last_name} {' '.join(initials)}"


@register.simple_tag
def stock_key(cartridge_id: int, on_balance: int) -> str:
    """Ключ для stock_map: 'cartridge_id:0/1'."""
    return f"{cartridge_id}:{int(on_balance)}"


@register.simple_tag
def bstock_key(cartridge_id: int, building_id: int) -> str:
    """
    Ключ для карты остатков по корпусам:
      'cartridge_id:building_id' -> {'on': qty, 'off': qty}
    """
    return f"{cartridge_id}:{building_id}"