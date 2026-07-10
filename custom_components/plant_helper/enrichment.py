"""Species enrichment mapping (pure, no Home Assistant).

Turns raw provider payloads (Perenual / Trefle / iNaturalist) into a compact,
meaningful set of care context: a clean attribute set, a photo URL, a *suggested*
care profile, and a reference watering interval the user can compare against the
learned drying rate. This is the "meaningful use" of the external APIs — context
and a setup hint — without letting them override the calibrated engine.
"""

from __future__ import annotations

from typing import Any

# Watering word -> rough interval in days (Perenual's coarse scale).
_WATERING_DAYS = {"frequent": 3.0, "average": 7.0, "minimum": 14.0, "none": 21.0}


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _photo_url(data: dict[str, Any]) -> str | None:
    """Best available image URL across the providers' shapes."""
    img = data.get("default_image")
    if isinstance(img, dict):
        for k in ("regular_url", "medium_url", "original_url", "small_url", "thumbnail"):
            if img.get(k):
                return img[k]
    if isinstance(img, str) and img.startswith("http"):
        return img
    photos = data.get("photos")
    if isinstance(photos, list) and photos:
        first = photos[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("medium_url") or first.get("url")
    # Nested iNaturalist enrichment block (older cache shape).
    inat = data.get("inat")
    if isinstance(inat, dict):
        ip = inat.get("photos")
        if isinstance(ip, list) and ip:
            f = ip[0]
            if isinstance(f, dict):
                return f.get("url") or f.get("medium_url")
            if isinstance(f, str):
                return f
    for k in ("image_url", "image"):
        if isinstance(data.get(k), str) and data[k].startswith("http"):
            return data[k]
    return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "yes", "1"):
            return True
        if low in ("false", "no", "0"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def reference_watering_days(data: dict[str, Any]) -> float | None:
    """A reference watering interval (days) from the provider data, if any.

    Prefers Perenual's explicit benchmark (e.g. "5-7 days"), else maps the coarse
    watering word. Returned so the entity can sit next to the engine's learned
    `days_until_dry` as a sanity check — not as a control input.
    """
    bench = data.get("watering_general_benchmark") or data.get("watering_benchmark")
    if isinstance(bench, dict):
        val = str(bench.get("value") or "").replace("–", "-")
        parts = [p.strip() for p in val.split("-") if p.strip()]
        nums: list[float] = []
        for p in parts:
            try:
                nums.append(float(p))
            except ValueError:
                pass
        if nums:
            return round(sum(nums) / len(nums), 1)
    word = str(data.get("watering") or "").strip().lower()
    return _WATERING_DAYS.get(word)


def suggested_profile(data: dict[str, Any]) -> str | None:
    """A care-profile hint from enrichment (setup guidance only).

    dry_tolerant for drought-tolerant / minimal waterers; moisture_loving for
    frequent waterers or high soil-moisture preference; balanced otherwise.
    """
    if _as_bool(data.get("drought_tolerant")):
        return "dry_tolerant"
    watering = str(data.get("watering") or "").strip().lower()
    if watering == "minimum":
        return "dry_tolerant"
    if watering == "frequent":
        return "moisture_loving"

    soil = data.get("soil_moisture")  # Trefle 0-10 scale
    try:
        soil_v = float(soil) if soil is not None else None
    except (TypeError, ValueError):
        soil_v = None
    if soil_v is not None:
        if soil_v >= 7:
            return "moisture_loving"
        if soil_v <= 3:
            return "dry_tolerant"
        return "balanced"

    if watering == "average":
        return "balanced"
    return None


def summarize_enrichment(data: dict[str, Any] | None) -> dict[str, Any]:
    """Compact, meaningful attribute set for the Species entity.

    Only carries fields with real value: identity, care guidance, toxicity
    (actionable for pet owners), environmental preferences, a photo, and the
    derived hints. Empty inputs yield an empty dict.
    """
    if not data:
        return {}

    out: dict[str, Any] = {}

    def put(key: str, value: Any) -> None:
        if value not in (None, "", [], {}):
            out[key] = value

    put("common_name", data.get("common_name"))
    put("scientific_name", _first(data.get("scientific_name")) or data.get("species"))
    put("family", data.get("family"))
    put("cycle", data.get("cycle"))
    put("care_level", data.get("care_level"))
    put("maintenance", data.get("maintenance"))
    put("watering", data.get("watering"))
    put("sunlight", data.get("sunlight"))
    put("indoor", _as_bool(data.get("indoor")))
    put("drought_tolerant", _as_bool(data.get("drought_tolerant")))
    put("poisonous_to_pets", _as_bool(data.get("poisonous_to_pets")))
    put("poisonous_to_humans", _as_bool(data.get("poisonous_to_humans")))

    # Trefle botanical preferences (reference only).
    put("light_requirement_0_10", data.get("light"))
    put("soil_moisture_pref_0_10", data.get("soil_moisture"))
    put("min_temperature_c", data.get("minimum_temperature_c") or data.get("min_temperature_c"))
    put("max_temperature_c", data.get("maximum_temperature_c") or data.get("max_temperature_c"))

    desc = data.get("description") or data.get("wikipedia_summary")
    if isinstance(desc, str) and desc:
        put("description", desc[:500])

    put("photo", _photo_url(data))
    put("reference_watering_days", reference_watering_days(data))
    put("suggested_profile", suggested_profile(data))
    providers = data.get("providers")
    if providers:
        put("source", ", ".join(providers))
    else:
        put("source", data.get("provider") or data.get("source"))
    return out


# --- provider merge (uses all three meaningfully) -------------------------

def _pick(*values: Any) -> Any:
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None


def merge_provider_data(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge normalized payloads from Perenual/Trefle/iNaturalist into one record.

    Field precedence reflects each provider's strength:
      * identity (scientific name, photo, wiki) -> iNaturalist (canonical taxonomy)
      * care (watering, sunlight, toxicity, ...) -> Perenual
      * botanical priors (light, soil moisture, temps, pH) -> Trefle
    First non-empty wins within each group; the result lists which providers
    contributed. Pure, so it's unit-tested.
    """
    by = {p.get("provider"): p for p in parts if isinstance(p, dict)}
    per = by.get("perenual", {})
    inat = by.get("inaturalist", {})
    tre = by.get("trefle", {})
    out: dict[str, Any] = {}

    out["scientific_name"] = _pick(
        inat.get("scientific_name"), _first(per.get("scientific_name")),
        _first(tre.get("scientific_name")), _first(per.get("species")),
    )
    out["common_name"] = _pick(per.get("common_name"), inat.get("common_name"), tre.get("common_name"))
    out["family"] = _pick(tre.get("family"), inat.get("family"), per.get("family"))

    for key in (
        "watering", "sunlight", "cycle", "care_level", "maintenance",
        "drought_tolerant", "indoor", "poisonous_to_pets", "poisonous_to_humans",
        "watering_general_benchmark", "growth_rate",
    ):
        if per.get(key) not in (None, "", [], {}):
            out[key] = per[key]

    for key in ("light", "soil_moisture", "minimum_temperature_c", "maximum_temperature_c", "ph_min", "ph_max"):
        if tre.get(key) not in (None, "", [], {}):
            out[key] = tre[key]
    out.update(_trefle_botanical(tre))

    out["description"] = _pick(per.get("description"), inat.get("description"))
    out["photo"] = _pick(_photo_url(per), inat.get("photo"), _photo_url(inat))
    out["photos"] = _pick(inat.get("photos"), per.get("photos")) or []
    out["wikipedia_url"] = inat.get("wikipedia_url")
    out["providers"] = [p for p in ("perenual", "inaturalist", "trefle") if p in by]

    return {k: v for k, v in out.items() if v not in (None, "", [], {})}


def _trefle_botanical(tre: dict[str, Any]) -> dict[str, Any]:
    """Pull botanical priors from Trefle's actual nested shape (growth/thresholds).

    Trefle normalizes into a `growth` sub-dict (light, soil_moisture, min/max
    temperature as {deg_c}, ph_minimum/maximum), not flat keys. Falls back to flat
    keys if a caller already flattened them.
    """
    growth = tre.get("growth") or {}
    out: dict[str, Any] = {}

    def _num(*vals: Any) -> Any:
        for v in vals:
            if v not in (None, "", [], {}):
                return v
        return None

    def _deg_c(node: Any) -> Any:
        return node.get("deg_c") if isinstance(node, dict) else node

    light = _num(growth.get("light"), tre.get("light"))
    soil = _num(growth.get("soil_moisture"), tre.get("soil_moisture"))
    min_t = _num(_deg_c(growth.get("minimum_temperature")), tre.get("minimum_temperature_c"))
    max_t = _num(_deg_c(growth.get("maximum_temperature")), tre.get("maximum_temperature_c"))
    ph_min = _num(growth.get("ph_minimum"), tre.get("ph_min"))
    ph_max = _num(growth.get("ph_maximum"), tre.get("ph_max"))

    for key, val in (
        ("light", light), ("soil_moisture", soil),
        ("minimum_temperature_c", min_t), ("maximum_temperature_c", max_t),
        ("ph_min", ph_min), ("ph_max", ph_max),
    ):
        if val not in (None, "", [], {}):
            out[key] = val
    return out
