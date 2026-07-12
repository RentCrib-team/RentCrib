from django.core.management.base import BaseCommand
from notifications.models import NotificationTemplate

TEMPLATES = [
    {
        "key": "message.new",
        "subject": "New message from {{ sender.name }} on RentCrib",
        "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    You have a new message
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    <strong>{{ sender.name }}</strong> has sent you a new message on RentCrib.
    </p>

    <p style="
    background:#f5f5f5;
    padding:15px;
    border-radius:6px;
    font-family:Arial,sans-serif;
    ">
    {{ snippet }}
    </p>

    <p>
    Reply to continue your conversation and arrange your next steps.
    </p>

    {% include "emails/components/button.html" with button_url=thread_url button_text="Reply to message" %}

    <p>
    Thanks for using RentCrib.
    </p>

    {% endblock %}
    """,
    },
    {
        "key": "booking.new",
        "subject": "New viewing request for {{ room.title }}",
        "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    New viewing request received
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    <strong>{{ booker.name }}</strong> has requested to view your room:
    </p>

    <p>
    <strong>{{ room.title }}</strong>
    </p>

    <p>
    A potential tenant is interested in your listing. You can review the request and continue the conversation through RentCrib.
    </p>

    <p>
    <strong>Booking reference:</strong><br>
    {{ booking_id }}
    </p>

    {% include "emails/components/button.html" with button_url=cta_url button_text="View request" %}

    <p>
    Thanks for using RentCrib.
    </p>

    {% endblock %}
    """,
    },
    {
        "key": "booking.confirmation",
        "subject": "Your viewing request has been sent for {{ room.title }}",
        "body": """
        {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    Your viewing request has been sent
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    Your request to view
    <strong>{{ room.title }}</strong>
    has been successfully sent to
    <strong>{{ room.owner_name }}</strong>.
    </p>

    <p>
    The landlord will review your request and respond through RentCrib.
    </p>

    <p>
    <strong>Booking reference:</strong><br>
    {{ booking_id }}
    </p>

    {% include "emails/components/button.html" with button_url=cta_url button_text="View booking" %}

    <p>
    Thank you for using RentCrib.
    </p>

    {% endblock %}
    """,
    },
    
    {
        "key": "booking.updated",
        "subject": "Your viewing time has been updated for {{ room.title }}",
        "body": """
        {% extends "emails/base.html" %}

        {% block content %}

        <h2 style="
        font-family:Arial,sans-serif;
        color:#333333;
        ">
        Your viewing time has been updated
        </h2>

        <p>
        Hi {{ user.first_name }},
        </p>

        <p>
        The landlord has updated the viewing time for:
        </p>

        <p>
        <strong>{{ room.title }}</strong>
        </p>

        <p>
        Your new viewing time is:
        </p>

        <p>
        <strong>{{ new_start }}</strong>
        <br>
        to
        <br>
        <strong>{{ new_end }}</strong>
        </p>

        <p>
        Please check the updated viewing details through RentCrib.
        </p>

        {% include "emails/components/button.html" with button_url=cta_url button_text="View updated booking" %}

        <p>
        Thanks for using RentCrib.
        </p>

        {% endblock %}
        """,
    },
        
    
    
    {
        "key": "listing.expiring",
        "subject": "Your RentCrib listing is expiring soon",
        "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    Your listing is expiring soon
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    Your listing:
    </p>

    <p>
    <strong>{{ room.title }}</strong>
    </p>

    <p>
    is due to expire on <strong>{{ room.paid_until }}</strong>.
    </p>

    <p>
    Renew your listing to keep it visible to room seekers on RentCrib.
    </p>

    {% include "emails/components/button.html" with button_url=renew_url button_text="Renew listing" %}

    <p>
    Thank you for using RentCrib.
    </p>

    {% endblock %}
    """,
    },
    
    
        # -------------------------
    # Tenancy lifecycle
    # -------------------------
    {
        "key": "tenancy.proposed",
        "subject": "Tenancy information received for {{ room_title }}",
        "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    Tenancy information received
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    Tenancy information has been submitted for:
    </p>

    <p>
    <strong>{{ room_title }}</strong>
    </p>

    <p>
    Please review the information recorded and confirm that it matches the tenancy agreement you agreed with the other party outside RentCrib.
    </p>

    <p>
    RentCrib does not create tenancy agreements. We help both parties keep track of the tenancy information they have agreed.
    </p>

    {% include "emails/components/button.html" with button_url=cta_url button_text="Review tenancy information" %}

    <p>
    Thank you for using RentCrib.
    </p>

    {% endblock %}
    """,
    },
    {
        "key": "tenancy.updated",
        "subject": "Tenancy information updated for {{ room_title }}",
        "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    Your tenancy information has been updated
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    The tenancy information recorded for:
    </p>

    <p>
    <strong>{{ room_title }}</strong>
    </p>

    <p>
    has been updated.
    </p>

    <p>
    Please review the latest details and ensure they match the tenancy agreement you agreed with the other party outside RentCrib.
    </p>

    <p>
    RentCrib stores this information to help both parties keep track of their tenancy journey.
    </p>

    {% include "emails/components/button.html" with button_url=cta_url button_text="Review tenancy information" %}

    <p>
    Thank you for using RentCrib.
    </p>

    {% endblock %}
    """,
    },
    {
        "key": "tenancy.confirmed",
        "subject": "Tenancy information confirmed for {{ room_title }}",
        "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    Your tenancy information has been confirmed
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    The tenancy information recorded for:
    </p>

    <p>
    <strong>{{ room_title }}</strong>
    </p>

    <p>
    has been confirmed.
    </p>

    <p>
    Please ensure the details match the tenancy agreement you agreed with the other party outside RentCrib.
    </p>

    <p>
    RentCrib stores this information to help both parties keep track of their tenancy journey.
    </p>

    {% include "emails/components/button.html" with button_url=cta_url button_text="View tenancy information" %}

    <p>
    Thank you for using RentCrib.
    </p>

    {% endblock %}
    """,
    },
    {
        "key": "tenancy.cancelled",
        "subject": "Tenancy information cancelled for {{ room_title }}",
        "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    Tenancy information cancelled
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    The tenancy information recorded for:
    </p>

    <p>
    <strong>{{ room_title }}</strong>
    </p>

    <p>
    has been cancelled.
    </p>

    <p>
    RentCrib stores tenancy information to help both parties keep track of the details they agreed outside RentCrib.
    </p>

    {% include "emails/components/button.html" with button_url=cta_url button_text="View tenancy information" %}

    <p>
    Thank you for using RentCrib.
    </p>

    {% endblock %}
    """,
    },
    # -------------------------
    # Tenancy prompts
    # -------------------------
    {
        "key": "tenancy.still_living_check",
        "subject": "Tenancy information check for {{ room_title }}",
        "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    Tenancy information check
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    Tenancy information check
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    Please confirm whether this tenancy is still active.
    </p>

    <p>
    <strong>{{ room_title }}</strong>
    </p>

    <p>
    We periodically ask both landlords and tenants to confirm active tenancy information so RentCrib records remain accurate and reviews become available at the right time.
    </p>

    {% include "emails/components/button.html" with button_url=cta_url button_text="Confirm tenancy status" %}

    <p>
    Thank you for using RentCrib.
    </p>

    {% endblock %}
    """,
    },
    {
        "key": "tenancy.review_available",
        "subject": "You can now leave a review for {{ room_title }}",
        "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    Your review is now available
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    You can now leave a review linked to:
    </p>

    <p>
    <strong>{{ room_title }}</strong>
    </p>

    <p>
    Reviews help keep RentCrib fair and useful for both tenants and landlords.
    </p>

    {% include "emails/components/button.html" with button_url=cta_url button_text="Leave a review" %}

    <p>
    Thank you for being part of the RentCrib community.
    </p>

    {% endblock %}
    """,
    },

    # -------------------------
    # Tenancy extension
    # -------------------------
   {
        "key": "tenancy.extension.proposed",
        "subject": "Tenancy extension request received for {{ room_title }}",
        "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    Tenancy extension request received
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    A tenancy extension request has been submitted for:
    </p>

    <p>
    <strong>{{ room_title }}</strong>
    </p>

    <p>
    Please review the updated tenancy information and respond when ready.
    </p>

    {% include "emails/components/button.html" with button_url=cta_url button_text="Review extension request" %}

    <p>
    Thank you for using RentCrib.
    </p>

    {% endblock %}
    """,
    },
    {
        "key": "tenancy.extension.accepted",
        "subject": "Tenancy extension information confirmed for {{ room_title }}",
        "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    Tenancy extension information confirmed
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    The tenancy extension information for:
    </p>

    <p>
    <strong>{{ room_title }}</strong>
    </p>

    <p>
    has been confirmed.
    </p>

    <p>
    Please ensure the updated details match the agreement made between both parties outside RentCrib.
    </p>

    {% include "emails/components/button.html" with button_url=cta_url button_text="View tenancy information" %}

    <p>
    Thank you for using RentCrib.
    </p>

    {% endblock %}
    """,
    },
    {
        "key": "tenancy.extension.rejected",
        "subject": "Tenancy extension request declined for {{ room_title }}",
        "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
    font-family:Arial,sans-serif;
    color:#333333;
    ">
    Tenancy extension request declined
    </h2>

    <p>
    Hi {{ user.first_name }},
    </p>

    <p>
    The tenancy extension request for:
    </p>

    <p>
    <strong>{{ room_title }}</strong>
    </p>

    <p>
    has been declined.
    </p>

    {% include "emails/components/button.html" with button_url=cta_url button_text="View tenancy information" %}

    <p>
    Thank you for using RentCrib.
    </p>

    {% endblock %}
    """,
    },
]

class Command(BaseCommand):
    help = "Seed default notification templates"

    def handle(self, *args, **options):
        created = 0
        for t in TEMPLATES:
            obj, was_created = NotificationTemplate.objects.update_or_create(
                key=t["key"],
                defaults={
                    "subject": t["subject"],
                    "body": t["body"],
                    "channel": "email",
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Seeded templates. New created: {created}"))
