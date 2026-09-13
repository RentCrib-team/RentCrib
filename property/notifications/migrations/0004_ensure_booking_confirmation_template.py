from __future__ import annotations

from django.db import migrations


BOOKING_CONFIRMATION_SUBJECT = (
    "Your viewing request has been sent for {{ room.title }}"
)

BOOKING_CONFIRMATION_BODY = """
{% extends "emails/base.html" %}

{% block content %}
<h1>Viewing request sent</h1>

<p>Hi {{ user.first_name|default:"there" }},</p>

<p>
Your viewing request for <strong>{{ room.title }}</strong> has been sent.
</p>

{% if room.owner_name %}
<p>{{ room.owner_name }} has been notified of your request.</p>
{% endif %}

{% include "emails/components/button.html" with button_url=cta_url button_text="View booking" %}

<p>Thank you for using RentCrib.</p>
{% endblock %}
"""


def ensure_booking_confirmation_template(apps, schema_editor):
    NotificationTemplate = apps.get_model(
        "notifications",
        "NotificationTemplate",
    )

    NotificationTemplate.objects.get_or_create(
        key="booking.confirmation",
        defaults={
            "channel": "email",
            "subject": BOOKING_CONFIRMATION_SUBJECT,
            "body": BOOKING_CONFIRMATION_BODY,
            "is_active": True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        (
            "notifications",
            "0003_fix_upcoming_booking_reminder_periodic_task",
        ),
    ]

    operations = [
        migrations.RunPython(
            ensure_booking_confirmation_template,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
