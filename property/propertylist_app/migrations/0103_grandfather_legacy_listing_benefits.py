from django.db import migrations


def grandfather_successful_listing_payments(apps, schema_editor):
    Payment = apps.get_model("propertylist_app", "Payment")
    RoomListingBenefit = apps.get_model(
        "propertylist_app",
        "RoomListingBenefit",
    )

    rooms_with_benefit = set(
        RoomListingBenefit.objects.values_list(
            "room_id",
            flat=True,
        )
    )

    successful_payments = (
        Payment.objects.filter(
            status="succeeded",
            room_id__isnull=False,
        )
        .order_by(
            "room_id",
            "created_at",
            "id",
        )
    )

    for payment in successful_payments.iterator():
        if payment.room_id in rooms_with_benefit:
            continue

        RoomListingBenefit.objects.create(
            room_id=payment.room_id,
            granted_from_payment_id=payment.id,
            granted_at=payment.updated_at or payment.created_at,
        )
        rooms_with_benefit.add(payment.room_id)


def noop_reverse(apps, schema_editor):
    # Grandfathered benefits are a business entitlement, not disposable
    # migration scaffolding. Reversing the migration must not revoke them.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0102_roomlistingbenefit"),
    ]

    operations = [
        migrations.RunPython(
            grandfather_successful_listing_payments,
            noop_reverse,
        ),
    ]
