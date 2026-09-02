from django.conf import settings


def _frontend_base_url() -> str:
    base = getattr(settings, "FRONTEND_BASE_URL", "") or ""
    return base.rstrip("/")


def _safe_next_path(
    next_path: str,
    default: str = "/messages",
) -> str:
    if not next_path or not isinstance(next_path, str):
        return default

    next_path = next_path.strip()

    if not next_path.startswith("/"):
        return default

    return next_path


def build_absolute_url(
    path: str,
    *,
    force_login: bool = False,
) -> str:
    """
    Build a frontend URL for emails and notifications.

    Email links always point directly to their intended frontend
    destination.

    Authentication is decided by the frontend when the link opens:

    - An already authenticated browser uses its existing session and
      opens the destination immediately.
    - An unauthenticated browser is redirected to login by the
      frontend auth guard and should return to the original destination
      after successful authentication.

    ``force_login`` is retained as a backwards-compatible argument
    because existing notification producers still pass it. It no
    longer changes the generated URL.
    """
    base = _frontend_base_url()
    safe_path = _safe_next_path(
        path,
        default="/messages",
    )

    return f"{base}{safe_path}"