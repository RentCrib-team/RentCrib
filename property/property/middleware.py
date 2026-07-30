import uuid
from time import perf_counter
import threading

_request_local = threading.local()

def get_current_request_id() -> str:
    return getattr(_request_local, "request_id", "-")


class RequestIDMiddleware:
    """
    Adds X-Request-ID to every response.
    - If client sends X-Request-ID, we keep it.
    - Otherwise generate UUID4.
    Also stores request_id in threadlocal so logs can include it.
    """
    HEADER_IN = "HTTP_X_REQUEST_ID"
    HEADER_OUT = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.META.get(self.HEADER_IN) or str(uuid.uuid4())
        request.request_id = request_id
        _request_local.request_id = request_id

        start = perf_counter()

        response = self.get_response(request)

        duration_ms = int((perf_counter() - start) * 1000)

        response[self.HEADER_OUT] = request_id
        response["X-Response-Time-ms"] = str(duration_ms)

        return response
    
    
    
    
class SecurityHeadersMiddleware:
    """
    Adds browser security headers to every Django response.

    These headers provide defence-in-depth for API responses and browser-based
    API documentation such as Swagger UI and ReDoc.
    """

    CONTENT_SECURITY_POLICY = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )

    PERMISSIONS_POLICY = (
        "camera=(), "
        "microphone=(), "
        "geolocation=(), "
        "payment=(), "
        "usb=(), "
        "interest-cohort=()"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        response.setdefault(
            "Content-Security-Policy",
            self.CONTENT_SECURITY_POLICY,
        )
        response.setdefault(
            "Permissions-Policy",
            self.PERMISSIONS_POLICY,
        )

        return response    