from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import StockTransaction
from .services import apply_transaction


@receiver(post_save, sender=StockTransaction)
def on_tx_created(sender, instance: StockTransaction, created, **kwargs):
    if not created:
        # упрощение: редактирование движений пока не поддерживаем,
        # иначе придётся делать «ревёрс» прошлых значений
        return
    apply_transaction(instance)