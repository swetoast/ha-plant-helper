from plant_helper_domain.species import normalize_species_key,classify_match,merge_provider_fields

def test_normalize_species_key():
    assert normalize_species_key("  Dracaena_trifasciata!! ")=="dracaena trifasciata"

def test_match_classes():
    exact={"scientific_name":"Dracaena trifasciata","common_name":"Snake plant","synonyms":["Sansevieria trifasciata"],"family":"Asparagaceae"}
    assert classify_match("snake plant",exact)=="confirmed"
    assert classify_match("Dracaena trifasciata",exact)=="confirmed"
    assert classify_match("Dracaena green",exact,known_family="Asparagaceae")=="strong"
    assert classify_match("plant",exact)=="ambiguous"
    assert classify_match("rose",exact)=="rejected"

def test_field_owners_and_provenance():
    merged=merge_provider_fields({"trefle":{"scientific_name":"Dracaena trifasciata","image_url":"t"},"perenual":{"common_name":"Snake plant","watering_category":"minimum","image_url":"p"},"inaturalist":{"image_url":"i"}})
    assert merged["scientific_name"]=="Dracaena trifasciata"
    assert merged["common_name"]=="Snake plant"
    assert merged["image_url"]=="i"
    assert merged["provenance"]["image_url"]=="inaturalist"
