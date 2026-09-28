from drone_sim.schema_mapping import Conversion, FieldMapping, MappingCache, apply_mapping
from drone_sim.schema_mapping import route_from_coordinates


def test_unfamiliar_vendor_key_is_mapped_deterministically_with_anchor() -> None:
    document = {"AUW_g": 4200, "wind_kmh": 36}
    value, anchor = apply_mapping(document, FieldMapping(source_pointer="/AUW_g", canonical_path="/vehicle/mass_kg", conversion=Conversion.GRAMS_TO_KG))
    assert value == 4.2
    assert anchor == "/AUW_g"


def test_mapping_is_cached_by_schema_not_values() -> None:
    cache = MappingCache()
    mapping = FieldMapping(source_pointer="/AUW_g", canonical_path="/vehicle/mass_kg", conversion=Conversion.GRAMS_TO_KG)
    cache.put({"AUW_g": 1}, (mapping,))
    assert cache.get({"AUW_g": 999}) == (mapping,)


def test_kml_coordinates_become_canonical_drone_route() -> None:
    route = route_from_coordinates(((151.0, -33.0, 20), (151.1, -33.1, 25)))
    assert route.points[0].position.latitude_deg == -33.0
    assert route.points[1].position.altitude_m == 25
