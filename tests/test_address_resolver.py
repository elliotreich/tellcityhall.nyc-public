"""Tests for address resolution: parsing, Census API, point-in-polygon."""
import pytest
import asyncio

from engine.nyc_address_resolver import (
    _parse_address_components,
    _extract_county_fips,
    _extract_coordinates,
    _extract_district_layers,
    _load_council_geojson,
    _point_in_council_district,
    validate_and_resolve,
)


class TestParseAddressComponents:
    def test_standard_nyc_format(self):
        result = _parse_address_components("160 Water St, New York, NY 10038")
        assert result["street"] == "160 Water St"
        assert result["city"] == "New York"
        assert result["state"] == "NY"
        assert result["zip"] == "10038"

    def test_brooklyn_format(self):
        result = _parse_address_components("350 Jay Street, Brooklyn, NY 11201")
        assert result["street"] == "350 Jay Street"
        assert result["city"] == "Brooklyn"
        assert result["zip"] == "11201"

    def test_queens_format(self):
        result = _parse_address_components("37-06 82nd St, Jackson Heights, NY 11372")
        assert result["street"] == "37-06 82nd St"
        assert result["city"] == "Jackson Heights"
        assert result["zip"] == "11372"

    def test_no_comma_fallback(self):
        """Fallback regex extraction when no comma separators."""
        result = _parse_address_components("350 Jay Street Brooklyn NY 11201")
        assert result["zip"] == "11201"
        assert result["state"] == "NY"

    def test_empty_input(self):
        result = _parse_address_components("")
        assert result == {"street": "", "city": "", "state": "", "zip": ""}

    def test_none_input(self):
        result = _parse_address_components(None)
        assert result == {"street": "", "city": "", "state": "", "zip": ""}


class TestExtractCountyFips:
    def test_extracts_county_fips(self):
        data = {
            "result": {
                "addressMatches": [{
                    "geographies": {
                        "Counties": [{"COUNTY": "047"}]
                    }
                }]
            }
        }
        assert _extract_county_fips(data) == "047"

    def test_no_matches_returns_empty(self):
        assert _extract_county_fips({"result": {"addressMatches": []}}) == ""

    def test_no_counties_returns_empty(self):
        data = {
            "result": {
                "addressMatches": [{"geographies": {}}]
            }
        }
        assert _extract_county_fips(data) == ""


class TestExtractCoordinates:
    def test_extracts_lat_lon(self):
        data = {
            "result": {
                "addressMatches": [{
                    "coordinates": {"x": -73.987, "y": 40.693}
                }]
            }
        }
        lat, lon = _extract_coordinates(data)
        assert lat == 40.693
        assert lon == -73.987

    def test_no_matches_returns_zeros(self):
        lat, lon = _extract_coordinates({"result": {"addressMatches": []}})
        assert lat == 0.0
        assert lon == 0.0

    def test_missing_coordinates_returns_zeros(self):
        data = {
            "result": {
                "addressMatches": [{}]
            }
        }
        lat, lon = _extract_coordinates(data)
        assert lat == 0.0
        assert lon == 0.0


class TestExtractDistrictLayers:
    def test_extracts_senate_and_assembly(self):
        data = {
            "result": {
                "addressMatches": [{
                    "geographies": {
                        "2024 State Legislative Districts - Upper": [
                            {"GEOID": "36026", "NAME": "State Senate District 26"}
                        ],
                        "2024 State Legislative Districts - Lower": [
                            {"GEOID": "36052", "NAME": "Assembly District 52"}
                        ]
                    }
                }]
            }
        }
        senate, assembly = _extract_district_layers(data)
        assert senate == 26
        assert assembly == 52

    def test_no_matches_returns_zeros(self):
        senate, assembly = _extract_district_layers({"result": {"addressMatches": []}})
        assert senate == 0
        assert assembly == 0

    def test_missing_geographies_returns_zeros(self):
        data = {"result": {"addressMatches": [{}]}}
        senate, assembly = _extract_district_layers(data)
        assert senate == 0
        assert assembly == 0


class TestCouncilGeojson:
    def test_loads_and_indexes(self):
        districts = _load_council_geojson()
        assert len(districts) == 51, f"Expected 51 council districts, got {len(districts)}"
        assert 1 in districts
        assert 51 in districts
        assert "geometry" in districts[1]

    def test_returns_same_cache(self):
        d1 = _load_council_geojson()
        d2 = _load_council_geojson()
        assert d1 is d2

    def test_point_in_district(self):
        # Downtown Brooklyn → District 33
        dist = _point_in_council_district(-73.987, 40.693)
        assert dist == 33

    def test_point_returns_zero_for_invalid(self):
        assert _point_in_council_district(0, 0) == 0
        assert _point_in_council_district(None, None) == 0


class TestValidateAndResolve:
    """Integration tests — hit the live Census API."""

    def test_valid_brooklyn_address(self):
        async def _test():
            result = await validate_and_resolve("350 Jay Street, Brooklyn, NY 11201")
            assert result.address.is_valid
            assert result.borough_code == "brooklyn"
            assert result.council_district == 33
            assert result.state_senate_district == 26
            assert result.state_assembly_district == 52
        asyncio.run(_test())

    def test_valid_manhattan_address(self):
        async def _test():
            result = await validate_and_resolve("160 Water St, New York, NY 10038")
            assert result.address.is_valid
            assert result.borough_code == "manhattan"
            assert result.council_district == 1
            assert result.state_senate_district > 0
            assert result.state_assembly_district > 0
        asyncio.run(_test())

    def test_non_nyc_address_rejected(self):
        async def _test():
            result = await validate_and_resolve("1600 Pennsylvania Ave, Washington, DC 20500")
            assert not result.address.is_valid
            assert len(result.errors) > 0
            assert "New York City" in result.errors[0]
        asyncio.run(_test())

    def test_empty_address(self):
        async def _test():
            result = await validate_and_resolve("")
            assert not result.address.is_valid
            assert len(result.errors) > 0
        asyncio.run(_test())
