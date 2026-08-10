from django.core import signing

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .common import ok_response


REALTIME_TICKET_SALT = "rentcrib.realtime.websocket"
REALTIME_TICKET_MAX_AGE_SECONDS = 60


class RealtimeTicketView(APIView):
    """
    Create a short-lived signed ticket used only to authenticate
    a new RentCrib WebSocket connection.

    This does NOT replace or modify normal JWT/cookie authentication.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        ticket = signing.dumps(
            {
                "user_id": request.user.id,
            },
            salt=REALTIME_TICKET_SALT,
            compress=True,
        )

        return ok_response(
            {
                "ticket": ticket,
                "expires_in": REALTIME_TICKET_MAX_AGE_SECONDS,
            },
            message="Realtime connection ticket created.",
            status_code=200,
        )