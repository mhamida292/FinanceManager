import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("banking", "0005_transaction_category"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(help_text="Lowercase identifier; unique per user.", max_length=30)),
                ("label", models.CharField(help_text="Display name shown in UI.", max_length=50)),
                ("color", models.CharField(help_text="Hex color like '#7a9a6a'.", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="custom_categories", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["label"]},
        ),
        migrations.AddConstraint(
            model_name="usercategory",
            constraint=models.UniqueConstraint(fields=("user", "slug"), name="uniq_usercategory_slug_per_user"),
        ),
    ]
