from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("banking", "0003_transaction_display_name"),
    ]

    operations = [
        migrations.AlterField(
            model_name="institution",
            name="provider",
            field=models.CharField(
                choices=[("simplefin", "SimpleFIN"), ("teller", "Teller")],
                default="simplefin",
                max_length=20,
            ),
        ),
    ]
