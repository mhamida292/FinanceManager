from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.banking.services import spending_breakdown

from .services import net_worth_history, net_worth_summary


@login_required
def dashboard(request):
    summary = net_worth_summary(request.user)
    history = net_worth_history(request.user, days=30)

    today = date.today()
    spending_rows = spending_breakdown(request.user, today - timedelta(days=29), today)

    return render(request, "dashboard/index.html", {
        "summary": summary,
        "history": history,
        "spending_rows": spending_rows[:5],
        "spending_total": sum((r.total for r in spending_rows), Decimal("0")),
    })
