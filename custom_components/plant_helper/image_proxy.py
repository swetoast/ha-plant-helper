from __future__ import annotations

from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .domain.image_proxy import SpeciesImageProxy

IMAGE_PATH = "/api/plant_helper/image/{hash}"
_PROXY_KEY = "image_proxy"
_VIEW_REGISTERED_KEY = "image_view_registered"


def async_set_image_proxy(hass: HomeAssistant, proxy: SpeciesImageProxy | None) -> None:
    """Point the image view at the current proxy, registering the view once.

    HTTP routes cannot be registered twice, and a config-entry reload builds a
    new proxy, so the view is registered once per Home Assistant instance and
    resolves the live proxy on each request. Passing None (on unload) makes the
    view answer 404 instead of serving from a torn-down proxy.
    """
    data = hass.data.setdefault(DOMAIN, {})
    data[_PROXY_KEY] = proxy
    if proxy is not None and not data.get(_VIEW_REGISTERED_KEY):
        hass.http.register_view(PlantHelperImageView(hass))
        data[_VIEW_REGISTERED_KEY] = True


class PlantHelperImageView(HomeAssistantView):
    """Serve sanitized, cached species thumbnails from the local proxy."""

    url = "/api/plant_helper/image/{digest}"
    name = "api:plant_helper:image"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: Any, digest: str) -> web.Response:
        proxy = self.hass.data.get(DOMAIN, {}).get(_PROXY_KEY)
        if proxy is None:
            return web.Response(status=404, headers={"Cache-Control": "no-store"})
        user = getattr(request, "user", None)
        authenticated = bool(user and getattr(user, "is_authenticated", True))
        response = await proxy.async_serve(
            digest, authenticated, request.headers.get("If-None-Match")
        )
        return web.Response(
            status=response.status,
            headers=dict(response.headers),
            body=response.body,
        )
