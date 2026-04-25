from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter(name="money")
def money(value, mode: str = "") -> str:
    """Format a number as US dollar currency.

    - `{{ v|money }}`             → '$1,234.56' / '−$1,234.56' / '—' for None or invalid.
    - `{{ v|money:"signed" }}`    → adds '+' prefix on positives ('+$523.10').
    - `{{ v|money:"liability" }}` → always prefixes '−' (liabilities are stored positive but displayed negative).
    """
    if value is None or value == "":
        return "—"
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return "—"

    is_negative = d < 0
    abs_str = f"{abs(d):,.2f}"
    formatted = f"${abs_str}"

    if mode == "liability":
        return f"−{formatted}"
    if is_negative:
        return f"−{formatted}"  # U+2212 minus sign for typographic alignment with monospace font
    if mode == "signed":
        return f"+{formatted}"
    return formatted
