"""Category vocabulary and Teller mapping. Single source of truth."""

SPENDING_CATEGORIES = [
    "groceries", "dining", "transportation", "utilities", "bills",
    "housing", "health", "entertainment", "shopping", "software",
    "travel", "personal", "charity", "other",
]

INCOME_CATEGORIES = ["income"]
TRANSFER_CATEGORIES = ["transfer"]
UNCATEGORIZED = "uncategorized"

ALL_CATEGORIES = SPENDING_CATEGORIES + INCOME_CATEGORIES + TRANSFER_CATEGORIES + [UNCATEGORIZED]

CATEGORY_LABELS = {c: c.replace("_", " ").title() for c in ALL_CATEGORIES}

CATEGORY_CHOICES = [(c, CATEGORY_LABELS[c]) for c in ALL_CATEGORIES]

# Quiet-theme-aligned palette: muted, distinct hues.
CATEGORY_COLORS = {
    "groceries":     "#7a9a6a",
    "dining":        "#c08868",
    "transportation":"#8a8aaa",
    "utilities":     "#c8a868",
    "bills":         "#a87a8a",
    "housing":       "#6a8a9a",
    "health":        "#9b6a7a",
    "entertainment": "#a89a6a",
    "shopping":      "#7a6a9a",
    "software":      "#6a9a8a",
    "travel":        "#9a8a6a",
    "personal":      "#aa7aaa",
    "charity":       "#7aaa9a",
    "other":         "#888888",
    "income":        "#88a877",
    "transfer":      "#5a7aaa",
    "uncategorized": "#444444",
}

# Teller's `details.category` strings → our 14-spending-category vocabulary.
TELLER_TO_FINLAB = {
    "groceries":      "groceries",
    "dining":         "dining",
    "bar":            "dining",
    "transport":      "transportation",
    "transportation": "transportation",
    "fuel":           "transportation",
    "utilities":      "utilities",
    "phone":          "bills",
    "insurance":      "bills",
    "loan":           "bills",
    "accommodation":  "housing",
    "home":           "housing",
    "health":         "health",
    "entertainment":  "entertainment",
    "sport":          "entertainment",
    "shopping":       "shopping",
    "clothing":       "shopping",
    "electronics":    "shopping",
    "software":       "software",
    "charity":        "charity",
    "income":         "income",
    # Fall-through to "other":
    "tax":         "other",
    "education":   "other",
    "investment":  "other",
    "service":     "other",
    "general":     "other",
    "office":      "other",
    "advertising": "other",
}


def map_teller_category(teller_value: str | None) -> str:
    """Translate a Teller category string into a FinLab category.
    Unknown strings, None, and empty strings → 'uncategorized'."""
    if not teller_value:
        return UNCATEGORIZED
    return TELLER_TO_FINLAB.get(teller_value, UNCATEGORIZED)


TRANSFER_PATTERNS = (
    "TRANSFER",
    "XFER",
    "ZELLE",
    "VENMO",
    "CASHAPP",
    "CASH APP",
    "PAYPAL",
    "PAY PAL",
    "WIRE",
    "INTERNAL TRANSFER",
    "ONLINE PAYMENT",
    "MOBILE PAYMENT",
    "ONLINE PYMT",
    "MOBILE PYMT",
    "CARDMEMBER PAYMENT",
    "AUTOMATIC PAYMENT",
    "CC PAYMENT",
    "CREDIT CARD PAYMENT",
    "PYMT",
    "CITI",
    "TO ACCOUNT",
    "FROM ACCOUNT",
    "TO CHECKING",
    "FROM CHECKING",
    "TO SAVINGS",
    "FROM SAVINGS",
)


def is_likely_transfer(payee: str | None, description: str | None) -> bool:
    """Return True if the combined payee + description text matches any
    known transfer keyword (case-insensitive)."""
    text = f"{payee or ''} {description or ''}".upper()
    return any(pat in text for pat in TRANSFER_PATTERNS)


COLOR_PALETTE = [
    "#7a9a6a", "#c08868", "#8a8aaa", "#c8a868", "#a87a8a",
    "#6a8a9a", "#9b6a7a", "#a89a6a", "#7a6a9a", "#6a9a8a",
    "#9a8a6a", "#aa7aaa", "#7aaa9a", "#888888",
]


def get_user_categories(user) -> dict[str, dict]:
    """Return merged dict {slug: {"label": str, "color": str, "kind": str, "custom": bool}}
    of built-in categories + user's custom categories. `kind` is one of:
    'spending', 'income', 'transfer', 'system' (uncategorized)."""
    result: dict[str, dict] = {}
    for slug in ALL_CATEGORIES:
        if slug in INCOME_CATEGORIES:
            kind = "income"
        elif slug in TRANSFER_CATEGORIES:
            kind = "transfer"
        elif slug == UNCATEGORIZED:
            kind = "system"
        else:
            kind = "spending"
        result[slug] = {
            "label": CATEGORY_LABELS[slug],
            "color": CATEGORY_COLORS[slug],
            "kind": kind,
            "custom": False,
        }
    if user is not None and getattr(user, "is_authenticated", False):
        from apps.banking.models import UserCategory
        for uc in UserCategory.objects.filter(user=user):
            result[uc.slug] = {
                "label": uc.label,
                "color": uc.color,
                "kind": "spending",
                "custom": True,
            }
    return result


def is_valid_category_for_user(user, slug: str) -> bool:
    """True if slug is a built-in category OR a custom category owned by user."""
    if slug in ALL_CATEGORIES:
        return True
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    from apps.banking.models import UserCategory
    return UserCategory.objects.filter(user=user, slug=slug).exists()


# Reserved slugs cannot be used for custom categories.
RESERVED_SLUGS = frozenset(ALL_CATEGORIES)
