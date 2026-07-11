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


def _valid_photo(url: Any) -> str | None:
    """A usable photo URL, or None. Rejects Perenual's free-tier placeholder
    (an 'upgrade_access.jpg' image that 404s) and non-http values."""
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    low = url.lower()
    if "upgrade_access" in low or "upgrade-access" in low or "/upgrade." in low:
        return None
    return url


def _photo_url(data: dict[str, Any]) -> str | None:
    """Best available image URL across the providers' shapes (placeholders rejected)."""
    img = data.get("default_image")
    if isinstance(img, dict):
        for k in ("regular_url", "medium_url", "original_url", "small_url", "thumbnail"):
            got = _valid_photo(img.get(k))
            if got:
                return got
    got = _valid_photo(img) if isinstance(img, str) else None
    if got:
        return got
    photos = data.get("photos")
    if isinstance(photos, list) and photos:
        first = photos[0]
        if isinstance(first, str):
            got = _valid_photo(first)
            if got:
                return got
        elif isinstance(first, dict):
            got = _valid_photo(first.get("medium_url") or first.get("url"))
            if got:
                return got
    inat = data.get("inat")
    if isinstance(inat, dict):
        ip = inat.get("photos")
        if isinstance(ip, list) and ip:
            f = ip[0]
            if isinstance(f, dict):
                got = _valid_photo(f.get("url") or f.get("medium_url"))
                if got:
                    return got
            elif isinstance(f, str):
                got = _valid_photo(f)
                if got:
                    return got
    for k in ("image_url", "image"):
        got = _valid_photo(data.get(k))
        if got:
            return got
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
    put("family", _family_name(data.get("family")))
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

    put("photo", _valid_photo(data.get("photo")) or _photo_url(data))
    put("wikipedia_url", data.get("wikipedia_url"))
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


def _family_name(value: Any) -> str | None:
    """Family as a plain string. Trefle returns a nested object ({name, ...});
    Perenual/iNaturalist return a string. Normalize to the name."""
    if isinstance(value, dict):
        return value.get("name") or value.get("common_name")
    if isinstance(value, str) and value.strip():
        return value.strip()
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
    out["family"] = _family_name(_pick(per.get("family"), inat.get("family"), tre.get("family")))

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
    # iNaturalist first: its photos are real and keyless. Perenual's free-tier
    # image is an 'upgrade_access' placeholder that 404s, so it comes last and
    # only if it passes the placeholder filter.
    out["photo"] = _pick(_valid_photo(inat.get("photo")), _photo_url(inat), _photo_url(per))
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
    soil = _num(
        growth.get("soil_moisture"), growth.get("soil_humidity"),
        growth.get("atmospheric_humidity"), tre.get("soil_moisture"),
    )
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


# --- species insight: priors, confidence, explanations (read-only) --------
#
# Level 2 + 2.5 of the "a say, not the wheel" design. These attributes let the
# external providers offer confidence checks and explanations WITHOUT ever
# changing a care decision. The calibrated engine still owns every decision; this
# only annotates. Pure and testable — the coordinator supplies the learned side.

_SIGNAL_FIELDS = (
    "watering", "sunlight", "care_level", "drought_tolerant", "indoor",
    "soil_moisture_pref_0_10", "light_requirement_0_10", "reference_watering_days",
    "min_temperature_c", "max_temperature_c", "description", "poisonous_to_pets",
)


def species_data_quality(enrichment: dict[str, Any]) -> str:
    """How much usable species data the providers actually returned."""
    if not enrichment:
        return "none"
    fields = sum(1 for f in _SIGNAL_FIELDS if enrichment.get(f) not in (None, "", [], {}))
    providers = len((enrichment.get("source") or "").split(",")) if enrichment.get("source") else 0
    if fields == 0:
        return "none"
    if fields >= 6 or providers >= 3:
        return "high"
    if fields >= 3 or providers >= 2:
        return "medium"
    return "low"


def light_preference(enrichment: dict[str, Any]) -> str | None:
    """A coarse light-need label from Trefle's 0-10 scale or Perenual's sunlight."""
    light = enrichment.get("light_requirement_0_10")
    try:
        if light is not None:
            lv = float(light)
            if lv <= 3:
                return "low_light"
            if lv <= 6:
                return "bright_indirect"
            return "full_sun"
    except (TypeError, ValueError):
        pass
    sun = enrichment.get("sunlight")
    tokens = " ".join(sun).lower() if isinstance(sun, list) else str(sun or "").lower()
    if not tokens:
        return None
    if "full" in tokens and "sun" in tokens:
        return "full_sun"
    if "part" in tokens or "indirect" in tokens or "filtered" in tokens:
        return "bright_indirect"
    if "shade" in tokens or "low" in tokens:
        return "low_light"
    return None


def _watering_comparison(reference: float | None, learned: float | None) -> str:
    if learned is None:
        return "calibrating"
    if reference is None:
        return "no_reference"
    if reference <= 0:
        return "no_reference"
    ratio = learned / reference
    if ratio < 0.7:
        return "dries_faster_than_reference"
    if ratio > 1.4:
        return "dries_slower_than_reference"
    return "matches_reference"


def _baseline_fit(reference: float | None, learned: float | None, calibrating: bool) -> str:
    if calibrating or learned is None:
        return "pending"
    if reference is None or reference <= 0:
        return "unknown"  # nothing to compare against
    ratio = learned / reference
    # Deliberately lenient: indoor light and pots vary a lot. Only a large gap
    # is worth a "look", never a hard "wrong".
    if ratio < 0.3 or ratio > 3.0:
        return "outside_expected"
    return "plausible"


def _calibration_hint(enrichment: dict[str, Any], quality: str, calibrating: bool) -> str | None:
    """Explanation only (Level 2.5). Contextualizes; never suppresses an alert."""
    if not calibrating:
        return None
    if quality == "none":
        return "No species reference available yet; care is based entirely on this plant's own calibration."
    profile = enrichment.get("suggested_profile")
    if profile == "dry_tolerant" or enrichment.get("drought_tolerant"):
        return ("Reference suggests a drought-tolerant species, so damp readings early on may be "
                "normal — alerts still fire, but expect fewer once the baseline locks.")
    if profile == "moisture_loving":
        return ("Reference suggests a moisture-loving species, so dry readings while learning are "
                "expected to prompt watering.")
    return "Species reference loaded; the baseline is still learning this plant's own behaviour."


def species_insight(
    enrichment: dict[str, Any] | None,
    *,
    calibrating: bool,
    learned_interval_days: float | None = None,
) -> dict[str, Any]:
    """Read-only species-insight attributes (priors, confidence, explanations).

    `learned_interval_days` is the plant's own full->dry interval once known
    (None during calibration / until the engine exposes it). Nothing here feeds
    back into care decisions.
    """
    enrichment = enrichment or {}
    quality = species_data_quality(enrichment)
    reference = enrichment.get("reference_watering_days")
    out: dict[str, Any] = {
        "species_data_quality": quality,
        "provider_reference_watering_days": reference,
        "learned_watering_interval_days": learned_interval_days,
        "watering_interval_comparison": _watering_comparison(reference, learned_interval_days),
        "baseline_species_fit": _baseline_fit(reference, learned_interval_days, calibrating),
    }
    light = light_preference(enrichment)
    if light:
        out["light_preference"] = light
    if enrichment.get("suggested_profile"):
        out["suggested_profile"] = enrichment["suggested_profile"]
    hint = _calibration_hint(enrichment, quality, calibrating)
    if hint:
        out["calibration_hint"] = hint
    return out
