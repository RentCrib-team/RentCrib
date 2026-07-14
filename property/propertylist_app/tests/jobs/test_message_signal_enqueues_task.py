import pytest
from django.contrib.auth import get_user_model
from propertylist_app.models import MessageThread, Message

User = get_user_model()

@pytest.mark.django_db(transaction=True)
def test_message_post_save_signal_enqueues_email_task(monkeypatch, django_capture_on_commit_callbacks):
    # 1) Patch the Celery task's .delay() so no real queue is used.
    calls = {"count": 0, "args": None}

    def fake_delay(message_id):
        calls["count"] += 1
        calls["args"] = (message_id,)

    from propertylist_app import tasks

    monkeypatch.setattr(tasks.task_send_new_message_email, "delay", fake_delay)

    # 2) Create a two-person thread.
    u1 = User.objects.create_user(username="alice", email="a@example.com", password="x")
    u2 = User.objects.create_user(username="bob", email="b@example.com", password="x")
    thread = MessageThread.objects.create()
    thread.participants.set([u1, u2])

    # 3) Create a message -> post_save signal registers an on_commit callback.
    with django_capture_on_commit_callbacks(execute=True):
        msg = Message.objects.create(thread=thread, sender=u1, body="Hi!")

    # 4) Assert that our fake .delay() was called exactly once after commit.
    assert calls["count"] == 1, "Expected Celery task to be enqueued once"
    assert calls["args"] == (msg.id,)
