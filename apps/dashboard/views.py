from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services import net_worth_history, net_worth_summary


@login_required
def dashboard(request):
    summary = net_worth_summary(request.user)
    history = net_worth_history(request.user, days=30)
    return render(request, "dashboard/index.html", {"summary": summary, "history": history})
