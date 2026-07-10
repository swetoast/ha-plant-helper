"""Shared helpers for Plant Helper.

Provider-payload parsing used by the config flow when caching species from the
enrichment providers. (Threshold/entity-resolution helpers were removed with the
v3 algorithm; the v4 engine derives everything from learned baselines.)
"""

from __future__ import annotations

from typing import Any


def extract_species_key(data: dict[str, Any], fallback: str) -> str:
    """Extract a stable species key from a provider payload."""
    for key in (
        "species",
        "scientific_name",
        "scientificName",
        "latin_name",
        "latinName",
        "name",
    ):
        value = data.get(key)
        if isinstance(value, list) and value and str(value[0]).strip():
            return str(value[0]).strip()
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback.strip()


def extract_common_name(data: dict[str, Any], fallback: str) -> str:
    """Extract a display common name from a provider payload."""
    for key in ("common_name", "commonName", "common", "name"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback.strip()
