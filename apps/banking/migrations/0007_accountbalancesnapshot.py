import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("banking", "0006_usercategory"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountBalanceSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(db_index=True)),
                ("balance", models.DecimalField(decimal_places=2, max_digits=14)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="balance_snapshots", to="banking.account")),
            ],
            options={"ordering": ["-date"]},
        ),
        migrations.AddConstraint(
            model_name="accountbalancesnapshot",
            constraint=models.UniqueConstraint(fields=("account", "date"), name="uniq_balance_snapshot_per_day"),
        ),
    ]
