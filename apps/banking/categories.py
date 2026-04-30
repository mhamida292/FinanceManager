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
