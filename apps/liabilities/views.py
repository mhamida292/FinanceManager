from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .models import Liability
from .services import liabilities_for, total_liabilities


def _decimal_or_zero(raw: str) -> Decimal:
    raw = (raw or "").strip()
    if not raw:
        return Decimal("0")
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"Not a valid number: {raw!r}")


@login_required
def liabilities_list(request):
    rows = liabilities_for(request.user)
    return render(request, "liabilities/liabilities_list.html", {
        "rows": rows,
        "total": total_liabilities(request.user),
    })


@login_required
@require_http_methods(["GET", "POST"])
def add_liability(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        notes = request.POST.get("notes", "").strip()
        if not name:
            messages.error(request, "Name is required.")
            return render(request, "liabilities/liability_form.html", {"mode": "add", "data": request.POST})
        try:
            balance = _decimal_or_zero(request.POST.get("balance", ""))
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "liabilities/liability_form.html", {"mode": "add", "data": request.POST})
        Liability.objects.create(user=request.user, name=name, balance=balance, notes=notes)
        messages.success(request, f"Added {name}.")
        return HttpResponseRedirect(reverse("liabilities:list"))
    return render(request, "liabilities/liability_form.html", {"mode": "add", "data": {}})


@login_required
@require_http_methods(["GET", "POST"])
def edit_liability(request, liability_id):
    liability = get_object_or_404(Liability.objects.for_user(request.user), pk=liability_id)
    if request.method == "POST":
        liability.name = request.POST.get("name", "").strip() or liability.name
        liability.notes = request.POST.get("notes", "").strip()
        try:
            liability.balance = _decimal_or_zero(request.POST.get("balance", ""))
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "liabilities/liability_form.html", {"mode": "edit", "liability": liability, "data": request.POST})
        liability.save()
        messages.success(request, f"Updated {liability.name}.")
        return HttpResponseRedirect(reverse("liabilities:list"))
    return render(request, "liabilities/liability_form.html", {"mode": "edit", "liability": liability, "data": {
        "name": liability.name, "balance": liability.balance, "notes": liability.notes,
    }})


@login_required
@require_http_methods(["GET", "POST"])
def delete_liability(request, liability_id):
    liability = get_object_or_404(Liability.objects.for_user(request.user), pk=liability_id)
    if request.method == "POST":
        name = liability.name
        liability.delete()
        messages.success(request, f"Deleted {name}.")
        return HttpResponseRedirect(reverse("liabilities:list"))
    return render(request, "liabilities/liability_confirm_delete.html", {"liability": liability})
