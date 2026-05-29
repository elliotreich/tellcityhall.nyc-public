"""Tests for official lookup and data integrity."""
import pytest

from engine.nyc_officials import get_officials_for_address, NYCOfficial, _load_officials


class TestLoadOfficials:
    def test_loads_all_categories(self):
        data = _load_officials()
        categories = ["citywide", "council", "boroughs", "state_wide",
                       "state_senate", "state_assembly"]
        for cat in categories:
            assert cat in data, f"Missing category: {cat}"

    def test_51_council_members(self):
        data = _load_officials()
        council = data.get("council", {})
        assert len(council) == 51, f"Expected 51 council members, got {len(council)}"

    def test_5_boroughs(self):
        data = _load_officials()
        boroughs = data.get("boroughs", {})
        expected = ["manhattan", "bronx", "brooklyn", "queens", "staten_island"]
        for b in expected:
            assert b in boroughs, f"Missing borough: {b}"

    def test_council_emails_exist(self):
        """All council members should have an email address."""
        data = _load_officials()
        for dist_num, member in data["council"].items():
            assert member.get("email"), f"Council district {dist_num} has no email"

    def test_3_citywide(self):
        data = _load_officials()
        assert len(data["citywide"]) == 3

    def test_3_statewide(self):
        data = _load_officials()
        assert len(data["state_wide"]) == 3


class TestGetOfficialsForAddress:
    def test_returns_11_officials(self):
        officials = get_officials_for_address(
            council_district=33,
            borough_code="brooklyn",
            state_senate_district=26,
            state_assembly_district=52,
        )
        assert len(officials) == 11, f"Expected 11 officials, got {len(officials)}"

    def test_citywide_officials_present(self):
        officials = get_officials_for_address(33, "brooklyn", 26, 52)
        titles = {o.title for o in officials}
        assert "Mayor of New York City" in titles
        assert "Public Advocate" in titles
        assert "Comptroller" in titles

    def test_council_member_present(self):
        officials = get_officials_for_address(33, "brooklyn", 26, 52)
        council = [o for o in officials if "Council Member" in o.title]
        assert len(council) == 1
        assert "33" in council[0].title

    def test_borough_officials_present(self):
        officials = get_officials_for_address(33, "brooklyn", 26, 52)
        bp = [o for o in officials if "Borough President" in o.title]
        da = [o for o in officials if "District Attorney" in o.title]
        assert len(bp) == 1
        assert len(da) == 1

    def test_statewide_officials_present(self):
        officials = get_officials_for_address(33, "brooklyn", 26, 52)
        titles = {o.title for o in officials}
        assert "Governor of New York" in titles
        assert "Attorney General of New York" in titles
        assert "New York State Comptroller" in titles

    def test_state_legislators_present(self):
        officials = get_officials_for_address(33, "brooklyn", 26, 52)
        senate = [o for o in officials if "NYS Senator" in o.title]
        assembly = [o for o in officials if "NYS Assembly" in o.title]
        assert len(senate) == 1
        assert len(assembly) == 1
        assert "26" in senate[0].title
        assert "52" in assembly[0].title

    def test_invalid_district_gets_citywide_and_statewide(self):
        """Even with invalid districts, citywide and statewide officials resolve."""
        officials = get_officials_for_address(999, "unknown", 999, 999)
        citywide_and_statewide = [o for o in officials
                                  if o.jurisdiction in ("citywide", "statewide")]
        assert len(citywide_and_statewide) == 6

    def test_each_official_has_required_fields(self):
        officials = get_officials_for_address(33, "brooklyn", 26, 52)
        for o in officials:
            assert o.title, f"Official missing title: {o}"
            assert o.name, f"Official missing name: {o.title}"
            assert o.contact_method in ("email", "form"), \
                f"Unexpected contact_method for {o.title}: {o.contact_method}"

    def test_email_officials_have_email(self):
        officials = get_officials_for_address(33, "brooklyn", 26, 52)
        email_officials = [o for o in officials if o.contact_method == "email"]
        for o in email_officials:
            assert o.email, f"Email official {o.title} has no email address"

    def test_all_officials_have_party(self):
        officials = get_officials_for_address(33, "brooklyn", 26, 52)
        for o in officials:
            assert o.party, f"{o.title} has no party listed"


class TestJurisdictions:
    def test_groups_match_expected_counts(self):
        officials = get_officials_for_address(33, "brooklyn", 26, 52)
        counts = {}
        for o in officials:
            counts[o.jurisdiction] = counts.get(o.jurisdiction, 0) + 1
        assert counts.get("citywide") == 3
        assert counts.get("borough") == 2
        assert counts.get("statewide") == 3
        assert counts.get("district") == 3
