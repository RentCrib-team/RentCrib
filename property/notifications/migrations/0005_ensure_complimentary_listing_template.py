from __future__ import annotations

from django.db import migrations


SUBJECT = "Your RentCrib listing has been renewed free for 30 days"

BODY = """
{% extends "emails/base.html" %}

{% block content %}
<h1>Your listing has been renewed free for 30 days</h1>

<p>Hi {{ user.first_name|default:"there" }},</p>

<p>
Your room <strong>{{ room.title }}</strong> has been automatically renewed
for another 30 days at no charge because it was still available at the end
of your paid listing period.
</p>

{% include "emails/components/button.html" with button_url=cta_url button_text="View active listing" %}

<p>Thank you for using RentCrib.</p>
{% endblock %}
"""


def ensure_template(apps, schema_editor):
    NotificationTemplate = apps.get_model(
        "notifications",
        "NotificationTemplate",
    )

    NotificationTemplate.objects.update_or_create(
        key="listing.complimentary_renewed",
        defaults={
            "channel": "email",
            "subject": SUBJECT,
            "body": BODY,
            "is_active": True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0004_ensure_booking_confirmation_template"),
    ]

    operations = [
        migrations.RunPython(
            ensure_template,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
