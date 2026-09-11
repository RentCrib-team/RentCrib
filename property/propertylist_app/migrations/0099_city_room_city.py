from django.db import migrations, models
import django.db.models.deletion
from django.db.models.functions import Lower


class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0098_tenancy_source_booking"),
    ]

    operations = [
        migrations.CreateModel(
            name="City",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                (
                    "slug",
                    models.SlugField(
                        blank=True,
                        db_index=True,
                        max_length=120,
                        unique=True,
                    ),
                ),
                (
                    "image",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to="city_images/",
                    ),
                ),
                (
                    "image_alt",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=160,
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        db_index=True,
                        default=True,
                    ),
                ),
                (
                    "is_featured",
                    models.BooleanField(
                        db_index=True,
                        default=False,
                    ),
                ),
                (
                    "display_order",
                    models.PositiveIntegerField(
                        db_index=True,
                        default=0,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["display_order", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="city",
            constraint=models.UniqueConstraint(
                Lower("name"),
                name="uq_city_name_lower",
            ),
        ),
        migrations.AddField(
            model_name="room",
            name="city",
            field=models.ForeignKey(
                blank=True,
                help_text="Canonical city used for city browsing and city cards.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="rooms",
                to="propertylist_app.city",
            ),
        ),
    ]
