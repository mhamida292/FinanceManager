from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("banking", "0004_alter_institution_provider"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="category",
            field=models.CharField(
                choices=[
                    ("groceries", "Groceries"),
                    ("dining", "Dining"),
                    ("transportation", "Transportation"),
                    ("utilities", "Utilities"),
                    ("bills", "Bills"),
                    ("housing", "Housing"),
                    ("health", "Health"),
                    ("entertainment", "Entertainment"),
                    ("shopping", "Shopping"),
                    ("software", "Software"),
                    ("travel", "Travel"),
                    ("personal", "Personal"),
                    ("charity", "Charity"),
                    ("other", "Other"),
                    ("income", "Income"),
                    ("transfer", "Transfer"),
                    ("uncategorized", "Uncategorized"),
                ],
                db_index=True,
                default="uncategorized",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="category_manual",
            field=models.BooleanField(default=False),
        ),
    ]
