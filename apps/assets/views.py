from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .models import Asset
from .services import create_asset, delete_asset, refresh_scraped_assets, update_asset


def _decimal_or_default(raw: str, default: Decimal) -> Decimal:
    raw = (raw or "").strip()
    if not raw:
        return default
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"Not a valid number: {raw!r}")


@login_required
def assets_list(request):
    assets = Asset.objects.for_user(request.user)
    total = sum((a.current_value for a in assets), Decimal("0"))
    return render(request, "assets/assets_list.html", {
        "assets": assets,
        "total": total,
    })


@login_required
@require_http_methods(["GET", "POST"])
def add_asset(request):
    if request.method == "POST":
        kind = request.POST.get("kind", "manual")
        name = request.POST.get("name", "").strip()
        notes = request.POST.get("notes", "").strip()

        if not name:
            messages.error(request, "Name is required.")
            return render(request, "assets/asset_form.html", {"mode": "add", "data": request.POST})

        try:
            if kind == "scraped":
                source_url = request.POST.get("source_url", "").strip()
                css_selector = request.POST.get("css_selector", "").strip()
                unit = request.POST.get("unit", "").strip()
                quantity = _decimal_or_default(request.POST.get("quantity", ""), Decimal("1"))
                if not source_url:
                    messages.error(request, "URL is required for scraped assets.")
                    return render(request, "assets/asset_form.html", {"mode": "add", "data": request.POST})
                asset = create_asset(
                    user=request.user, kind="scraped", name=name, notes=notes,
                    source_url=source_url, css_selector=css_selector, unit=unit, quantity=quantity,
                )
                refresh_scraped_assets(user=request.user)
                messages.success(request, f"Added {name}. Refresh ran — check the list for the value.")
            else:
                current_value = _decimal_or_default(request.POST.get("current_value", ""), Decimal("0"))
                asset = create_asset(
                    user=request.user, kind="manual", name=name, notes=notes,
                    current_value=current_value,
                )
                messages.success(request, f"Added {name}.")
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "assets/asset_form.html", {"mode": "add", "data": request.POST})

        return HttpResponseRedirect(reverse("assets:list"))

    return render(request, "assets/asset_form.html", {"mode": "add", "data": {"kind": "manual"}})


@login_required
@require_http_methods(["GET", "POST"])
def edit_asset(request, asset_id):
    asset = get_object_or_404(Asset.objects.for_user(request.user), pk=asset_id)
    if request.method == "POST":
        fields = {"name": request.POST.get("name", "").strip(),
                  "notes": request.POST.get("notes", "").strip()}
        try:
            if asset.kind == "scraped":
                fields["source_url"] = request.POST.get("source_url", "").strip()
                fields["css_selector"] = request.POST.get("css_selector", "").strip()
                fields["unit"] = request.POST.get("unit", "").strip()
                fields["quantity"] = _decimal_or_default(request.POST.get("quantity", ""), asset.quantity)
            else:
                fields["current_value"] = _decimal_or_default(
                    request.POST.get("current_value", ""), asset.current_value
                )
            update_asset(asset, **fields)
            messages.success(request, f"Updated {asset.name}.")
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "assets/asset_form.html", {"mode": "edit", "asset": asset, "data": request.POST})
        return HttpResponseRedirect(reverse("assets:list"))

    return render(request, "assets/asset_form.html", {"mode": "edit", "asset": asset, "data": {
        "kind": asset.kind, "name": asset.name, "notes": asset.notes, "quantity": asset.quantity,
        "unit": asset.unit, "source_url": asset.source_url, "css_selector": asset.css_selector,
        "current_value": asset.current_value,
    }})


@login_required
@require_http_methods(["GET", "POST"])
def delete_asset_view(request, asset_id):
    asset = get_object_or_404(Asset.objects.for_user(request.user), pk=asset_id)
    if request.method == "POST":
        name = asset.name
        delete_asset(asset)
        messages.success(request, f"Deleted {name}.")
        return HttpResponseRedirect(reverse("assets:list"))
    return render(request, "assets/asset_confirm_delete.html", {"asset": asset})


@login_required
@require_http_methods(["POST"])
def refresh_prices(request):
    result = refresh_scraped_assets(user=request.user)
    if result.failed:
        messages.warning(request, f"Refreshed {result.updated}; {len(result.failed)} failed.")
        for asset_id, err in result.failed:
            messages.error(request, f"Asset {asset_id}: {err}")
    else:
        messages.success(request, f"Refreshed {result.updated} scraped asset(s).")
    return HttpResponseRedirect(reverse("assets:list"))
