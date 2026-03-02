from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect

from inventory.utils.delete_inspector import build_delete_report


class DeleteConfirmContextMixin:
    """
    Добавляет в контекст:
      - can_delete
      - consequences
      - blockers
      - delete_subject (человекочитаемое имя объекта)
      - delete_kind (тип объекта для заголовка/фраз)
    И блокирует POST, если удаление невозможно.
    """

    delete_kind = "объект"  # можно переопределять в DeleteView

    def get_delete_report(self):
        return build_delete_report(self.get_object())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        obj = ctx.get("object") or self.get_object()
        report = self.get_delete_report()

        ctx.update({
            "delete_kind": getattr(self, "delete_kind", "объект"),
            "delete_subject": str(obj),
            "can_delete": report.can_delete,
            "consequences": report.consequences,
            "blockers": report.blockers,
        })
        return ctx

    def post(self, request, *args, **kwargs):
        report = self.get_delete_report()
        if not report.can_delete:
            messages.error(request, "Удаление невозможно: есть связанные записи.")
            return redirect(request.path)
        return super().post(request, *args, **kwargs)