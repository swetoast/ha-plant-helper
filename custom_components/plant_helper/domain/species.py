from __future__ import annotations
import re, unicodedata
from typing import Any, Mapping

def normalize_species_key(value: str) -> str:
    value=unicodedata.normalize("NFKC",value).casefold().strip()
    value=re.sub(r"[^\w\s-]"," ",value)
    return re.sub(r"[\s_-]+"," ",value).strip()

def classify_match(query: str, candidate: Mapping[str,Any], *, known_family: str | None=None) -> str:
    q=normalize_species_key(query)
    scientific=normalize_species_key(str(candidate.get("scientific_name", "")))
    common=normalize_species_key(str(candidate.get("common_name", "")))
    synonyms={normalize_species_key(str(v)) for v in candidate.get("synonyms",[]) if v}
    if q and q in {scientific,common,*synonyms}: return "confirmed"
    qtokens=set(q.split()); ctokens=set(scientific.split())|set(common.split())
    genus_agreement=bool(qtokens and scientific and next(iter(qtokens),"")==scientific.split()[0])
    family_agreement=known_family is not None and normalize_species_key(known_family)==normalize_species_key(str(candidate.get("family","")))
    overlap=len(qtokens&ctokens)/max(1,len(qtokens))
    if overlap>=0.5 and (genus_agreement or family_agreement): return "strong"
    if overlap>0: return "ambiguous"
    return "rejected"

FIELD_OWNERS={
    "scientific_name":("trefle","inaturalist","perenual"),
    "family":("trefle","inaturalist","perenual"),
    "genus":("trefle","inaturalist","perenual"),
    "common_name":("perenual","trefle","inaturalist"),
    "watering_category":("perenual","trefle"),
    "sunlight_requirements":("perenual","trefle"),
    "image_url":("inaturalist","perenual","trefle"),
}

def merge_provider_fields(results: Mapping[str,Mapping[str,Any]]) -> dict[str,Any]:
    merged={}; provenance={}
    all_fields=set().union(*(r.keys() for r in results.values())) if results else set()
    for field in all_fields:
        order=FIELD_OWNERS.get(field,tuple(results))
        for provider in order:
            value=results.get(provider,{}).get(field)
            if value not in (None,"",[],{}):
                merged[field]=value; provenance[field]=provider; break
    if provenance: merged["provenance"]=provenance
    return merged
