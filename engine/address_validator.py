"""
Address validation and district/representative lookup.
Uses free Census Geocoder API (no key needed) with optional Google Civic API fallback.

Handles ALL edge cases:
- PO boxes, rural routes, military addresses (APO/FPO)
- US territories (PR, Guam, etc.) → non-voting delegates
- DC → non-voting delegate
- Vacant seats → staff still processes mail
- Multi-district ZIP codes → resolved by full address
- Invalid addresses → clear error messages
"""
import re
import asyncio
import json
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote, urlencode

import httpx
import yaml
from pathlib import Path

from config import (
    CENSUS_GEOCODER_URL, GOOGLE_CIVIC_API_KEY, GOOGLE_CIVIC_URL,
    LEGISLATORS_FILE, YAML_DIR
)

# ---- Data Models ----

@dataclass
class ValidatedAddress:
    """A USPS-validated address."""
    street: str
    street2: str = ""
    city: str = ""
    state: str = ""      # 2-letter postal abbreviation
    zip5: str = ""
    zip4: str = ""
    is_valid: bool = True
    standardized: str = ""  # Full standardized address string

    @property
    def zip_plus_4(self) -> str:
        if self.zip4:
            return f"{self.zip5}-{self.zip4}"
        return self.zip5

    @property
    def state_full(self) -> str:
        return STATE_ABBREV_TO_FULL.get(self.state, self.state)


@dataclass
class Representative:
    """A congressional representative."""
    bioguide: str
    name: str
    chamber: str          # "house" or "senate"
    state: str
    district: str = ""    # House district number, empty for Senate
    party: str = ""
    has_yaml: bool = False
    is_vacant: bool = False
    is_delegate: bool = False  # Non-voting delegate (DC, PR, etc.)


@dataclass
class AddressResult:
    """Complete result of address lookup."""
    address: ValidatedAddress
    representatives: list[Representative] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    lookup_method: str = ""  # "census", "google_civic", "zip_only"


# ---- Constants ----

STATE_ABBREV_TO_FULL = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "AS": "American Samoa", "GU": "Guam", "MP": "Northern Mariana Islands",
    "PR": "Puerto Rico", "VI": "U.S. Virgin Islands",
    "AA": "Armed Forces Americas", "AE": "Armed Forces Europe",
    "AP": "Armed Forces Pacific",
}

# States with only one House district (at-large)
AT_LARGE_STATES = {"AK", "DE", "ND", "SD", "VT", "WY"}

# States/territories with non-voting delegates only
DELEGATE_TERRITORIES = {"DC", "AS", "GU", "MP", "PR", "VI"}

# Military "state" codes → they vote in their home state
MILITARY_STATES = {"AA", "AE", "AP"}

# Vacant House seats as of May 2026
VACANT_SEATS = {
    "CA01", "CA14", "FL20", "GA13", "TX23"
}


# ---- Legislator Database (lazy-loaded) ----

_legislators_cache: Optional[dict] = None


def _load_legislators() -> dict:
    """Load and index all current legislators from the YAML file."""
    global _legislators_cache
    if _legislators_cache is not None:
        return _legislators_cache

    with open(LEGISLATORS_FILE) as f:
        data = yaml.safe_load(f)

    by_state_district: dict[str, dict] = {}  # "NY-10" → house member
    senate_by_state: dict[str, list] = {}     # "NY" → [senator1, senator2]

    for member in data:
        terms = member.get("terms", [])
        if not terms:
            continue

        # Find current term
        current_term = None
        for term in terms:
            if term.get("type") in ("rep", "sen"):
                end = term.get("end", "")
                if end >= "2026-01-01":  # Still in office
                    current_term = term
                    break

        if not current_term:
            continue

        bio = member["id"]["bioguide"]
        name_data = member.get("name", {})
        name = f"{name_data.get('first', '')} {name_data.get('last', '')}".strip()
        chamber = "senate" if current_term["type"] == "sen" else "house"
        state = current_term.get("state", "")
        district = str(current_term.get("district", ""))

        rep = {
            "bioguide": bio,
            "name": name,
            "chamber": chamber,
            "state": state,
            "district": district,
            "party": _get_party(terms),
        }

        if chamber == "senate":
            senate_by_state.setdefault(state, []).append(rep)
        elif chamber == "house":
            key = f"{state}-{district}" if district else state
            by_state_district[key] = rep

    _legislators_cache = {
        "house": by_state_district,
        "senate": senate_by_state,
    }
    return _legislators_cache


def _get_party(terms: list) -> str:
    """Get party from most recent term."""
    for term in reversed(terms):
        p = term.get("party", "")
        if p in ("Republican", "Democrat", "Independent"):
            return {"Republican": "R", "Democrat": "D", "Independent": "I"}.get(p, p)
    return ""


# ---- YAML Availability Check ----

def _bioguide_has_yaml(bioguide: str) -> bool:
    """Check if a YAML form definition exists for this bioguide ID."""
    yaml_path = YAML_DIR / f"{bioguide}.yaml"
    if not yaml_path.exists():
        return False
    # Check it's not a stub
    try:
        with open(yaml_path) as f:
            content = f.read()
        return "stubforcwc" not in content.lower()
    except Exception:
        return False


# ---- Main Address Validation ----

async def validate_and_lookup(address_raw: str) -> AddressResult:
    """
    Validate an address and find all congressional representatives.

    Args:
        address_raw: Free-form address string like "160 Water St, New York, NY 10038"

    Returns:
        AddressResult with validated address and list of representatives.
    """
    result = AddressResult(address=ValidatedAddress(street=address_raw))

    # Sanitize input
    address_raw = _sanitize_address(address_raw)
    if not address_raw:
        result.errors.append("No address provided.")
        return result

    # Try Census Geocoder first (free, no key)
    try:
        result = await _census_lookup(address_raw, result)
        if result.representatives:
            result.lookup_method = "census"
            return result
    except Exception as e:
        result.errors.append(f"Census lookup failed: {e}")

    # Try Google Civic API if configured
    if GOOGLE_CIVIC_API_KEY:
        try:
            result = await _google_civic_lookup(address_raw, result)
            if result.representatives:
                result.lookup_method = "google_civic"
                return result
        except Exception as e:
            result.errors.append(f"Google Civic lookup failed: {e}")

    # Fallback: parse ZIP + state manually and do basic lookup
    return _zip_only_lookup(address_raw, result)


def _parse_address_components(address_raw: str) -> dict:
    """
    Parse a free-form US address into {street, city, state, zip}.
    Handles formats like:
      "160 Water St, New York, NY 10038"
      "290 Broadway Suite 291, New York, NY 10007"
      "PO Box 123, Austin, TX 78701"
      "1600 Pennsylvania Ave NW, Washington, DC 20500"
    """
    result = {"street": "", "city": "", "state": "", "zip": ""}

    # Split by commas
    parts = [p.strip() for p in address_raw.split(",")]

    if len(parts) >= 3:
        # "street, city, state ZIP"
        result["street"] = parts[0]
        result["city"] = parts[1]

        # Handle remaining parts (could be address line 2)
        if len(parts) > 3:
            result["street"] += ", " + ", ".join(parts[1:-1])
            result["city"] = parts[-2].strip().split()[0] if parts[-2].strip() else ""

        # Last part: "state ZIP" — ONLY extract from the LAST component
        last = parts[-1].strip()
        state_zip = last.split()
        for token in state_zip:
            if re.match(r'^\d{5}(-\d{4})?$', token):
                result["zip"] = token.replace("-", "")[:5]
            elif len(token) == 2 and token.isalpha():
                result["state"] = token.upper()
    elif len(parts) == 2:
        # "street, state ZIP" or "city, state ZIP"
        result["street"] = parts[0]
        last = parts[-1].strip().split()
        for token in last:
            if re.match(r'^\d{5}', token):
                result["zip"] = token[:5]
            elif len(token) == 2 and token.isalpha():
                result["state"] = token.upper()
    else:
        # Single string - try to extract ZIP and state
        tokens = address_raw.split()
        for i, token in enumerate(tokens):
            zip_match = re.match(r'^(\d{5})(-\d{4})?$', token)
            if zip_match:
                result["zip"] = zip_match.group(1)
                # Look for state before ZIP
                if i >= 2 and len(tokens[i-2]) == 2 and tokens[i-2].isalpha():
                    result["state"] = tokens[i-2].upper()
                    result["city"] = " ".join(tokens[i-1:i])
                    result["street"] = " ".join(tokens[:i-2])
                elif i >= 1 and len(tokens[i-1]) == 2 and tokens[i-1].isalpha():
                    result["state"] = tokens[i-1].upper()
                    result["street"] = " ".join(tokens[:i-1])
                break

    return result



def _sanitize_address(addr: str) -> str:
    """Clean up address input."""
    if not addr or not addr.strip():
        return ""
    # Remove excessive whitespace
    addr = re.sub(r'\s+', ' ', addr.strip())
    # Remove special characters that break geocoding
    addr = re.sub(r'[^\w\s,.#\-\'&/]', '', addr)
    return addr


async def _census_lookup(address_raw: str, result: AddressResult) -> AddressResult:
    """
    Use U.S. Census Geocoder API (free, no auth required).
    Returns congressional district + state from address.
    """
    # Parse address into components
    parts = _parse_address_components(address_raw)
    street = parts["street"]
    city = parts["city"]
    state_code = parts["state"]
    zip_code = parts["zip"]

    params = {
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "Congressional Districts,State Legislative Districts Upper",
        "format": "json",
    }
    if street:
        params["street"] = street
    if city:
        params["city"] = city
    if state_code:
        params["state"] = state_code
    if zip_code:
        params["zip"] = zip_code

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(CENSUS_GEOCODER_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    result_data = data.get("result", {})
    address_matches = result_data.get("addressMatches", [])

    if not address_matches:
        result.errors.append("Address not found in Census database. Check spelling and try again.")
        return result

    match = address_matches[0]
    addr = match.get("matchedAddress", address_raw)
    coords = match.get("coordinates", {})

    # Parse validated address components
    components = match.get("addressComponents", {})
    result.address = ValidatedAddress(
        street=f"{components.get('fromAddress', '')} {components.get('streetName', '')} {components.get('suffixType', '')}".strip(),
        city=components.get("city", ""),
        state=components.get("state", ""),
        zip5=components.get("zip", ""),
        is_valid=True,
        standardized=match.get("matchedAddress", addr),
    )

    # Extract district from geographies - check multiple possible keys
    geos = match.get("geographies", {})
    # Census API uses session-specific keys like "119th Congressional Districts"
    cd = []
    for key in geos:
        if "Congressional District" in key:
            cd = geos[key]
            break

    # Also get state from Census response
    census_state = ""
    census_states = geos.get("States", [])
    if census_states:
        census_state = census_states[0].get("STUSAB", "")

    state = census_state or result.address.state.upper()

    if not state:
        result.errors.append("Could not determine state from address.")
        return result

    district_num = ""
    if cd:
        cd_data = cd[0]
        # Extract district: CD119 field is zero-padded ("01", "10", "00"=at-large)
        raw_district = str(
            cd_data.get("CD119", "") or
            cd_data.get("CD", "") or
            cd_data.get("BASENAME", "") or
            ""
        )

        # Strip leading zeros: "01"→"1", "10"→"10", "00"→"0"
        if raw_district.isdigit():
            district_num = str(int(raw_district))  # "01"→"1", "00"→"0"
        else:
            # Non-numeric: check for at-large text
            basename = str(cd_data.get("BASENAME", "")).strip()
            full_name = str(cd_data.get("NAME", "")).strip()
            geoid = str(cd_data.get("GEOID", "")).strip()

            if basename.upper() in ("AL", "00", "0"):
                district_num = "0"
            elif "at large" in full_name.lower() or "at large" in basename.lower():
                district_num = "0"
            elif len(geoid) == 4 and geoid.endswith("00"):
                district_num = "0"
            else:
                nums = re.findall(r'\d+', basename or full_name)
                if nums:
                    district_num = str(int(nums[0]))  # Strip leading zeros

    # Get representatives
    return _build_representative_list(result, state, district_num)


async def _google_civic_lookup(address_raw: str, result: AddressResult) -> AddressResult:
    """Use Google Civic Information API (requires API key)."""
    url = f"{GOOGLE_CIVIC_URL}?key={GOOGLE_CIVIC_API_KEY}&address={quote(address_raw)}&levels=country&roles=legislatorUpperBody&roles=legislatorLowerBody"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    # Parse normalized address
    normalized = data.get("normalizedInput", {})
    result.address = ValidatedAddress(
        street=normalized.get("line1", address_raw),
        city=normalized.get("city", ""),
        state=normalized.get("state", ""),
        zip5=normalized.get("zip", ""),
        is_valid=True,
    )

    # Parse offices and officials
    offices = data.get("offices", [])
    officials = data.get("officials", [])

    for office in offices:
        for idx in office.get("officialIndices", []):
            if idx >= len(officials):
                continue
            official = officials[idx]
            # Try to match with our legislator database
            name = official.get("name", "")
            result.representatives.append(Representative(
                bioguide="",  # Google Civic doesn't give bioguide IDs
                name=name,
                chamber="senate" if "Senat" in office.get("name", "") else "house",
                state=result.address.state,
                party=official.get("party", ""),
            ))

    # Cross-reference with our legislator DB to get bioguide IDs
    if result.address.state:
        result = _cross_reference_legislators(result)

    return result


def _build_representative_list(result: AddressResult, state: str, district_num: str) -> AddressResult:
    """Build the list of representatives from the legislator database."""
    db = _load_legislators()

    state = state.upper()

    # Territory check
    is_territory = state in DELEGATE_TERRITORIES
    is_military = state in MILITARY_STATES
    is_at_large = state in AT_LARGE_STATES

    # Handle military addresses - can't reliably determine home state
    if is_military:
        result.errors.append(
            "Military APO/FPO address detected. You must contact your representatives "
            "using your legal voting residence address (home of record), not your APO/FPO address."
        )
        return result

    # Handle territories - only non-voting delegates
    if is_territory:
        result.errors.append(
            f"{STATE_ABBREV_TO_FULL.get(state, state)} does not have voting representation "
            "in Congress. If a contact form exists for your delegate, it will be used."
        )
        # Look for delegate/commissioner in House (keyed just by state)
        house_rep = db["house"].get(state)
        if house_rep:
            result.representatives.append(_make_rep(house_rep, is_delegate=True))
        # Also try "STATE-0" format
        if not house_rep:
            house_rep = db["house"].get(f"{state}-0")
            if house_rep:
                result.representatives.append(_make_rep(house_rep, is_delegate=True))
        return result

    # Get House representative
    if district_num and district_num != "0":
        house_key = f"{state}-{district_num}"
        # Try exact match first
        house_rep = db["house"].get(house_key)
        # If not found, try "STATE-0D" format (e.g., CT-01 → CT-1 vs CT-01)
        if not house_rep and len(district_num) == 1:
            house_rep = db["house"].get(f"{state}-0{district_num}")
    elif is_at_large or district_num == "0":
        house_key = state
        # Try both "STATE" and "STATE-0"
        house_rep = db["house"].get(state) or db["house"].get(f"{state}-0")
    else:
        house_key = ""
        house_rep = None

    # Check vacancy
    vacancy_check = f"{state}{district_num}" if district_num else state
    is_vacant = vacancy_check in VACANT_SEATS

    if house_rep:
        result.representatives.append(_make_rep(house_rep, is_vacant=is_vacant))
    elif is_vacant:
        result.errors.append(
            f"House seat for {state}-{district_num} is currently vacant. "
            "The office may still accept constituent messages."
        )

    # Get Senators (every state has 2)
    senators = db["senate"].get(state, [])
    for sen in senators[:2]:
        result.representatives.append(_make_rep(sen))

    if len(senators) < 2 and not is_territory:
        result.errors.append(f"Could not find both senators for {state}.")

    return result


def _zip_only_lookup(address_raw: str, result: AddressResult) -> AddressResult:
    """Last-resort fallback: aggressively parse ZIP and state from raw address."""
    result.lookup_method = "zip_only"

    components = _parse_address_components(address_raw)
    zip5 = components["zip"]
    state = components["state"]

    # If no ZIP found, scan the whole string
    if not zip5:
        zip_match = re.search(r'\b(\d{5})(?:[-\s]?(\d{4}))?\b', address_raw)
        if zip_match:
            zip5 = zip_match.group(1)

    # If no state found, try multiple strategies
    if not state:
        state = _extract_state_aggressive(address_raw)

    # Still no state — try ZIP prefix lookup
    if not state and zip5:
        state = _state_from_zip(zip5)

    if not zip5 and not state:
        result.errors.append(
            "Could not parse your address. Please enter a full street address "
            "including city, state, and ZIP code (e.g. '160 Water St, New York, NY 10038')."
        )
        return result

    result.address = ValidatedAddress(
        street=address_raw, zip5=zip5 or "", zip4="", state=state or "",
        is_valid=False
    )

    if state and zip5:
        result.errors.append(
            "Address could not be fully verified, but we found your state and ZIP. "
            "Message delivery may fail if you are not a constituent of these representatives."
        )
    elif state:
        result.errors.append(
            "Found your state but not ZIP. Attempting delivery to your state's senators."
        )

    return _build_representative_list(result, state or "", "")


def _extract_state_aggressive(address_raw: str) -> str:
    """Try every possible way to extract a state from a raw address string."""
    upper = address_raw.upper()

    # 1. Look for 2-letter state codes as standalone tokens
    tokens = re.split(r'[\s,]+', upper)
    for token in tokens:
        token = token.strip('.,;:')
        if len(token) == 2 and token in STATE_ABBREV_TO_FULL:
            return token

    # 2. Look for full state names
    for abbr, full in STATE_ABBREV_TO_FULL.items():
        if full.upper() in upper:
            return abbr

    # 3. Try city name lookup
    return _guess_state_from_city(address_raw)

    result.errors.append("Could not determine state from address.")
    return result


def _guess_state_from_city(address: str) -> str:
    """Quick city-to-state guess for major cities."""
    city_map = {
        "new york": "NY", "brooklyn": "NY", "los angeles": "CA",
        "chicago": "IL", "houston": "TX", "phoenix": "AZ",
        "philadelphia": "PA", "san antonio": "TX", "san diego": "CA",
        "dallas": "TX", "austin": "TX", "boston": "MA", "seattle": "WA",
        "washington": "DC", "miami": "FL", "denver": "CO", "portland": "OR",
        "atlanta": "GA", "detroit": "MI", "nashville": "TN", "baltimore": "MD",
        "minneapolis": "MN", "tampa": "FL", "orlando": "FL", "st louis": "MO",
        "pittsburgh": "PA", "charlotte": "NC", "indianapolis": "IN",
        "columbus": "OH", "cleveland": "OH", "cincinnati": "OH",
        "kansas city": "MO", "las vegas": "NV", "milwaukee": "WI",
        "raleigh": "NC", "sacramento": "CA", "san jose": "CA",
        "san francisco": "CA", "oakland": "CA", "omaha": "NE",
        "albuquerque": "NM", "tucson": "AZ", "fresno": "CA",
        "long beach": "CA", "mesa": "AZ", "virginia beach": "VA",
        "colorado springs": "CO", "new orleans": "LA", "memphis": "TN",
        "louisville": "KY", "oklahoma city": "OK", "el paso": "TX",
        "fort worth": "TX", "jacksonville": "FL",
        "flushing": "NY", "queens": "NY", "bronx": "NY",
        "staten island": "NY", "long island": "NY",
    }
    addr_lower = address.lower()
    for city, st in city_map.items():
        if city in addr_lower:
            return st
    return ""


def _state_from_zip(zip5: str) -> str:
    """Look up state from first 3 digits of ZIP code (USPS data)."""
    if not zip5.isdigit():
        return ""
    z = int(zip5[:3])
    ranges = [
        ("MA", 10, 27), ("RI", 28, 29), ("NH", 30, 38), ("ME", 39, 49),
        ("VT", 50, 59), ("CT", 60, 69), ("NJ", 70, 89),
        ("NY", 100, 149), ("PA", 150, 196), ("DE", 197, 199),
        ("DC", 200, 205), ("MD", 206, 219), ("VA", 220, 246),
        ("WV", 247, 268), ("NC", 270, 289), ("SC", 290, 299),
        ("GA", 300, 319), ("FL", 320, 349), ("AL", 350, 369),
        ("TN", 370, 385), ("MS", 386, 397), ("KY", 400, 427),
        ("OH", 430, 459), ("IN", 460, 479), ("MI", 480, 499),
        ("IA", 500, 528), ("WI", 530, 549), ("MN", 550, 567),
        ("SD", 570, 577), ("ND", 580, 588), ("MT", 590, 599),
        ("IL", 600, 629), ("MO", 630, 658), ("KS", 660, 679),
        ("NE", 680, 693), ("LA", 700, 714), ("AR", 716, 729),
        ("OK", 730, 749), ("TX", 750, 799), ("CO", 800, 819),
        ("WY", 820, 831), ("ID", 832, 838), ("UT", 840, 847),
        ("AZ", 850, 865), ("NM", 870, 884), ("NV", 889, 898),
        ("CA", 900, 966), ("HI", 967, 968), ("OR", 970, 979),
        ("WA", 980, 994), ("AK", 995, 999),
    ]
    for st, lo, hi in ranges:
        if lo <= z <= hi:
            return st
    return ""



def _make_rep(data: dict, is_vacant: bool = False, is_delegate: bool = False) -> Representative:
    """Create a Representative from legislator DB entry."""
    bio = data["bioguide"]
    return Representative(
        bioguide=bio,
        name=data["name"],
        chamber=data["chamber"],
        state=data["state"],
        district=data.get("district", ""),
        party=data.get("party", ""),
        has_yaml=_bioguide_has_yaml(bio),
        is_vacant=is_vacant,
        is_delegate=is_delegate,
    )


def _cross_reference_legislators(result: AddressResult) -> AddressResult:
    """Match Google Civic results to our legislator database for bioguide IDs."""
    db = _load_legislators()
    state = result.address.state.upper()

    all_known = []
    for key, rep_data in db["house"].items():
        if key.startswith(state + "-") or key == state:
            all_known.append(_make_rep(rep_data))
    for sen_data in db["senate"].get(state, []):
        all_known.append(_make_rep(sen_data))

    # Match by name similarity
    matched = []
    for known in all_known:
        last_name = known.name.split()[-1].lower()
        for google_rep in result.representatives:
            if last_name in google_rep.name.lower():
                google_rep.bioguide = known.bioguide
                google_rep.has_yaml = known.has_yaml
                if known.chamber == "senate":
                    google_rep.chamber = "senate"
                matched.append(known.bioguide)

    return result


# ---- Convenience Functions ----

async def get_representatives(address: str) -> list[Representative]:
    """Quick lookup: address → list of representatives."""
    result = await validate_and_lookup(address)
    return result.representatives


# ---- Validation Helpers ----

def validate_email(email: str) -> bool:
    """Basic email validation."""
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email))


def validate_phone(phone: str) -> bool:
    """Basic phone validation (US format)."""
    digits = re.sub(r'\D', '', phone)
    return len(digits) == 10 or len(digits) == 11
