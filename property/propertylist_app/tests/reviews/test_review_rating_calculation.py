from decimal import Decimal

import pytest

from propertylist_app.review_ratings import calculate_review_rating


@pytest.mark.parametrize(
    ("role", "flags", "expected"),
    [
        (
            "tenant_to_landlord",
            [
                "responsive",
                "maintenance_good",
                "accurate_listing",
                "respectful_fair",
            ],
            Decimal("5.0"),
        ),
        (
            "tenant_to_landlord",
            [
                "unresponsive",
                "maintenance_poor",
                "misleading_listing",
                "unfair_treatment",
            ],
            Decimal("1.0"),
        ),
        (
            "tenant_to_landlord",
            ["responsive", "maintenance_good"],
            Decimal("4.1"),
        ),
        (
            "landlord_to_tenant",
            [
                "clean_and_tidy",
                "followed_rules",
                "property_care_good",
                "friendly",
                "poor_communication",
                "rude",
            ],
            Decimal("3.7"),
        ),
    ],
)
def test_calculate_review_rating(role, flags, expected):
    assert calculate_review_rating(role=role, flags=flags) == expected


def test_duplicate_flags_cannot_inflate_rating():
    once = calculate_review_rating(
        role="tenant_to_landlord",
        flags=["responsive"],
    )
    repeated = calculate_review_rating(
        role="tenant_to_landlord",
        flags=["responsive", "responsive", "responsive"],
    )
    assert repeated == once
