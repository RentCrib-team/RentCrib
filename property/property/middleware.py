import logging
import threading
import uuid
from time import perf_counter

_request_local = threading.local()

def get_current_request_id() -> str:
    return getattr(_request_local, "request_id", "-")


class RequestIDMiddleware:
    """
    Adds safe request correlation and backend timing information.

    - Preserves a client-supplied X-Request-ID when present.
    - Otherwise generates a UUID4 request identifier.
    - Measures Django request/response processing time.
    - Exposes the measurement through response headers.
    - Logs only safe request metadata.

    Request bodies, query-string values, cookies, authorization headers,
    credentials, and tokens are never logged here.
    """

    HEADER_IN = "HTTP_X_REQUEST_ID"
    HEADER_OUT = "X-Request-ID"
    TIMING_HEADER = "X-Backend-Response-Time-Ms"
    LEGACY_TIMING_HEADER = "X-Response-Time-ms"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = (
            request.META.get(self.HEADER_IN)
            or str(uuid.uuid4())
        )

        request.request_id = request_id
        _request_local.request_id = request_id

        start = perf_counter()

        response = self.get_response(request)

        duration_ms = (
            perf_counter() - start
        ) * 1000

        duration_text = f"{duration_ms:.3f}"

        response[self.HEADER_OUT] = request_id
        response[self.TIMING_HEADER] = duration_text

        # Keep the existing header so current clients are not broken.
        response[self.LEGACY_TIMING_HEADER] = duration_text

        logging.getLogger("property.performance").info(
            "REST performance "
            "request_id=%s method=%s path=%s "
            "status=%s backend_response_ms=%s",
            request_id,
            request.method,
            request.path,
            response.status_code,
            duration_text,
        )

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