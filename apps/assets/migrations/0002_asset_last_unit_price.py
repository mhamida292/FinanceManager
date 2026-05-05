from decimal import Decimal

from django.db import migrations, models


def _backfill_unit_price(apps, schema_editor):
    Asset = apps.get_model("assets", "Asset")
    for asset in Asset.objects.filter(kind="scraped"):
        if asset.quantity and asset.quantity > 0 and asset.current_value and asset.current_value > 0:
            asset.last_unit_price = (asset.current_value / asset.quantity).quantize(Decimal("0.0001"))
            asset.save(update_fields=["last_unit_price"])


def _noop_reverse(apps, schema_editor):
    """Reverse just drops the column; nothing to undo at the data level."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="asset",
            name="last_unit_price",
            field=models.DecimalField(
                blank=True, decimal_places=4, max_digits=18, null=True,
                help_text="Per-unit scraped price from the most recent successful refresh. "
                          "Null for manual assets and for scraped assets never refreshed.",
            ),
        ),
        migrations.RunPython(_backfill_unit_price, _noop_reverse),
    ]
