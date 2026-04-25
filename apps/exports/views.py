from io import BytesIO
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

from .services import build_workbook


@login_required
def xlsx_export(request):
    wb = build_workbook(user=request.user)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"finance-{date.today().isoformat()}.xlsx"
    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
