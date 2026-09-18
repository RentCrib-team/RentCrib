from typing import Optional
from django.conf import settings
from rest_framework.response import Response

from .cache import make_cache_key, get_cached_json, set_cached_json


class CachedAnonymousGETMixin:
    """
    Drop-in mixin for DRF views:
    - Caches GET responses for anonymous and authenticated callers
    - Authenticated cache entries are isolated per requesting user
    - Uses per-view prefix to isolate keys
    - Stores/returns the response data payload (JSON-serializable)
    - Uses the global cache buster so when room data changes,
      new keys are automatically used.

    The historical class name is kept for import compatibility.
    """

    cache_prefix: str = "v1"
    cache_ttl: Optional[int] = None  # override per-view
    cache_timeout: int = 60  # fallback default

    def _cache_should_use(self, request) -> bool:
        """Use cache for all GETs; make_cache_key isolates authenticated users."""
        return request.method == "GET"

    def _cache_ttl(self) -> int:
        """Get TTL (seconds) for this view."""
        if self.cache_ttl is not None:
            return self.cache_ttl
        return getattr(settings, "CACHE_DEFAULT_TTL", self.cache_timeout)

    def _make_key(self, request):
        return make_cache_key(self.cache_prefix, request.path, request=request)

    def _get_cached_response(self, request):
        if not self._cache_should_use(request):
            return None
        cached = get_cached_json(self._make_key(request))
        if cached is None:
            return None
        return Response(cached)

    def _store_cached_response(self, request, response):
        if (
            self._cache_should_use(request)
            and getattr(response, "status_code", None) == 200
        ):
            set_cached_json(
                self._make_key(request),
                response.data,
                ttl=self._cache_ttl(),
            )
        return response

    # For ListAPIView
    def list(self, request, *args, **kwargs):
        cached = self._get_cached_response(request)
        if cached is not None:
            return cached
        resp = super().list(request, *args, **kwargs)
        return self._store_cached_response(request, resp)

    # For RetrieveAPIView / APIView.get
    def get(self, request, *args, **kwargs):
        cached = self._get_cached_response(request)
        if cached is not None:
            return cached
        resp = super().get(request, *args, **kwargs)
        return self._store_cached_response(request, resp)
