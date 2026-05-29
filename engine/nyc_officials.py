"""
NYC elected official data model and lookup functions.
Loads nyc_officials.yaml and provides get_officials_for_address().
"""
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import OFFICIALS_FILE, COUNTY_BOROUGH_FILE

# Cache loaded data
_officials_data: Optional[dict] = None
_county_borough_map: Optional[dict] = None


def _load_officials() -> dict:
    global _officials_data
    if _officials_data is None:
        with open(OFFICIALS_FILE) as f:
            _officials_data = yaml.safe_load(f)
    return _officials_data


def _load_county_borough_map() -> dict:
    global _county_borough_map
    if _county_borough_map is None:
        with open(COUNTY_BOROUGH_FILE) as f:
            _county_borough_map = yaml.safe_load(f)
    return _county_borough_map


@dataclass
class NYCOfficial:
    """Represents one elected official with contact info."""
    title: str
    name: str
    party: str = ""
    contact_method: str = "email"  # "email" or "form"
    email: str = ""
    form_key: str = ""
    url: str = ""
    phone: str = ""
    jurisdiction: str = ""  # "citywide", "borough", "district", "statewide"
    note: str = ""


def get_council_member(district: int) -> Optional[NYCOfficial]:
    """Look up a City Council member by district number (1-51)."""
    data = _load_officials()
    council = data.get("council", {})
    member = council.get(district)
    if not member:
        return None
    return NYCOfficial(
        title=f"City Council Member, District {district}",
        name=member["name"],
        party=member.get("party", ""),
        contact_method=member.get("contact_method", "email"),
        email=member.get("email", ""),
        phone=member.get("phone", ""),
        jurisdiction="district",
        note=member.get("note", ""),
    )


def get_borough_officials(borough_code: str) -> list[NYCOfficial]:
    """Get Borough President and District Attorney for a borough."""
    data = _load_officials()
    boroughs = data.get("boroughs", {})
    boro = boroughs.get(borough_code)
    if not boro:
        return []

    officials = []

    bp = boro.get("borough_president", {})
    if bp:
        officials.append(NYCOfficial(
            title=f"{boro['name']} Borough President",
            name=bp["name"],
            party=bp.get("party", ""),
            contact_method=bp.get("contact_method", "email"),
            email=bp.get("email", ""),
            form_key=bp.get("form_key", ""),
            url=bp.get("url", ""),
            phone=bp.get("phone", ""),
            jurisdiction="borough",
            note=bp.get("note", ""),
        ))

    da = boro.get("district_attorney", {})
    if da:
        officials.append(NYCOfficial(
            title=f"{boro['name']} District Attorney",
            name=da["name"],
            party=da.get("party", ""),
            contact_method=da.get("contact_method", "email"),
            email=da.get("email", ""),
            url=da.get("url", ""),
            phone=da.get("phone", ""),
            jurisdiction="borough",
        ))

    return officials


def get_citywide_officials() -> list[NYCOfficial]:
    """Get Mayor, Public Advocate, and Comptroller."""
    data = _load_officials()
    officials = []
    for cw in data.get("citywide", []):
        officials.append(NYCOfficial(
            title=cw["title"],
            name=cw["name"],
            party=cw.get("party", ""),
            contact_method=cw.get("contact_method", "email"),
            email=cw.get("email", ""),
            form_key=cw.get("form_key", ""),
            url=cw.get("url", ""),
            phone=cw.get("phone", ""),
            jurisdiction="citywide",
        ))
    return officials


def get_statewide_officials() -> list[NYCOfficial]:
    """Get Governor, NYS AG, and NYS Comptroller."""
    data = _load_officials()
    officials = []
    for sw in data.get("state_wide", []):
        officials.append(NYCOfficial(
            title=sw["title"],
            name=sw["name"],
            party=sw.get("party", ""),
            contact_method=sw.get("contact_method", "email"),
            email=sw.get("email", ""),
            form_key=sw.get("form_key", ""),
            url=sw.get("url", ""),
            phone=sw.get("phone", ""),
            jurisdiction="statewide",
        ))
    return officials


def get_state_senator(district: int) -> Optional[NYCOfficial]:
    """Look up a NYS Senator by district number."""
    data = _load_officials()
    senate = data.get("state_senate", {})
    member = senate.get(district)
    if not member:
        return None
    return NYCOfficial(
        title=f"NYS Senator, District {district}",
        name=member["name"],
        party=member.get("party", ""),
        contact_method="form",
        form_key="nys_senate_template",
        email=member.get("email", ""),
        url=member.get("url", f"https://www.nysenate.gov/senators-district/{district}"),
        phone=member.get("phone", ""),
        jurisdiction="district",
        note=member.get("note", ""),
    )


def get_state_assembly_member(district: int) -> Optional[NYCOfficial]:
    """Look up a NYS Assembly member by district number."""
    data = _load_officials()
    assembly = data.get("state_assembly", {})
    member = assembly.get(district)
    if not member:
        return None
    return NYCOfficial(
        title=f"NYS Assembly Member, District {district}",
        name=member["name"],
        party=member.get("party", ""),
        contact_method="form",
        form_key="nys_assembly_template",
        email=member.get("email", ""),
        url=f"https://assembly.state.ny.us/mem/?ad={district}",
        phone=member.get("phone", ""),
        jurisdiction="district",
        note=member.get("note", ""),
    )


def get_officials_for_address(
    council_district: int,
    borough_code: str = "",
    state_senate_district: int = 0,
    state_assembly_district: int = 0,
) -> list[NYCOfficial]:
    """
    Return ALL elected officials for a given address.

    Returns up to 11 officials:
    - 3 citywide (Mayor, Public Advocate, Comptroller)
    - 1 City Council member
    - 2 borough-level (Borough President, District Attorney)
    - 3 statewide (Governor, NYS AG, NYS Comptroller)
    - 1 NYS Senator
    - 1 NYS Assembly member
    """
    officials = []

    # Citywide
    officials.extend(get_citywide_officials())

    # Council member
    cm = get_council_member(council_district)
    if cm:
        officials.append(cm)

    # Borough-level
    if borough_code:
        officials.extend(get_borough_officials(borough_code))

    # Statewide
    officials.extend(get_statewide_officials())

    # State Senate
    if state_senate_district:
        sen = get_state_senator(state_senate_district)
        if sen:
            officials.append(sen)

    # State Assembly
    if state_assembly_district:
        am = get_state_assembly_member(state_assembly_district)
        if am:
            officials.append(am)

    return officials


def get_borough_code_for_fips(fips: str) -> str:
    """Convert county FIPS code to borough code (e.g., '061' -> 'manhattan')."""
    county_map = _load_county_borough_map()
    entry = county_map.get(fips, {})
    return entry.get("borough_code", "")
