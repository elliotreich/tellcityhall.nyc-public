"""Application-level coverage for the Council digest submission path."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app
from engine.nyc_address_resolver import AddressResult, ValidatedAddress
from engine.nyc_officials import NYCOfficial
from engine.email_sender import EmailDeliveryResult


class FakeEmailSender:
    def __init__(self):
        self.verifications = []
        self.immediate = []

    async def send_verification(self, **kwargs):
        self.verifications.append(kwargs)
        return EmailDeliveryResult(success=True, message="verification accepted")

    async def send_email(self, **kwargs):
        self.immediate.append(kwargs)
        return EmailDeliveryResult(success=True, message="immediate accepted")


def test_council_message_is_queued_and_verification_is_sent(monkeypatch, tmp_path):
    fake_sender = FakeEmailSender()
    queued = []

    result = AddressResult(
        address=ValidatedAddress(
            street="350 Jay St",
            city="Brooklyn",
            state="NY",
            zip5="11201",
            standardized="350 Jay St, Brooklyn, NY 11201",
        ),
        borough_code="brooklyn",
        council_district=33,
    )
    officials = [
        NYCOfficial(
            title="City Council Member, District 33",
            name="Lincoln Restler",
            email="District33@council.nyc.gov",
            contact_method="email",
            phone="212-555-0100",
            jurisdiction="district",
        ),
        NYCOfficial(
            title="Public Advocate",
            name="Jumaane Williams",
            email="gethelp@advocate.nyc.gov",
            contact_method="email",
            jurisdiction="citywide",
        ),
    ]

    monkeypatch.setattr(app, "validate_and_resolve", lambda _: _async_value(result))
    monkeypatch.setattr(app, "get_officials_for_address", lambda **_: officials)
    monkeypatch.setattr(app, "get_email_sender", lambda: fake_sender)

    def fake_enqueue(**kwargs):
        queued.append(kwargs)
        return "message-1", "token-1"

    monkeypatch.setattr(app, "enqueue", fake_enqueue)
    monkeypatch.setattr(app, "DIGEST_VERIFY_BASE_URL", "https://bridge.example")

    with TestClient(app.app) as client:
        response = client.post(
            "/api/send",
            data={
                "address": "350 Jay St, Brooklyn, NY 11201",
                "first_name": "Ana",
                "last_name": "Rivera",
                "email": "ana@example.com",
                "topic": "Housing",
                "message": "Please protect tenants from displacement.",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    council_result = payload["officials"][0]
    assert council_result["status"] == "queued"
    assert council_result["contact_method"] == "digest"
    assert payload["summary"]["sent"] == 2
    assert queued[0]["district"] == 33
    assert fake_sender.verifications[0]["to_email"] == "ana@example.com"
    assert fake_sender.verifications[0]["verification_url"] == (
        "https://bridge.example/verify/token-1"
    )
    assert len(fake_sender.immediate) == 1
    assert fake_sender.immediate[0]["to_email"] == "gethelp@advocate.nyc.gov"


async def _async_value(value):
    return value
