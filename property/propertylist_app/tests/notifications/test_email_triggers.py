import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings

from propertylist_app.models import MessageThread, Message
from propertylist_app.services.tasks import send_new_message_email

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@rentout.test",
)
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@rentout.test",
)
@pytest.mark.django_db
def test_send_new_message_email_sends_to_other_participant_and_uses_outbox():
    """
    When A messages B in a 2-person thread:
    - An email is sent to B (not A).
    - Subject identifies the sender.
    - Message content is NOT exposed in the email.
    - Recipient is directed back to RentCrib to read the message.
    """
    alice = User.objects.create_user(
        username="alice",
        password="x",
        email="alice@example.com",
    )
    bob = User.objects.create_user(
        username="bob",
        password="x",
        email="bob@example.com",
    )

    thread = MessageThread.objects.create()
    thread.participants.set([alice, bob])

    msg = Message.objects.create(
        thread=thread,
        sender=alice,
        body="Hi Bob!",
    )

    mail.outbox.clear()

    sent = send_new_message_email(msg.id)

    assert sent == 1
    assert len(mail.outbox) == 1

    email = mail.outbox[0]

    assert email.to == ["bob@example.com"]
    assert "alice" in email.subject.lower()

    # Privacy contract: chat content must never be copied into email.
    assert "Hi Bob!" not in email.body

    assert "new message on RentCrib" in email.body
    assert "Open your conversation to read and reply." in email.body
    assert (
        "The message content is only available inside RentCrib."
        in email.body
    )

@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@rentout.test",
)
@pytest.mark.django_db
def test_send_new_message_email_skips_when_recipient_has_no_email():
    """
    If the other participant doesn't have an email address,
    send_new_message_email should return 0 and not send anything.
    """
    # Sender has email, recipient doesn't
    sender = User.objects.create_user(username="sender", password="x", email="sender@example.com")
    no_email_user = User.objects.create_user(username="noemail", password="x", email="")

    thread = MessageThread.objects.create()
    thread.participants.set([sender, no_email_user])

    msg = Message.objects.create(thread=thread, sender=sender, body="Ping")

    mail.outbox.clear()

    sent = send_new_message_email(msg.id)
    assert sent == 0, "Should return 0 when no recipient email is available"
    assert len(mail.outbox) == 0, "No email should be sent when recipient has no email"


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@rentout.test",
)
@pytest.mark.django_db
def test_send_new_message_email_ignores_threads_not_exactly_two_participants():
    """
    If the thread does not have exactly two participants,
    the function should not send anything and return 0.
    """
    u1 = User.objects.create_user(username="u1", password="x", email="u1@example.com")
    u2 = User.objects.create_user(username="u2", password="x", email="u2@example.com")
    u3 = User.objects.create_user(username="u3", password="x", email="u3@example.com")

    thread = MessageThread.objects.create()
    thread.participants.set([u1, u2, u3])  # 3 participants -> should skip

    msg = Message.objects.create(thread=thread, sender=u1, body="Hello all")

    mail.outbox.clear()

    sent = send_new_message_email(msg.id)
    assert sent == 0, "Should return 0 for non 2-person threads"
    assert len(mail.outbox) == 0, "No email should be sent for non 2-person threads"
