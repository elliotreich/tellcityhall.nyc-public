"""
NYC address resolver using Census Geocoder + point-in-polygon for City Council districts.
Also extracts state legislative districts from Census data.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx
import yaml
from shapely.geometry import shape, Point

from config import (
    CENSUS_GEOCODER_URL,
    CENSUS_AUTOCOMPLETE_URL,
    NYC_COUNTY_FIPS,
    COUNCIL_GEOJSON,
)


@dataclass
class ValidatedAddress:
    """Standardized address components."""
    street: str = ""
    city: str = ""
    state: str = "NY"
    zip5: str = ""
    zip4: str = ""
    is_valid: bool = False
    standardized: str = ""
    county_fips: str = ""
    lat: float = 0.0
    lon: float = 0.0


@dataclass
class AddressResult:
    """Result of address validation + district resolution."""
    address: ValidatedAddress = field(default_factory=ValidatedAddress)
    borough_code: str = ""          # "manhattan", "bronx", etc.
    council_district: int = 0
    state_senate_district: int = 0
    state_assembly_district: int = 0
    lookup_method: str = ""         # "census", "zip_only"
    errors: list[str] = field(default_factory=list)


# Cache for GeoJSON polygons
_council_districts: Optional[dict] = None


def _load_council_geojson() -> dict:
    """Load and index NYC Council district GeoJSON."""
    global _council_districts
    if _council_districts is None:
        with open(COUNCIL_GEOJSON) as f:
            data = json.load(f)
        # Index by district number for fast lookup
        _council_districts = {}
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            dist_num = props.get("CounDist") or props.get("council_district") or props.get("district")
            if dist_num is not None:
                _council_districts[int(dist_num)] = feature
    return _council_districts


async def autocomplete(query: str) -> list[dict]:
    """Get address autocomplete suggestions from Census Geocoder."""
    params = {
        "address": query,
        "benchmark": "Public_AR_Current",
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(CENSUS_AUTOCOMPLETE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            suggestions = []
            address_matches = data.get("result", {}).get("addressMatches", [])
            for match in address_matches[:8]:
                suggestions.append({
                    "address": match.get("matchedAddress", ""),
                    "city": match.get("addressComponents", {}).get("city", ""),
                    "state": match.get("addressComponents", {}).get("state", ""),
                    "zip": match.get("addressComponents", {}).get("zip", ""),
                })
            return suggestions
        except Exception:
            return []


def _extract_county_fips(census_data: dict) -> str:
    """Extract county FIPS code from Census Geocoder response."""
    try:
        # Geographies are at the match level, not the result level
        matches = census_data.get("result", {}).get("addressMatches", [])
        if matches:
            geographies = matches[0].get("geographies", {})
            counties = geographies.get("Counties", [])
            if counties:
                return counties[0].get("COUNTY", "")
    except Exception:
        pass
    return ""


def _extract_district_layers(census_data: dict) -> tuple[int, int]:
    """Extract state legislative districts from Census Geocoder response.
    Returns (senate_district, assembly_district).

    The Census API returns these with a vintage-prefixed key (e.g.
    "2024 State Legislative Districts - Upper"). GEOID is 36 + district number.
    """
    senate = 0
    assembly = 0
    try:
        matches = census_data.get("result", {}).get("addressMatches", [])
        if not matches:
            return senate, assembly
        geographies = matches[0].get("geographies", {})

        # State Legislative Districts - Upper (Senate) — key varies by vintage
        upper = None
        for k in geographies:
            if "Legislative Districts" in k and "Upper" in k:
                upper = geographies[k]
                break
        if upper and upper[0].get("GEOID", "").startswith("36"):
            senate = int(upper[0]["GEOID"][2:])

        # State Legislative Districts - Lower (Assembly)
        lower = None
        for k in geographies:
            if "Legislative Districts" in k and "Lower" in k:
                lower = geographies[k]
                break
        if lower and lower[0].get("GEOID", "").startswith("36"):
            assembly = int(lower[0]["GEOID"][2:])

    except Exception:
        pass

    return senate, assembly


def _extract_coordinates(census_data: dict) -> tuple[float, float]:
    """Extract lat/lon from Census Geocoder response."""
    try:
        # Coordinates are at the match level, not the result level
        matches = census_data.get("result", {}).get("addressMatches", [])
        if matches:
            coords = matches[0].get("coordinates", {})
            return float(coords.get("y", 0)), float(coords.get("x", 0))
    except Exception:
        pass
    return 0.0, 0.0


def _extract_address_components(census_data: dict) -> dict:
    """Extract address components from Census Geocoder response."""
    try:
        match = census_data.get("result", {}).get("addressMatches", [{}])[0]
        components = match.get("addressComponents", {})
        return {
            "street": components.get("streetName", ""),
            "city": components.get("city", ""),
            "state": components.get("state", "NY"),
            "zip5": components.get("zip", ""),
            "standardized": match.get("matchedAddress", ""),
        }
    except Exception:
        return {"standardized": ""}


def _point_in_council_district(lon: float, lat: float) -> int:
    """Find which NYC Council district a point falls in using GeoJSON.
    Returns district number or 0 if not found.
    """
    if not lon or not lat:
        return 0

    districts = _load_council_geojson()
    if not districts:
        return 0

    point = Point(lon, lat)

    for dist_num, feature in districts.items():
        try:
            geom = shape(feature["geometry"])
            # Add a small buffer to handle boundary edge cases
            if geom.buffer(0.0001).contains(point) or geom.contains(point):
                return dist_num
        except Exception:
            continue

    # Fallback: find nearest district centroid
    min_dist = float("inf")
    nearest = 0
    for dist_num, feature in districts.items():
        try:
            geom = shape(feature["geometry"])
            centroid = geom.centroid
            d = point.distance(centroid)
            if d < min_dist:
                min_dist = d
                nearest = dist_num
        except Exception:
            continue

    return nearest


def _parse_address_components(address_raw: str) -> dict:
    """
    Parse a free-form US address into {street, city, state, zip}.
    Handles formats like:
      "160 Water St, New York, NY 10038"
      "350 Jay Street, Brooklyn, NY 11201"
    """
    result = {"street": "", "city": "", "state": "", "zip": ""}
    if not address_raw:
        return result

    text = address_raw.strip().rstrip(",")

    # Try "Street, City, State ZIP" format
    # Split by comma
    parts = [p.strip() for p in text.split(",")]

    if len(parts) >= 3:
        result["street"] = parts[0]
        result["city"] = parts[1]
        # State and ZIP from last part: "NY 10038"
        state_zip = parts[-1].strip().split()
        if len(state_zip) >= 2:
            result["state"] = state_zip[0]
            result["zip"] = state_zip[1][:5]
        elif len(state_zip) == 1 and len(state_zip[0]) == 2:
            result["state"] = state_zip[0]
    elif len(parts) == 2:
        result["street"] = parts[0]
        state_zip = parts[1].strip().split()
        if len(state_zip) >= 2:
            result["state"] = state_zip[0]
            result["zip"] = state_zip[1][:5]

    # Fallback: extract ZIP and state via regex
    if not result["zip"]:
        zip_match = re.search(r"(\d{5})", text)
        if zip_match:
            result["zip"] = zip_match.group(1)
    if not result["state"]:
        state_match = re.search(r"\b(NY|NJ|CT|PA)\b", text)
        if state_match:
            result["state"] = state_match.group(1)
    if not result["city"]:
        # Try to extract city between street and state
        for borough_city in ["New York", "Brooklyn", "Bronx", "Queens", "Staten Island",
                              "Manhattan", "Long Island City", "Astoria", "Flushing",
                              "Jamaica", "Harlem"]:
            if borough_city.lower() in text.lower():
                result["city"] = borough_city
                break

    return result


async def validate_and_resolve(address_raw: str) -> AddressResult:
    """
    Validate an address and resolve all districts.

    1. Census Geocoder → coordinates + county FIPS + state leg districts
    2. County FIPS → borough code
    3. Point-in-polygon → City Council district
    """
    result = AddressResult()

    if not address_raw or not address_raw.strip():
        result.errors.append("Please enter an address.")
        return result

    # Query Census Geocoder for geography layers
    # Parse address into components for structured lookup
    parts = _parse_address_components(address_raw)
    params = {
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "Counties,2024 State Legislative Districts - Upper,2024 State Legislative Districts - Lower",
        "format": "json",
    }
    if parts.get("street"):
        params["street"] = parts["street"]
    if parts.get("city"):
        params["city"] = parts["city"]
    if parts.get("state"):
        params["state"] = parts["state"]
    if parts.get("zip"):
        params["zip"] = parts["zip"]
    # Fallback: use one-line address if parsing failed
    if not parts.get("street") and not parts.get("city"):
        params["address"] = address_raw.strip()

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(CENSUS_GEOCODER_URL, params=params)
            resp.raise_for_status()
            geo_data = resp.json()

            # Check if address matched
            matches = geo_data.get("result", {}).get("addressMatches", [])
            if not matches:
                result.errors.append("Address not found. Please check and try again.")
                return result

            result.lookup_method = "census"

        except httpx.HTTPError:
            result.errors.append("Address lookup service unavailable. Please try again.")
            return result
        except Exception as e:
            result.errors.append(f"Address lookup error: {e}")
            return result

    # Extract county FIPS
    county_fips = _extract_county_fips(geo_data)
    result.address.county_fips = county_fips

    # Check if address is in NYC
    if county_fips not in NYC_COUNTY_FIPS:
        # Try fallback: check if city contains a borough name
        components = _extract_address_components(geo_data)
        city = components.get("city", "").lower()
        borough_cities = {
            "new york": "061", "manhattan": "061",
            "brooklyn": "047",
            "bronx": "005",
            "queens": "081", "jamaica": "081", "flushing": "081",
            "long island city": "081", "astoria": "081",
            "staten island": "085",
        }
        found_fips = ""
        for city_name, fips in borough_cities.items():
            if city_name in city or city_name in address_raw.lower():
                found_fips = fips
                break

        if found_fips in NYC_COUNTY_FIPS:
            county_fips = found_fips
            result.address.county_fips = county_fips
        else:
            result.errors.append(
                "This tool is for New York City residents only. "
                "The address you entered appears to be outside NYC."
            )
            return result

    # Map county FIPS to borough code
    from engine.nyc_officials import get_borough_code_for_fips
    result.borough_code = get_borough_code_for_fips(county_fips)

    # Extract coordinates
    result.address.lat, result.address.lon = _extract_coordinates(geo_data)

    # Extract address components
    components = _extract_address_components(geo_data)
    result.address.street = components.get("street", "")
    result.address.city = components.get("city", "")
    result.address.state = components.get("state", "NY")
    result.address.zip5 = components.get("zip5", "")
    result.address.standardized = components.get("standardized", address_raw)
    result.address.is_valid = True

    # Resolve City Council district via point-in-polygon
    result.council_district = _point_in_council_district(
        result.address.lon, result.address.lat
    )

    # Extract state legislative districts from Census data
    result.state_senate_district, result.state_assembly_district = (
        _extract_district_layers(geo_data)
    )

    if result.council_district == 0:
        result.errors.append("Could not determine City Council district.")

    return result
