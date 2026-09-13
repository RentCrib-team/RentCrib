import pytest

from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from propertylist_app.api.views.messaging import (
    MessageStatsView,
    MessageThreadListCreateView,
)
from propertylist_app.models import (
    Message,
    MessageThread,
    MessageThreadState,
    UserProfile,
)
from propertylist_app.services.message_unread import system_message_unread_payload


@pytest.mark.django_db
def test_message_thread_list_does_not_query_each_deleted_thread_state(
    django_user_model,
    django_assert_num_queries,
):
    user = django_user_model.objects.create_user(
        username="message_thread_perf_user",
        email="message_thread_perf_user@example.com",
        password="testpass123",
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = "seeker"
    profile.save(update_fields=["role"])

    deleted_at = timezone.now()

    for _ in range(4):
        thread = MessageThread.objects.create()
        thread.participants.add(user)
        MessageThreadState.objects.create(
            user=user,
            thread=thread,
            deleted_at=deleted_at,
        )

    factory = APIRequestFactory()
    django_request = factory.get("/api/v1/messages/threads/")
    force_authenticate(django_request, user=user)

    view = MessageThreadListCreateView()
    request = view.initialize_request(django_request)
    view.request = request
    view.args = ()
    view.kwargs = {}

    # Building the queryset should do only the fixed-cost profile lookup and
    # bin-state lookup. The number of deleted thread states must not add one
    # Message EXISTS query per state.
    with django_assert_num_queries(2):
        view.get_queryset()


@pytest.mark.django_db
def test_message_stats_does_not_query_each_deleted_thread_state(
    django_user_model,
    django_assert_num_queries,
):
    user = django_user_model.objects.create_user(
        username="message_stats_perf_user",
        email="message_stats_perf_user@example.com",
        password="testpass123",
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = "seeker"
    profile.save(update_fields=["role"])

    deleted_at = timezone.now()

    for _ in range(4):
        thread = MessageThread.objects.create()
        thread.participants.add(user)
        MessageThreadState.objects.create(
            user=user,
            thread=thread,
            deleted_at=deleted_at,
        )

    factory = APIRequestFactory()
    django_request = factory.get("/api/v1/messages/stats/")
    force_authenticate(django_request, user=user)

    view = MessageStatsView()
    request = view.initialize_request(django_request)
    view.request = request
    view.args = ()
    view.kwargs = {}

    # Fixed work only: profile, bin ids, two thread counts and two unread
    # counts. Deleted history must stay inside correlated SQL subqueries.
    with django_assert_num_queries(6):
        response = view.get(request)

    assert response.status_code == 200
    assert response.data["total_threads"] == 0
    assert response.data["total_unread"] == 0


@pytest.mark.django_db
def test_system_message_unread_payload_does_not_query_each_deleted_thread_state(
    django_user_model,
    django_assert_num_queries,
):
    user = django_user_model.objects.create_user(
        username="system_unread_perf_user",
        email="system_unread_perf_user@example.com",
        password="testpass123",
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = "seeker"
    profile.save(update_fields=["role"])

    active_thread = MessageThread.objects.create()
    active_thread.participants.add(user)
    system_message = Message.objects.create(
        thread=active_thread,
        sender=user,
        body="Workflow update",
        message_type=Message.TYPE_TEXT,
        metadata={"system_event": True},
    )

    deleted_at = timezone.now()
    for _ in range(4):
        thread = MessageThread.objects.create()
        thread.participants.add(user)
        MessageThreadState.objects.create(
            user=user,
            thread=thread,
            deleted_at=deleted_at,
        )

    with django_assert_num_queries(6):
        payload = system_message_unread_payload(
            user.id,
            {
                "message_id": system_message.id,
                "thread_id": active_thread.id,
            },
        )

    assert payload == {
        "thread_id": active_thread.id,
        "thread_unread_count": 1,
        "account_unread_total": 1,
    }
