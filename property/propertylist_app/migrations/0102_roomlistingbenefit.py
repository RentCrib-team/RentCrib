from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0101_city_image_is_approved"),
    ]

    operations = [
        migrations.CreateModel(
            name="RoomListingBenefit",
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
                ("granted_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "consumed_reason",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("automatic_extension", "Automatic extension"),
                            ("future_relist", "Future relist"),
                        ],
                        default="",
                        max_length=32,
                    ),
                ),
                ("complimentary_period_start", models.DateField(blank=True, null=True)),
                ("complimentary_period_end", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "granted_from_payment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="granted_listing_benefits",
                        to="propertylist_app.payment",
                    ),
                ),
                (
                    "room",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="complimentary_listing_benefit",
                        to="propertylist_app.room",
                    ),
                ),
            ],
        ),
    ]
