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

<table
    role="presentation"
    width="100%"
    cellpadding="0"
    cellspacing="0"
    border="0"
    style="
        width:100%;
        border-collapse:collapse;
    "
>
<tr>
<td align="center">

<table
    role="presentation"
    width="100%"
    cellpadding="0"
    cellspacing="0"
    border="0"
    style="
        max-width:620px;
        background:#ffffff;
        border:1px solid #e1e7ef;
        border-radius:5px;
    "
>

<tr>
<td style="padding:34px 34px 32px;">


<p style="
margin:0 0 16px;
font-family:Arial, Helvetica, sans-serif;
font-size:12px;
font-weight:700;
letter-spacing:1.4px;
text-transform:uppercase;
text-align:center;
color:#357af0;
">
VIEWING REQUEST
</p>


<h1 style="
margin:0;
font-family:Arial, Helvetica, sans-serif;
font-size:28px;
line-height:1.3;
font-weight:700;
text-align:center;
color:#172033;
">
New viewing request received
</h1>


<p style="
margin:10px 0 30px;
font-family:Arial, Helvetica, sans-serif;
font-size:15px;
line-height:1.6;
text-align:center;
color:#6b7689;
">
Someone is interested in viewing your room.
</p>


<p style="
margin:0 0 16px;
font-family:Arial, Helvetica, sans-serif;
font-size:16px;
line-height:1.7;
color:#4f5b70;
">
Hi {{ user.first_name|default:"there" }},
</p>


<p style="
margin:0;
font-family:Arial, Helvetica, sans-serif;
font-size:16px;
line-height:1.7;
color:#4f5b70;
">
<strong style="color:#172033;">
{{ booker.name }}
</strong>
has requested to view your room.
</p>


<table
role="presentation"
width="100%"
cellpadding="0"
cellspacing="0"
border="0"
style="
margin-top:26px;
background:#f7f9fc;
border:1px solid #dfe6ef;
border-radius:4px;
"
>

<tr>
<td style="padding:20px 22px;">


<p style="
margin:0 0 6px;
font-family:Arial, Helvetica, sans-serif;
font-size:11px;
font-weight:700;
letter-spacing:.8px;
text-transform:uppercase;
color:#7a8497;
">
VIEWING DETAILS
</p>


<p style="
margin:0;
font-family:Arial, Helvetica, sans-serif;
font-size:17px;
font-weight:700;
color:#172033;
">
{{ room.title }}
</p>


<p style="
margin:16px 0 0;
padding-top:14px;
border-top:1px solid #e4e9f0;
font-family:Arial, Helvetica, sans-serif;
font-size:13px;
color:#566176;
">
Viewing reference:
<strong>
{{ booking_id }}
</strong>
</p>


</td>
</tr>

</table>


<table
role="presentation"
width="100%"
cellpadding="0"
cellspacing="0"
border="0"
style="
margin-top:20px;
background:#f4f8ff;
border:1px solid #dce8fb;
border-left:4px solid #357af0;
border-radius:4px;
"
>

<tr>
<td style="padding:16px 18px;">


<p style="
margin:0 0 5px;
font-family:Arial, Helvetica, sans-serif;
font-size:14px;
font-weight:700;
color:#172033;
">
What happens next?
</p>


<p style="
margin:0;
font-family:Arial, Helvetica, sans-serif;
font-size:14px;
line-height:1.65;
color:#566176;
">
Review the request and continue the conversation with the prospective tenant through RentCrib.
</p>


</td>
</tr>

</table>


<table
role="presentation"
align="center"
cellpadding="0"
cellspacing="0"
border="0"
style="margin-top:28px;"
>

<tr>

<td
bgcolor="#357af0"
style="
background:#357af0;
border-radius:4px;
"
>

<a
href="{{ cta_url }}"
style="
display:inline-block;
padding:15px 30px;
font-family:Arial, Helvetica, sans-serif;
font-size:15px;
font-weight:700;
color:#ffffff;
text-decoration:none;
border-radius:4px;
"
>
View request
</a>

</td>

</tr>

</table>


<p style="
margin:22px 0 0;
font-family:Arial, Helvetica, sans-serif;
font-size:13px;
text-align:center;
color:#8892a3;
">
You can respond to this viewing request from your RentCrib account.
</p>


</td>
</tr>

</table>

</td>
</tr>

</table>

{% endblock %}
""",
},

        {
    "key": "booking.confirmation",
    "subject": "Your viewing request has been sent for {{ room.title }}",
    "body": """
{% extends "emails/base.html" %}

{% block content %}

<table
    role="presentation"
    width="100%"
    cellpadding="0"
    cellspacing="0"
    border="0"
    style="
        width:100%;
        border-collapse:collapse;
    "
>
    <tr>
        <td align="center" style="padding:0;">

            <table
                role="presentation"
                width="100%"
                cellpadding="0"
                cellspacing="0"
                border="0"
                style="
                    width:100%;
                    max-width:620px;
                    border-collapse:separate;
                    background-color:#ffffff;
                    border:1px solid #dfe5ee;
                    border-radius:5px;
                "
            >
                <tr>
                    <td style="padding:34px 34px 32px;">

                        <table
                            role="presentation"
                            width="100%"
                            cellpadding="0"
                            cellspacing="0"
                            border="0"
                            style="
                                width:100%;
                                border-collapse:collapse;
                            "
                        >
                            <tr>
                                <td align="center" style="padding:0 0 16px;">

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:12px;
                                        line-height:1.4;
                                        font-weight:700;
                                        letter-spacing:1.4px;
                                        text-transform:uppercase;
                                        color:#357af0;
                                    ">
                                        Viewing request
                                    </p>

                                </td>
                            </tr>

                            <tr>
                                <td align="center" style="padding:0 0 10px;">

                                    <h1 style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:28px;
                                        line-height:1.3;
                                        font-weight:700;
                                        letter-spacing:-0.4px;
                                        color:#172033;
                                    ">
                                        Your viewing request has been sent
                                    </h1>

                                </td>
                            </tr>

                            <tr>
                                <td align="center" style="padding:0 0 30px;">

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:15px;
                                        line-height:1.65;
                                        color:#6b7689;
                                    ">
                                        The landlord has received your request and can now review it.
                                    </p>

                                </td>
                            </tr>

                            <tr>
                                <td style="padding:0 0 16px;">

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:16px;
                                        line-height:1.7;
                                        color:#4f5b70;
                                    ">
                                        Hi {{ user.first_name|default:"there" }},
                                    </p>

                                </td>
                            </tr>

                            <tr>
                                <td style="padding:0 0 26px;">

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:16px;
                                        line-height:1.75;
                                        color:#4f5b70;
                                    ">
                                        Your request to view
                                        <strong style="color:#172033;">
                                            {{ room.title }}
                                        </strong>
                                        has been successfully sent to
                                        <strong style="color:#172033;">
                                            {{ room.owner_name }}
                                        </strong>.
                                    </p>

                                </td>
                            </tr>

                            <tr>
                                <td style="padding:0;">

                                    <table
                                        role="presentation"
                                        width="100%"
                                        cellpadding="0"
                                        cellspacing="0"
                                        border="0"
                                        style="
                                            width:100%;
                                            border-collapse:separate;
                                            background-color:#f7f9fc;
                                            border:1px solid #dfe6ef;
                                            border-radius:4px;
                                        "
                                    >
                                        <tr>
                                            <td style="padding:20px 22px;">

                                                <p style="
                                                    margin:0 0 6px;
                                                    font-family:Arial, Helvetica, sans-serif;
                                                    font-size:11px;
                                                    line-height:1.4;
                                                    font-weight:700;
                                                    letter-spacing:0.8px;
                                                    text-transform:uppercase;
                                                    color:#7a8497;
                                                ">
                                                    Viewing details
                                                </p>

                                                <p style="
                                                    margin:0;
                                                    font-family:Arial, Helvetica, sans-serif;
                                                    font-size:17px;
                                                    line-height:1.5;
                                                    font-weight:700;
                                                    color:#172033;
                                                ">
                                                    {{ room.title }}
                                                </p>

                                                <table
                                                    role="presentation"
                                                    width="100%"
                                                    cellpadding="0"
                                                    cellspacing="0"
                                                    border="0"
                                                    style="
                                                        width:100%;
                                                        margin-top:16px;
                                                        border-collapse:collapse;
                                                    "
                                                >
                                                    <tr>
                                                        <td
                                                            valign="top"
                                                            style="
                                                                width:50%;
                                                                padding:14px 12px 0 0;
                                                                border-top:1px solid #e4e9f0;
                                                            "
                                                        >

                                                            <p style="
                                                                margin:0 0 4px;
                                                                font-family:Arial, Helvetica, sans-serif;
                                                                font-size:11px;
                                                                line-height:1.4;
                                                                font-weight:700;
                                                                letter-spacing:0.7px;
                                                                text-transform:uppercase;
                                                                color:#7a8497;
                                                            ">
                                                                Sent to
                                                            </p>

                                                            <p style="
                                                                margin:0;
                                                                font-family:Arial, Helvetica, sans-serif;
                                                                font-size:14px;
                                                                line-height:1.5;
                                                                font-weight:600;
                                                                color:#3f4b5f;
                                                            ">
                                                                {{ room.owner_name }}
                                                            </p>

                                                        </td>

                                                        <td
                                                            valign="top"
                                                            style="
                                                                width:50%;
                                                                padding:14px 0 0 12px;
                                                                border-top:1px solid #e4e9f0;
                                                                border-left:1px solid #e4e9f0;
                                                            "
                                                        >

                                                            <p style="
                                                                margin:0 0 4px;
                                                                font-family:Arial, Helvetica, sans-serif;
                                                                font-size:11px;
                                                                line-height:1.4;
                                                                font-weight:700;
                                                                letter-spacing:0.7px;
                                                                text-transform:uppercase;
                                                                color:#7a8497;
                                                            ">
                                                                Reference
                                                            </p>

                                                            <p style="
                                                                margin:0;
                                                                font-family:Arial, Helvetica, sans-serif;
                                                                font-size:14px;
                                                                line-height:1.5;
                                                                font-weight:600;
                                                                word-break:break-word;
                                                                color:#3f4b5f;
                                                            ">
                                                                {{ booking_id }}
                                                            </p>

                                                        </td>
                                                    </tr>
                                                </table>

                                            </td>
                                        </tr>
                                    </table>

                                </td>
                            </tr>

                            <tr>
                                <td style="padding:20px 0 0;">

                                    <table
                                        role="presentation"
                                        width="100%"
                                        cellpadding="0"
                                        cellspacing="0"
                                        border="0"
                                        style="
                                            width:100%;
                                            border-collapse:separate;
                                            background-color:#f4f8ff;
                                            border:1px solid #dce8fb;
                                            border-left:4px solid #357af0;
                                            border-radius:4px;
                                        "
                                    >
                                        <tr>
                                            <td style="padding:16px 18px;">

                                                <p style="
                                                    margin:0 0 5px;
                                                    font-family:Arial, Helvetica, sans-serif;
                                                    font-size:14px;
                                                    line-height:1.5;
                                                    font-weight:700;
                                                    color:#172033;
                                                ">
                                                    What happens next?
                                                </p>

                                                <p style="
                                                    margin:0;
                                                    font-family:Arial, Helvetica, sans-serif;
                                                    font-size:14px;
                                                    line-height:1.65;
                                                    color:#566176;
                                                ">
                                                    The landlord will review your request and respond through RentCrib. Your viewing is not confirmed until the landlord accepts it.
                                                </p>

                                            </td>
                                        </tr>
                                    </table>

                                </td>
                            </tr>

                            <tr>
                                <td align="center" style="padding:26px 0 0;">

                                    <table
                                        role="presentation"
                                        cellpadding="0"
                                        cellspacing="0"
                                        border="0"
                                    >
                                        <tr>
                                            <td
                                                align="center"
                                                bgcolor="#357af0"
                                                style="
                                                    background-color:#357af0;
                                                    border-radius:4px;
                                                "
                                            >
                                                <a
                                                    href="{{ cta_url }}"
                                                    style="
                                                        display:inline-block;
                                                        min-width:190px;
                                                        padding:15px 28px;
                                                        font-family:Arial, Helvetica, sans-serif;
                                                        font-size:15px;
                                                        line-height:1.2;
                                                        font-weight:700;
                                                        color:#ffffff;
                                                        text-decoration:none;
                                                        text-align:center;
                                                        border-radius:4px;
                                                    "
                                                >
                                                    View request
                                                </a>
                                            </td>
                                        </tr>
                                    </table>

                                </td>
                            </tr>

                            <tr>
                                <td align="center" style="padding:20px 0 0;">

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:13px;
                                        line-height:1.65;
                                        color:#8892a3;
                                    ">
                                        This confirms your request was sent. It does not mean the viewing has been accepted yet.
                                    </p>

                                </td>
                            </tr>

                            <tr>
                                <td align="center" style="padding:22px 0 0;">

                                    <p style="
                                        margin:0 0 6px;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:12px;
                                        line-height:1.6;
                                        color:#98a1af;
                                    ">
                                        If the button does not work, copy and paste this link into your browser:
                                    </p>

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:12px;
                                        line-height:1.6;
                                        word-break:break-all;
                                    ">
                                        <a
                                            href="{{ cta_url }}"
                                            style="
                                                color:#357af0;
                                                text-decoration:underline;
                                            "
                                        >
                                            {{ cta_url }}
                                        </a>
                                    </p>

                                </td>
                            </tr>
                        </table>

                    </td>
                </tr>
            </table>

        </td>
    </tr>
</table>

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
    "key": "booking.completed",
    "subject": "Your viewing has been completed for {{ room_title }}",
    "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <table
        role="presentation"
        width="100%"
        cellpadding="0"
        cellspacing="0"
        border="0"
        style="
            width:100%;
            border-collapse:collapse;
        "
    >
    <tr>
    <td align="center">

    <table
        role="presentation"
        width="100%"
        cellpadding="0"
        cellspacing="0"
        border="0"
        style="
            width:100%;
            max-width:620px;
            background:#ffffff;
            border:1px solid #e1e7ef;
            border-radius:5px;
        "
    >

    <tr>
    <td style="padding:34px 34px 32px;">

    <p style="
        margin:0 0 16px;
        font-family:Arial, Helvetica, sans-serif;
        font-size:12px;
        font-weight:700;
        letter-spacing:1.4px;
        text-transform:uppercase;
        text-align:center;
        color:#357af0;
    ">
    VIEWING UPDATE
    </p>

    <h1 style="
        margin:0;
        font-family:Arial, Helvetica, sans-serif;
        font-size:28px;
        line-height:1.3;
        font-weight:700;
        text-align:center;
        color:#172033;
    ">
    Your viewing has been completed
    </h1>

    <p style="
        margin:10px 0 30px;
        font-family:Arial, Helvetica, sans-serif;
        font-size:15px;
        line-height:1.6;
        text-align:center;
        color:#6b7689;
    ">
    The scheduled viewing time has now passed.
    </p>

    <p style="
        margin:0 0 16px;
        font-family:Arial, Helvetica, sans-serif;
        font-size:16px;
        line-height:1.7;
        color:#4f5b70;
    ">
    Hi {{ user.first_name|default:"there" }},
    </p>

    <p style="
        margin:0;
        font-family:Arial, Helvetica, sans-serif;
        font-size:16px;
        line-height:1.7;
        color:#4f5b70;
    ">
    Your viewing for
    <strong style="color:#172033;">
    {{ room_title }}
    </strong>
    has now been marked as completed.
    </p>

    <table
        role="presentation"
        width="100%"
        cellpadding="0"
        cellspacing="0"
        border="0"
        style="
            margin-top:26px;
            background:#f7f9fc;
            border:1px solid #dfe6ef;
            border-radius:4px;
        "
    >
    <tr>
    <td style="padding:20px 22px;">

    <p style="
        margin:0 0 6px;
        font-family:Arial, Helvetica, sans-serif;
        font-size:11px;
        font-weight:700;
        letter-spacing:.8px;
        text-transform:uppercase;
        color:#7a8497;
    ">
    VIEWING DETAILS
    </p>

    <p style="
        margin:0;
        font-family:Arial, Helvetica, sans-serif;
        font-size:17px;
        font-weight:700;
        color:#172033;
    ">
    {{ room_title }}
    </p>

    <table
        role="presentation"
        width="100%"
        cellpadding="0"
        cellspacing="0"
        border="0"
        style="
            width:100%;
            margin-top:16px;
            border-collapse:collapse;
        "
    >
    <tr>

    <td
        valign="top"
        style="
            width:50%;
            padding:14px 12px 0 0;
            border-top:1px solid #e4e9f0;
        "
    >
    <p style="
        margin:0 0 4px;
        font-family:Arial, Helvetica, sans-serif;
        font-size:11px;
        font-weight:700;
        letter-spacing:.7px;
        text-transform:uppercase;
        color:#7a8497;
    ">
    Completed
    </p>

    <p style="
        margin:0;
        font-family:Arial, Helvetica, sans-serif;
        font-size:14px;
        line-height:1.5;
        font-weight:600;
        color:#3f4b5f;
    ">
    {{ ended_at }}
    </p>
    </td>

    <td
        valign="top"
        style="
            width:50%;
            padding:14px 0 0 12px;
            border-top:1px solid #e4e9f0;
            border-left:1px solid #e4e9f0;
        "
    >
    <p style="
        margin:0 0 4px;
        font-family:Arial, Helvetica, sans-serif;
        font-size:11px;
        font-weight:700;
        letter-spacing:.7px;
        text-transform:uppercase;
        color:#7a8497;
    ">
    Reference
    </p>

    <p style="
        margin:0;
        font-family:Arial, Helvetica, sans-serif;
        font-size:14px;
        line-height:1.5;
        font-weight:600;
        color:#3f4b5f;
    ">
    {{ booking_id }}
    </p>
    </td>

    </tr>
    </table>

    </td>
    </tr>
    </table>

    <table
        role="presentation"
        width="100%"
        cellpadding="0"
        cellspacing="0"
        border="0"
        style="
            margin-top:20px;
            background:#f4f8ff;
            border:1px solid #dce8fb;
            border-left:4px solid #357af0;
            border-radius:4px;
        "
    >
    <tr>
    <td style="padding:16px 18px;">

    <p style="
        margin:0 0 5px;
        font-family:Arial, Helvetica, sans-serif;
        font-size:14px;
        font-weight:700;
        color:#172033;
    ">
    What happens next?
    </p>

    <p style="
        margin:0;
        font-family:Arial, Helvetica, sans-serif;
        font-size:14px;
        line-height:1.65;
        color:#566176;
    ">
    You can continue the conversation with the landlord through your RentCrib inbox.
    </p>

    </td>
    </tr>
    </table>

    <table
        role="presentation"
        align="center"
        cellpadding="0"
        cellspacing="0"
        border="0"
        style="margin-top:28px;"
    >
    <tr>
    <td
        bgcolor="#357af0"
        style="
            background:#357af0;
            border-radius:4px;
        "
    >
    <a
        href="{{ cta_url }}"
        style="
            display:inline-block;
            padding:15px 30px;
            font-family:Arial, Helvetica, sans-serif;
            font-size:15px;
            font-weight:700;
            color:#ffffff;
            text-decoration:none;
            border-radius:4px;
        "
    >
    Open inbox
    </a>
    </td>
    </tr>
    </table>

    <p style="
        margin:22px 0 0;
        font-family:Arial, Helvetica, sans-serif;
        font-size:13px;
        line-height:1.6;
        text-align:center;
        color:#8892a3;
    ">
    This completion is based on the scheduled viewing end time.
    </p>

    </td>
    </tr>
    </table>

    </td>
    </tr>
    </table>

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

<table
    role="presentation"
    width="100%"
    cellpadding="0"
    cellspacing="0"
    border="0"
    style="
        width:100%;
        border-collapse:collapse;
    "
>
    <tr>
        <td align="center" style="padding:0;">

            <table
                role="presentation"
                width="100%"
                cellpadding="0"
                cellspacing="0"
                border="0"
                style="
                    width:100%;
                    max-width:620px;
                    border-collapse:separate;
                    background-color:#ffffff;
                    border:1px solid #dfe5ee;
                    border-radius:5px;
                "
            >
                <tr>
                    <td style="padding:34px 34px 32px;">

                        <table
                            role="presentation"
                            width="100%"
                            cellpadding="0"
                            cellspacing="0"
                            border="0"
                            style="
                                width:100%;
                                border-collapse:collapse;
                            "
                        >
                            <tr>
                                <td align="center" style="padding:0 0 16px;">

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:12px;
                                        line-height:1.4;
                                        font-weight:700;
                                        letter-spacing:1.4px;
                                        text-transform:uppercase;
                                        color:#357af0;
                                    ">
                                        Tenancy information
                                    </p>

                                </td>
                            </tr>

                            <tr>
                                <td align="center" style="padding:0 0 10px;">

                                    <h1 style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:28px;
                                        line-height:1.3;
                                        font-weight:700;
                                        letter-spacing:-0.4px;
                                        color:#172033;
                                    ">
                                        Tenancy information received
                                    </h1>

                                </td>
                            </tr>

                            <tr>
                                <td align="center" style="padding:0 0 30px;">

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:15px;
                                        line-height:1.65;
                                        color:#6b7689;
                                    ">
                                        Please review the information recorded for this tenancy.
                                    </p>

                                </td>
                            </tr>

                            <tr>
                                <td style="padding:0 0 16px;">

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:16px;
                                        line-height:1.7;
                                        color:#4f5b70;
                                    ">
                                        Hi {{ user.first_name|default:"there" }},
                                    </p>

                                </td>
                            </tr>

                            <tr>
                                <td style="padding:0 0 26px;">

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:16px;
                                        line-height:1.75;
                                        color:#4f5b70;
                                    ">
                                        Tenancy information has been submitted for
                                        <strong style="color:#172033;">
                                            {{ room_title }}
                                        </strong>.
                                    </p>

                                </td>
                            </tr>

                            <tr>
                                <td style="padding:0;">

                                    <table
                                        role="presentation"
                                        width="100%"
                                        cellpadding="0"
                                        cellspacing="0"
                                        border="0"
                                        style="
                                            width:100%;
                                            border-collapse:separate;
                                            background-color:#f7f9fc;
                                            border:1px solid #dfe6ef;
                                            border-radius:4px;
                                        "
                                    >
                                        <tr>
                                            <td style="padding:20px 22px;">

                                                <p style="
                                                    margin:0 0 6px;
                                                    font-family:Arial, Helvetica, sans-serif;
                                                    font-size:11px;
                                                    line-height:1.4;
                                                    font-weight:700;
                                                    letter-spacing:0.8px;
                                                    text-transform:uppercase;
                                                    color:#7a8497;
                                                ">
                                                    Property
                                                </p>

                                                <p style="
                                                    margin:0;
                                                    font-family:Arial, Helvetica, sans-serif;
                                                    font-size:17px;
                                                    line-height:1.5;
                                                    font-weight:700;
                                                    color:#172033;
                                                ">
                                                    {{ room_title }}
                                                </p>

                                                <p style="
                                                    margin:16px 0 0;
                                                    padding-top:14px;
                                                    border-top:1px solid #e4e9f0;
                                                    font-family:Arial, Helvetica, sans-serif;
                                                    font-size:14px;
                                                    line-height:1.65;
                                                    color:#566176;
                                                ">
                                                    Review the recorded information and confirm that it matches the tenancy agreement you made with the other party outside RentCrib.
                                                </p>

                                            </td>
                                        </tr>
                                    </table>

                                </td>
                            </tr>

                            <tr>
                                <td style="padding:20px 0 0;">

                                    <table
                                        role="presentation"
                                        width="100%"
                                        cellpadding="0"
                                        cellspacing="0"
                                        border="0"
                                        style="
                                            width:100%;
                                            border-collapse:separate;
                                            background-color:#f4f8ff;
                                            border:1px solid #dce8fb;
                                            border-left:4px solid #357af0;
                                            border-radius:4px;
                                        "
                                    >
                                        <tr>
                                            <td style="padding:16px 18px;">

                                                <p style="
                                                    margin:0 0 5px;
                                                    font-family:Arial, Helvetica, sans-serif;
                                                    font-size:14px;
                                                    line-height:1.5;
                                                    font-weight:700;
                                                    color:#172033;
                                                ">
                                                    Important to know
                                                </p>

                                                <p style="
                                                    margin:0;
                                                    font-family:Arial, Helvetica, sans-serif;
                                                    font-size:14px;
                                                    line-height:1.65;
                                                    color:#566176;
                                                ">
                                                    RentCrib does not create or replace tenancy agreements. We help both parties record and keep track of the tenancy information they agreed outside RentCrib.
                                                </p>

                                            </td>
                                        </tr>
                                    </table>

                                </td>
                            </tr>

                            <tr>
                                <td align="center" style="padding:26px 0 0;">

                                    <table
                                        role="presentation"
                                        cellpadding="0"
                                        cellspacing="0"
                                        border="0"
                                    >
                                        <tr>
                                            <td
                                                align="center"
                                                bgcolor="#357af0"
                                                style="
                                                    background-color:#357af0;
                                                    border-radius:4px;
                                                "
                                            >
                                                <a
                                                    href="{{ cta_url }}"
                                                    style="
                                                        display:inline-block;
                                                        min-width:220px;
                                                        padding:15px 28px;
                                                        font-family:Arial, Helvetica, sans-serif;
                                                        font-size:15px;
                                                        line-height:1.2;
                                                        font-weight:700;
                                                        color:#ffffff;
                                                        text-decoration:none;
                                                        text-align:center;
                                                        border-radius:4px;
                                                    "
                                                >
                                                    Review tenancy information
                                                </a>
                                            </td>
                                        </tr>
                                    </table>

                                </td>
                            </tr>

                            <tr>
                                <td align="center" style="padding:20px 0 0;">

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:13px;
                                        line-height:1.65;
                                        color:#8892a3;
                                    ">
                                        Review the information carefully before confirming it.
                                    </p>

                                </td>
                            </tr>

                            <tr>
                                <td align="center" style="padding:22px 0 0;">

                                    <p style="
                                        margin:0 0 6px;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:12px;
                                        line-height:1.6;
                                        color:#98a1af;
                                    ">
                                        If the button does not work, copy and paste this link into your browser:
                                    </p>

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:12px;
                                        line-height:1.6;
                                        word-break:break-all;
                                    ">
                                        <a
                                            href="{{ cta_url }}"
                                            style="
                                                color:#357af0;
                                                text-decoration:underline;
                                            "
                                        >
                                            {{ cta_url }}
                                        </a>
                                    </p>

                                </td>
                            </tr>
                        </table>

                    </td>
                </tr>
            </table>

        </td>
    </tr>
</table>

{% endblock %}
""",
},
    
  {
    "key": "tenancy.updated",
    "subject": "Tenancy information updated for {{ room_title }}",
    "body": """
{% extends "emails/base.html" %}

{% block content %}

<table
    role="presentation"
    width="100%"
    cellpadding="0"
    cellspacing="0"
    border="0"
    style="
        width:100%;
        border-collapse:collapse;
    "
>
    <tr>
        <td align="center">

            <table
                role="presentation"
                width="100%"
                cellpadding="0"
                cellspacing="0"
                border="0"
                style="
                    width:100%;
                    max-width:620px;
                    background:#ffffff;
                    border:1px solid #e1e7ef;
                    border-radius:5px;
                "
            >
                <tr>
                    <td style="padding:34px 34px 32px;">

                        <p style="
                            margin:0 0 16px;
                            font-family:Arial, Helvetica, sans-serif;
                            font-size:12px;
                            line-height:1.4;
                            font-weight:700;
                            letter-spacing:1.4px;
                            text-transform:uppercase;
                            text-align:center;
                            color:#357af0;
                        ">
                            Tenancy update
                        </p>

                        <h1 style="
                            margin:0;
                            font-family:Arial, Helvetica, sans-serif;
                            font-size:28px;
                            line-height:1.3;
                            font-weight:700;
                            letter-spacing:-0.4px;
                            text-align:center;
                            color:#172033;
                        ">
                            Your tenancy information has been updated
                        </h1>

                        <p style="
                            margin:10px 0 30px;
                            font-family:Arial, Helvetica, sans-serif;
                            font-size:15px;
                            line-height:1.6;
                            text-align:center;
                            color:#6b7689;
                        ">
                            The latest tenancy details are shown below.
                        </p>

                        <p style="
                            margin:0 0 16px;
                            font-family:Arial, Helvetica, sans-serif;
                            font-size:16px;
                            line-height:1.7;
                            color:#4f5b70;
                        ">
                            Hi {{ user.first_name|default:"there" }},
                        </p>

                        <p style="
                            margin:0 0 26px;
                            font-family:Arial, Helvetica, sans-serif;
                            font-size:16px;
                            line-height:1.7;
                            color:#4f5b70;
                        ">
                            The tenancy information recorded for this property has been updated.
                        </p>

                        <table
                            role="presentation"
                            width="100%"
                            cellpadding="0"
                            cellspacing="0"
                            border="0"
                            style="
                                width:100%;
                                border-collapse:separate;
                                background:#f7f9fc;
                                border:1px solid #dfe6ef;
                                border-radius:4px;
                            "
                        >
                            <tr>
                                <td style="padding:20px 22px;">

                                    <p style="
                                        margin:0 0 6px;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:11px;
                                        line-height:1.4;
                                        font-weight:700;
                                        letter-spacing:0.8px;
                                        text-transform:uppercase;
                                        color:#7a8497;
                                    ">
                                        Tenancy details
                                    </p>

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:17px;
                                        line-height:1.5;
                                        font-weight:700;
                                        color:#172033;
                                    ">
                                        {{ room_title }}
                                    </p>

                                    <table
                                        role="presentation"
                                        width="100%"
                                        cellpadding="0"
                                        cellspacing="0"
                                        border="0"
                                        style="
                                            width:100%;
                                            margin-top:16px;
                                            border-collapse:collapse;
                                        "
                                    >
                                        <tr>
                                            <td style="
                                                padding:14px 12px 14px 0;
                                                border-top:1px solid #e4e9f0;
                                                font-family:Arial, Helvetica, sans-serif;
                                                font-size:14px;
                                                line-height:1.5;
                                                color:#566176;
                                            ">
                                                Move-in date
                                            </td>

                                            <td align="right" style="
                                                padding:14px 0 14px 12px;
                                                border-top:1px solid #e4e9f0;
                                                font-family:Arial, Helvetica, sans-serif;
                                                font-size:14px;
                                                line-height:1.5;
                                                font-weight:700;
                                                color:#172033;
                                            ">
                                                {{ move_in_date }}
                                            </td>
                                        </tr>

                                        <tr>
                                            <td style="
                                                padding:14px 12px 14px 0;
                                                border-top:1px solid #e4e9f0;
                                                font-family:Arial, Helvetica, sans-serif;
                                                font-size:14px;
                                                line-height:1.5;
                                                color:#566176;
                                            ">
                                                Monthly rent
                                            </td>

                                            <td align="right" style="
                                                padding:14px 0 14px 12px;
                                                border-top:1px solid #e4e9f0;
                                                font-family:Arial, Helvetica, sans-serif;
                                                font-size:14px;
                                                line-height:1.5;
                                                font-weight:700;
                                                color:#172033;
                                            ">
                                                £{{ monthly_rent }} per month
                                            </td>
                                        </tr>

                                        <tr>
                                            <td style="
                                                padding:14px 12px 0 0;
                                                border-top:1px solid #e4e9f0;
                                                font-family:Arial, Helvetica, sans-serif;
                                                font-size:14px;
                                                line-height:1.5;
                                                color:#566176;
                                            ">
                                                Tenancy duration
                                            </td>

                                            <td align="right" style="
                                                padding:14px 0 0 12px;
                                                border-top:1px solid #e4e9f0;
                                                font-family:Arial, Helvetica, sans-serif;
                                                font-size:14px;
                                                line-height:1.5;
                                                font-weight:700;
                                                color:#172033;
                                            ">
                                                {{ duration_months }} month{{ duration_months|pluralize }}
                                            </td>
                                        </tr>
                                    </table>

                                </td>
                            </tr>
                        </table>

                        <table
                            role="presentation"
                            width="100%"
                            cellpadding="0"
                            cellspacing="0"
                            border="0"
                            style="
                                width:100%;
                                margin-top:20px;
                                border-collapse:separate;
                                background:#f4f8ff;
                                border:1px solid #dce8fb;
                                border-left:4px solid #357af0;
                                border-radius:4px;
                            "
                        >
                            <tr>
                                <td style="padding:16px 18px;">

                                    <p style="
                                        margin:0 0 5px;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:14px;
                                        line-height:1.5;
                                        font-weight:700;
                                        color:#172033;
                                    ">
                                        Important to know
                                    </p>

                                    <p style="
                                        margin:0;
                                        font-family:Arial, Helvetica, sans-serif;
                                        font-size:14px;
                                        line-height:1.65;
                                        color:#566176;
                                    ">
                                        Please ensure these details match the tenancy information agreed between both parties. RentCrib records this information to help both parties keep track of their tenancy.
                                    </p>

                                </td>
                            </tr>
                        </table>

                        <p style="
                            margin:24px 0 0;
                            font-family:Arial, Helvetica, sans-serif;
                            font-size:13px;
                            line-height:1.65;
                            text-align:center;
                            color:#8892a3;
                        ">
                            No action is required if these details are correct.
                        </p>

                    </td>
                </tr>
            </table>

        </td>
    </tr>
</table>

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
    "subject": "Your tenancy for {{ room_title }} is ending soon",
    "body": """
    {% extends "emails/base.html" %}

    {% block content %}

    <h2 style="
        font-family:Arial,sans-serif;
        color:#333333;
    ">
        Your tenancy is ending soon
    </h2>

    <p>
        Hi {{ user.first_name }},
    </p>

    <p>
        Your tenancy for:
    </p>

    <p>
        <strong>{{ room_title }}</strong>
    </p>

    <p>
        is due to end soon.
    </p>

    <p>
        If you plan to continue staying, please update your tenancy information.
    </p>

    <p>
        If you are moving out, no action is required.
    </p>

    {% include "emails/components/button.html" with button_url=cta_url button_text="Update tenancy" %}

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
    
        {
        "key": "booking.reminder",
        "subject": "Reminder: your viewing starts soon for {{ room_title }}",
        "body": """
        {% include "emails/booking/reminder.html" %}
        """,
    },

    {
        "key": "identity_verification.received",
        "subject": "We've received your identity verification",
        "body": """
        {% include "emails/identity_verification/request_received.html" %}
        """,
    },
    {
        "key": "identity_verification.approved",
        "subject": "Your identity has been verified",
        "body": """
        {% include "emails/identity_verification/approved.html" %}
        """,
    },
    {
        "key": "identity_verification.rejected",
        "subject": "We couldn't complete your identity verification",
        "body": """
        {% include "emails/identity_verification/rejected.html" %}
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

