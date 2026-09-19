from decimal import Decimal, ROUND_HALF_UP

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


TENANT_TO_LANDLORD = {
    "positives": {
        "responsive": Decimal("1.5"),
        "maintenance_good": Decimal("2.0"),
        "accurate_listing": Decimal("1.5"),
        "respectful_fair": Decimal("1.5"),
    },
    "negatives": {
        "unresponsive": Decimal("1.5"),
        "maintenance_poor": Decimal("2.0"),
        "misleading_listing": Decimal("2.0"),
        "unfair_treatment": Decimal("2.0"),
    },
}

LANDLORD_TO_TENANT = {
    "positives": {
        "clean_and_tidy": Decimal("1.0"),
        "followed_rules": Decimal("1.5"),
        "paid_on_time": Decimal("2.0"),
        "good_communication": Decimal("1.0"),
        "property_care_good": Decimal("1.5"),
        "friendly": Decimal("0.8"),
    },
    "negatives": {
        "messy": Decimal("1.0"),
        "broke_rules": Decimal("1.5"),
        "late_payment": Decimal("2.0"),
        "poor_communication": Decimal("1.0"),
        "property_care_poor": Decimal("1.5"),
        "rude": Decimal("1.0"),
    },
}


def _rating(config, flags):
    selected = set(flags or ())
    positives = config["positives"]
    negatives = config["negatives"]
    positive_score = sum(
        (weight for flag, weight in positives.items() if flag in selected),
        Decimal("0"),
    )
    negative_score = sum(
        (weight for flag, weight in negatives.items() if flag in selected),
        Decimal("0"),
    )
    net = (
        positive_score / sum(positives.values(), Decimal("0"))
        - negative_score / sum(negatives.values(), Decimal("0"))
    )
    score = Decimal("3") + Decimal("2") * net
    score = min(Decimal("5"), max(Decimal("1"), score))
    return score.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def recalculate_checklist_reviews(apps, schema_editor):
    Review = apps.get_model("propertylist_app", "Review")
    configs = {
        "tenant_to_landlord": TENANT_TO_LANDLORD,
        "landlord_to_tenant": LANDLORD_TO_TENANT,
    }

    for review in Review.objects.exclude(review_flags=[]).iterator():
        config = configs.get(review.role)
        if config is None:
            continue
        review.overall_rating = _rating(config, review.review_flags)
        review.save(update_fields=["overall_rating"])


class Migration(migrations.Migration):
    dependencies = [
        ("propertylist_app", "0103_grandfather_legacy_listing_benefits"),
    ]

    operations = [
        migrations.AlterField(
            model_name="review",
            name="overall_rating",
            field=models.DecimalField(
                decimal_places=1,
                default=3,
                max_digits=2,
                validators=[MinValueValidator(1), MaxValueValidator(5)],
            ),
        ),
        migrations.RunPython(
            recalculate_checklist_reviews,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
