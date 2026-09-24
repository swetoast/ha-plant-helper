from __future__ import annotations

from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .domain.image_proxy import SpeciesImageProxy

IMAGE_PATH = "/api/plant_helper/image/{hash}"


class PlantHelperImageView(HomeAssistantView):
    """Serve sanitized, cached species thumbnails from the local proxy."""

    url = "/api/plant_helper/image/{digest}"
    name = "api:plant_helper:image"
    requires_auth = True

    def __init__(self, proxy: SpeciesImageProxy) -> None:
        self.proxy = proxy

    async def get(self, request: Any, digest: str) -> web.Response:
        user = getattr(request, "user", None)
        authenticated = bool(user and getattr(user, "is_authenticated", True))
        response = self.proxy.serve(
            digest, authenticated, request.headers.get("If-None-Match")
        )
        return web.Response(
            status=response.status,
            headers=dict(response.headers),
            body=response.body,
        )
