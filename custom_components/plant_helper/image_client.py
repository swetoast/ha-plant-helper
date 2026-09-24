"""aiohttp downloader that feeds SpeciesImageProxy.

Thin Home Assistant glue, mirroring weather.py: the proxy owns all validation,
redirect handling, and transformation. This only performs one hop with redirects
disabled (the proxy re-validates every hop for SSRF) and caps the read at the
proxy's maximum so an oversized body is refused before it is fully buffered.
"""
from __future__ import annotations

from aiohttp import ClientSession, ClientTimeout

from .domain.image_proxy import MAX_DOWNLOAD, DownloadResponse

_TIMEOUT = ClientTimeout(total=30)


class ImageDownloader:
    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def fetch(self, url: str) -> DownloadResponse:
        async with self._session.get(
            url, timeout=_TIMEOUT, allow_redirects=False
        ) as response:
            # StreamReader.read(n) returns only what is currently buffered (up to n),
            # not the whole body, so a multi-chunk image arrives truncated and fails to
            # decode. Accumulate chunks until EOF or the proxy size cap is exceeded; an
            # oversized body stops early and is refused by the proxy's length check.
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.content.iter_chunked(65536):
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    break
            return DownloadResponse(
                status=response.status,
                headers=dict(response.headers),
                body=b"".join(chunks),
                url=str(response.url),
            )
