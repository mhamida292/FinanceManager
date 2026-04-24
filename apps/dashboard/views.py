from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services import net_worth_summary


@login_required
def dashboard(request):
    summary = net_worth_summary(request.user)
    return render(request, "dashboard/index.html", {"summary": summary})
