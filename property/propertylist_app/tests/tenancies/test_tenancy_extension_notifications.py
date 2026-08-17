# propertylist_app/tests/tenancies/test_tenancy_extension_notifications.py

from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone


pytestmark = pytest.mark.django_db


def _get_model(app_label, model_name):
    return apps.get_model(
        app_label,
        model_name,
    )


def _make_tenancy(
    room,
    landlord,
    tenant,
    *,
    status,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    now = timezone.now()

    return Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=(
            date.today() - timedelta(days=90)
        ),
        duration_months=3,
        status=status,
        landlord_confirmed_at=(
            now - timedelta(days=90)
        ),
        tenant_confirmed_at=(
            now - timedelta(days=90)
        ),
    )


def _renewal_start_date():
    return date.today() + timedelta(days=30)


def test_extension_proposal_creates_notification_to_other_party(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )
    Notification = _get_model(
        "propertylist_app",
        "Notification",
    )
    
    Message = _get_model(
        "propertylist_app",
        "Message",
    )
    
    NotificationTemplate = _get_model(
        "notifications",
        "NotificationTemplate",
    )

    OutboundNotification = _get_model(
        "notifications",
        "OutboundNotification",
    )
    

    landlord = user_factory(
        username="extn_landlord1",
    )
    tenant = user_factory(
        username="extn_tenant1",
    )
    room = room_factory(
        property_owner=landlord,
    )

    tenancy = _make_tenancy(
        room,
        landlord,
        tenant,
        status=Tenancy.STATUS_ACTIVE,
    )

    renewal_start_date = _renewal_start_date()
    
    
    NotificationTemplate.objects.update_or_create(
        key="tenancy.extension.proposed",
        channel="email",
        defaults={
            "subject": "Tenancy renewal proposed",
            "body": "{{ room_title }} {{ cta_url }}",
            "is_active": True,
        },
    )

    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=renewal_start_date,
        proposed_duration_months=6,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    notifications = Notification.objects.filter(
        type="tenancy_extension_proposed",
        target_type="tenancy_extension",
        target_id=extension.id,
    )

    # Both parties now receive a proposal notification:
    #
    # - the other party gets the action notification
    # - the proposer gets confirmation that the renewal proposal was sent
    assert notifications.count() == 2

    assert set(
        notifications.values_list(
            "user_id",
            flat=True,
        )
    ) == {
        landlord.id,
        tenant.id,
    }

    tenant_notification = notifications.get(
        user=tenant,
    )

    assert (
        tenant_notification.title
        == "Tenancy renewal proposed"
    )

    assert room.title in tenant_notification.body

    assert (
        renewal_start_date.strftime("%d %B %Y")
        in tenant_notification.body
    )

    assert "6 months" in tenant_notification.body

    landlord_notification = notifications.get(
        user=landlord,
    )

    assert (
        landlord_notification.title
        == "Tenancy renewal proposed"
    )

    assert room.title in landlord_notification.body

    assert "has been sent" in landlord_notification.body
    
    
    
    message = Message.objects.get(
    metadata__extension_id=extension.id,
    metadata__event_type="tenancy_extension_proposed",
    )

    assert message.metadata["system_event"] is True
    assert message.metadata["extension_id"] == extension.id
    assert message.metadata["tenancy_id"] == tenancy.id

    assert message.metadata["available_actions"] == [
        "accept",
        "reject",
    ]

    assert (
        message.metadata["responder_user_id"]
        == tenant.id
    )
    
    
    email = OutboundNotification.objects.get(
        user=tenant,
        template_key="tenancy.extension.proposed",
        context__extension_id=extension.id,
    )

    cta_url = email.context["cta_url"]

    assert f"/tenancies/{tenancy.id}" in cta_url
    assert "/app/tenancies/" not in cta_url




   













def test_extension_accept_creates_notifications_for_both(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )
    Notification = _get_model(
        "propertylist_app",
        "Notification",
    )

    landlord = user_factory(
        username="extn_landlord2",
    )
    tenant = user_factory(
        username="extn_tenant2",
    )
    room = room_factory(
        property_owner=landlord,
    )

    tenancy = _make_tenancy(
        room,
        landlord,
        tenant,
        status=Tenancy.STATUS_ACTIVE,
    )

    renewal_start_date = _renewal_start_date()

    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=renewal_start_date,
        proposed_duration_months=7,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    extension.status = (
        TenancyExtension.STATUS_ACCEPTED
    )
    extension.responded_at = timezone.now()
    extension.save(
        update_fields=[
            "status",
            "responded_at",
        ]
    )

    notifications = Notification.objects.filter(
        type="tenancy_extension_accepted",
        target_type="tenancy_extension",
        target_id=extension.id,
    )

    assert notifications.count() == 2

    assert set(
        notifications.values_list(
            "user_id",
            flat=True,
        )
    ) == {
        landlord.id,
        tenant.id,
    }

    for notification in notifications:
        assert (
            notification.title
            == "Tenancy renewal accepted"
        )
        assert room.title in notification.body
        assert (
            renewal_start_date.strftime(
                "%d %B %Y"
            )
            in notification.body
        )
        assert "7 months" in notification.body


def test_extension_reject_notifies_proposer(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )
    Notification = _get_model(
        "propertylist_app",
        "Notification",
    )

    landlord = user_factory(
        username="extn_landlord3",
    )
    tenant = user_factory(
        username="extn_tenant3",
    )
    room = room_factory(
        property_owner=landlord,
    )

    tenancy = _make_tenancy(
        room,
        landlord,
        tenant,
        status=Tenancy.STATUS_ACTIVE,
    )

    renewal_start_date = _renewal_start_date()

    # The tenant proposes this renewal.
    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=tenant,
        proposed_start_date=renewal_start_date,
        proposed_duration_months=8,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    extension.status = (
        TenancyExtension.STATUS_REJECTED
    )
    extension.responded_at = timezone.now()
    extension.save(
        update_fields=[
            "status",
            "responded_at",
        ]
    )

    notifications = Notification.objects.filter(
        type="tenancy_extension_rejected",
        target_type="tenancy_extension",
        target_id=extension.id,
    )

    assert notifications.count() == 1

    notification = notifications.get()

    assert notification.user_id == tenant.id
    assert (
        notification.title
        == "Tenancy renewal declined"
    )
    assert room.title in notification.body
    assert (
        renewal_start_date.strftime("%d %B %Y")
        in notification.body
    )
    assert "8 months" in notification.body
    assert (
        "existing tenancy information remains unchanged"
        in notification.body.lower()
    )

    # The counterparty does not receive a rejection alert.
    assert not Notification.objects.filter(
        user=landlord,
        type="tenancy_extension_rejected",
        target_type="tenancy_extension",
        target_id=extension.id,
    ).exists()


def test_extension_status_save_without_change_does_not_duplicate_notifications(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )
    Notification = _get_model(
        "propertylist_app",
        "Notification",
    )

    landlord = user_factory(
        username="extn_landlord_dup",
    )
    tenant = user_factory(
        username="extn_tenant_dup",
    )
    room = room_factory(
        property_owner=landlord,
    )

    tenancy = _make_tenancy(
        room,
        landlord,
        tenant,
        status=Tenancy.STATUS_ACTIVE,
    )

    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=_renewal_start_date(),
        proposed_duration_months=6,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    extension.status = (
        TenancyExtension.STATUS_ACCEPTED
    )
    extension.responded_at = timezone.now()
    extension.save(
        update_fields=[
            "status",
            "responded_at",
        ]
    )

    first_count = Notification.objects.filter(
        type="tenancy_extension_accepted",
        target_type="tenancy_extension",
        target_id=extension.id,
    ).count()

    assert first_count == 2

    # Saving the same status again must not create duplicates.
    extension.status = (
        TenancyExtension.STATUS_ACCEPTED
    )
    extension.save(
        update_fields=[
            "status",
        ]
    )

    second_count = Notification.objects.filter(
        type="tenancy_extension_accepted",
        target_type="tenancy_extension",
        target_id=extension.id,
    ).count()

    assert second_count == first_count


def test_extension_notification_target_id_is_extension_id(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )
    Notification = _get_model(
        "propertylist_app",
        "Notification",
    )

    landlord = user_factory(
        username="extn_landlord_target",
    )
    tenant = user_factory(
        username="extn_tenant_target",
    )
    room = room_factory(
        property_owner=landlord,
    )

    tenancy = _make_tenancy(
        room,
        landlord,
        tenant,
        status=Tenancy.STATUS_ACTIVE,
    )

    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=_renewal_start_date(),
        proposed_duration_months=5,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    notification = Notification.objects.get(
        user=tenant,
        type="tenancy_extension_proposed",
    )

    assert (
        notification.target_type
        == "tenancy_extension"
    )
    assert notification.target_id == extension.id