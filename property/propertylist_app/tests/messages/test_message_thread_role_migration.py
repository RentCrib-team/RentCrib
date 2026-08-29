import pytest

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


pytestmark = pytest.mark.django_db(transaction=True)


MIGRATE_FROM = [
    (
        "propertylist_app",
        "0093_messagethread_landlord_messagethread_seeker_and_more",
    ),
]

MIGRATE_TO = [
    (
        "propertylist_app",
        "0094_backfill_message_thread_roles",
    ),
]


def test_backfill_only_classifies_deterministic_room_threads():
    executor = MigrationExecutor(connection)
    executor.migrate(MIGRATE_FROM)

    old_apps = executor.loader.project_state(MIGRATE_FROM).apps

    user_app, user_model = settings.AUTH_USER_MODEL.split(".")

    User = old_apps.get_model(user_app, user_model)
    RoomCategorie = old_apps.get_model(
        "propertylist_app",
        "RoomCategorie",
    )
    Room = old_apps.get_model(
        "propertylist_app",
        "Room",
    )
    MessageThread = old_apps.get_model(
        "propertylist_app",
        "MessageThread",
    )

    landlord = User.objects.create(username="migration-landlord")
    seeker = User.objects.create(username="migration-seeker")

    category = RoomCategorie.objects.create(
        key="migration-general",
        name="Migration General",
    )

    room = Room.objects.create(
        title="Migration test room",
        description="Migration test",
        price_per_month="500.00",
        location="London",
        category=category,
        property_owner=landlord,
        property_type="flat",
        status="active",
    )

    safe_thread = MessageThread.objects.create(room=room)
    safe_thread.participants.set([landlord, seeker])

    malformed_thread = MessageThread.objects.create(room=room)
    malformed_thread.participants.set([landlord])

    roomless_thread = MessageThread.objects.create()
    roomless_thread.participants.set([landlord, seeker])

    executor = MigrationExecutor(connection)
    executor.migrate(MIGRATE_TO)

    new_apps = executor.loader.project_state(MIGRATE_TO).apps
    MigratedThread = new_apps.get_model(
        "propertylist_app",
        "MessageThread",
    )

    safe_thread = MigratedThread.objects.get(pk=safe_thread.pk)
    malformed_thread = MigratedThread.objects.get(
        pk=malformed_thread.pk
    )
    roomless_thread = MigratedThread.objects.get(
        pk=roomless_thread.pk
    )

    assert safe_thread.landlord_id == landlord.id
    assert safe_thread.seeker_id == seeker.id

    assert malformed_thread.landlord_id is None
    assert malformed_thread.seeker_id is None

    assert roomless_thread.landlord_id is None
    assert roomless_thread.seeker_id is None