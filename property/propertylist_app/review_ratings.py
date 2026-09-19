from decimal import Decimal, ROUND_HALF_UP


TENANT_TO_LANDLORD_FLAGS = {
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

LANDLORD_TO_TENANT_FLAGS = {
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

CONTRADICTORY_PAIRS = (
    ("responsive", "unresponsive"),
    ("maintenance_good", "maintenance_poor"),
    ("accurate_listing", "misleading_listing"),
    ("respectful_fair", "unfair_treatment"),
    ("clean_and_tidy", "messy"),
    ("followed_rules", "broke_rules"),
    ("paid_on_time", "late_payment"),
    ("good_communication", "poor_communication"),
    ("property_care_good", "property_care_poor"),
    ("friendly", "rude"),
)

_CONFIG_BY_ROLE = {
    "tenant_to_landlord": TENANT_TO_LANDLORD_FLAGS,
    "landlord_to_tenant": LANDLORD_TO_TENANT_FLAGS,
}


def calculate_review_rating(*, role: str, flags) -> Decimal:
    """
    Convert a role-specific checklist into a fair 1.0-5.0 score.

    Each selected positive contributes its share of the maximum possible
    positive experience. Each selected negative subtracts its share of the
    maximum possible negative experience. A balanced result is 3.0.

        score = 3 + 2 * (
            selected_positive_weight / maximum_positive_weight
            - selected_negative_weight / maximum_negative_weight
        )

    Duplicate flags are intentionally ignored here so they cannot alter a
    score. API validation rejects duplicates and contradictory selections.
    """
    try:
        config = _CONFIG_BY_ROLE[role]
    except KeyError as exc:
        raise ValueError(f"Unsupported review role: {role!r}") from exc

    selected = set(flags or ())
    positive_weights = config["positives"]
    negative_weights = config["negatives"]

    selected_positive = sum(
        (weight for flag, weight in positive_weights.items() if flag in selected),
        Decimal("0"),
    )
    selected_negative = sum(
        (weight for flag, weight in negative_weights.items() if flag in selected),
        Decimal("0"),
    )

    maximum_positive = sum(positive_weights.values(), Decimal("0"))
    maximum_negative = sum(negative_weights.values(), Decimal("0"))

    net = (
        selected_positive / maximum_positive
        - selected_negative / maximum_negative
    )
    score = Decimal("3") + Decimal("2") * net
    score = min(Decimal("5"), max(Decimal("1"), score))
    return score.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
