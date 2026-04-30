from apps.banking.categories import (
    ALL_CATEGORIES, CATEGORY_CHOICES, CATEGORY_COLORS, CATEGORY_LABELS,
    INCOME_CATEGORIES, SPENDING_CATEGORIES, TRANSFER_CATEGORIES,
    map_teller_category,
)


def test_spending_categories_contains_all_14():
    expected = {
        "groceries", "dining", "transportation", "utilities", "bills",
        "housing", "health", "entertainment", "shopping", "software",
        "travel", "personal", "charity", "other",
    }
    assert set(SPENDING_CATEGORIES) == expected


def test_all_categories_includes_income_transfer_uncategorized():
    assert "income" in ALL_CATEGORIES
    assert "transfer" in ALL_CATEGORIES
    assert "uncategorized" in ALL_CATEGORIES
    assert len(ALL_CATEGORIES) == 17


def test_category_choices_is_list_of_pairs():
    assert all(isinstance(c, tuple) and len(c) == 2 for c in CATEGORY_CHOICES)
    assert ("groceries", "Groceries") in CATEGORY_CHOICES


def test_category_colors_covers_all_categories():
    for c in ALL_CATEGORIES:
        assert c in CATEGORY_COLORS, f"missing color for {c}"
        assert CATEGORY_COLORS[c].startswith("#")


def test_category_labels_covers_all_categories():
    for c in ALL_CATEGORIES:
        assert c in CATEGORY_LABELS


def test_map_teller_category_known_values():
    assert map_teller_category("groceries") == "groceries"
    assert map_teller_category("bar") == "dining"
    assert map_teller_category("transport") == "transportation"
    assert map_teller_category("transportation") == "transportation"
    assert map_teller_category("fuel") == "transportation"
    assert map_teller_category("phone") == "bills"
    assert map_teller_category("insurance") == "bills"
    assert map_teller_category("loan") == "bills"
    assert map_teller_category("accommodation") == "housing"
    assert map_teller_category("home") == "housing"
    assert map_teller_category("clothing") == "shopping"
    assert map_teller_category("software") == "software"
    assert map_teller_category("charity") == "charity"
    assert map_teller_category("income") == "income"
    assert map_teller_category("tax") == "other"
    assert map_teller_category("advertising") == "other"


def test_map_teller_category_unknown_falls_through():
    assert map_teller_category("flying-saucers") == "uncategorized"


def test_map_teller_category_none_or_empty():
    assert map_teller_category(None) == "uncategorized"
    assert map_teller_category("") == "uncategorized"
