import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from propertylist_app.models import RoomCategorie, Room, Tenancy, Notification
from propertylist_app.tasks import task_send_tenancy_notification


User = get_user_model()


@pytest.mark.django_db
def test_task_send_tenancy_notification_sets_target_fields():
    landlord = User.objects.create_user(username="landlord", password="pass")
    tenant = User.objects.create_user(username="tenant", password="pass")

    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="R1",
        description="x",
        price_per_month=500,
        location="SW1A 1AA",
        category=cat,
        property_owner=landlord,
    )

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=tenant,
        move_in_date=timezone.localdate(),
        duration_months=6,
        status=Tenancy.STATUS_CONFIRMED,
    )

    task_send_tenancy_notification(tenancy.id, "proposed")

    notif = Notification.objects.filter(type="tenancy_proposed").first()

    assert notif is not None

    assert notif.target_type == "tenancy"
    assert notif.target_id == tenancy.id

    assert notif.thread_id is not None
    assert notif.message_id is not None
    
    
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("event", "notification_type", "expected_count"),
    [
        ("rejected_unverified", "tenancy_rejected_unverified", 2),
        ("expired_unverified", "tenancy_expired_unverified", 2),
        ("cancelled", "tenancy_cancelled", 2),
        ("updated", "tenancy_updated", 2),
    ],
)
def test_tenancy_lifecycle_notifications_target_tenancy(
    event,
    notification_type,
    expected_count,
):
    landlord = User.objects.create_user(
        username=f"landlord_{event}",
        password="pass",
    )
    tenant = User.objects.create_user(
        username=f"tenant_{event}",
        password="pass",
    )

    cat = RoomCategorie.objects.create(
        name=f"Any {event}",
        active=True,
    )

    room = Room.objects.create(
        title=f"R1 {event}",
        description="x",
        price_per_month=500,
        location="SW1A 1AA",
        category=cat,
        property_owner=landlord,
    )

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=tenant,
        move_in_date=timezone.localdate(),
        duration_months=6,
        status=Tenancy.STATUS_CONFIRMED,
    )

    task_send_tenancy_notification(
        tenancy.id,
        event,
    )

    notifications = Notification.objects.filter(
        type=notification_type,
    ).order_by("id")

    assert notifications.count() == expected_count

    for notification in notifications:
        assert notification.target_type == "tenancy"
        assert notification.target_id == tenancy.id
        assert notification.thread_id is not None
        assert notification.message_id is not None    