"""Fabrication guardrail tests for the digest cover letter.

These protect the highest-risk surface in the product: AI prose sent to a
government office. Quotes and tallies are always deterministic, so the only
thing needing policing is generated prose. Every case here is output a real
model could plausibly produce.
"""
import pytest

from engine.digest_builder import FallbackSummarizer, LLMSummarizer

MESSAGES = [
    {
        "topic": "Housing",
        "message": (
            "The rent guidelines board keeps approving increases. I am worried "
            "about staying in my apartment on Grand St."
        ),
    },
    {
        "topic": "Housing",
        "message": (
            "My landlord has ignored three heat complaints this winter. "
            "311 did nothing."
        ),
    },
]


@pytest.fixture
def summarizer():
    return LLMSummarizer()


class TestProseVerification:
    """_verify_prose must reject anything the messages do not support."""

    @pytest.mark.parametrize(
        "label,prose",
        [
            (
                "invented statistic",
                "Constituents are concerned about housing costs. Roughly 70 "
                "percent of residents report rent burdens.",
            ),
            (
                "false generalisation",
                "All constituents in this district demand immediate rent "
                "freezes and oppose the current board.",
            ),
            (
                "majority claim",
                "The majority of constituents want the council member to vote "
                "against the increases.",
            ),
            (
                "cited research",
                "Studies show that rent stabilization improves tenure security "
                "for low-income tenants.",
            ),
            (
                "every-resident claim",
                "Every resident who wrote in is facing eviction and needs "
                "emergency assistance.",
            ),
            (
                "polling claim",
                "Polls show broad support for stronger tenant protections.",
            ),
            (
                "ungrounded new subject",
                "Constituents raised concerns regarding congestion pricing "
                "tolls, bicycle infrastructure funding, commercial zoning "
                "variances, waterfront esplanade development, and ferry "
                "terminal accessibility upgrades.",
            ),
        ],
    )
    def test_rejects_fabrication(self, summarizer, label, prose):
        assert summarizer._verify_prose(prose, MESSAGES) == "", (
            f"fabrication leaked through: {label}"
        )

    def test_rejects_over_generation(self, summarizer):
        assert summarizer._verify_prose("Housing. " * 200, MESSAGES) == ""

    def test_rejects_insufficient_sentinel(self, summarizer):
        assert summarizer._verify_prose("INSUFFICIENT", MESSAGES) == ""

    def test_rejects_empty(self, summarizer):
        assert summarizer._verify_prose("   ", MESSAGES) == ""
        assert summarizer._verify_prose("", MESSAGES) == ""

    def test_accepts_faithful_summary(self, summarizer):
        """The guardrail must not be so strict that nothing survives."""
        good = (
            "Constituents wrote about rent increases approved by the rent "
            "guidelines board and about a landlord ignoring heat complaints. "
            "One described worry about staying in their apartment, and another "
            "said 311 did not resolve the issue."
        )
        assert summarizer._verify_prose(good, MESSAGES) != ""


class TestFallbackBehaviour:
    """Without a key the summariser must degrade, never fabricate or crash."""

    def test_no_key_falls_back_to_deterministic(self, monkeypatch):
        monkeypatch.setattr("engine.digest_builder.NYC_BRIDGE_GEMINI_KEY", "")
        result = LLMSummarizer().summarize(MESSAGES)
        assert result, "summarizer returned nothing"
        assert all(s.prose == "" for s in result), "prose without an API key"
        assert any(s.quotes for s in result), "quotes were dropped"

    def test_api_failure_falls_back(self, monkeypatch, summarizer):
        monkeypatch.setattr("engine.digest_builder.NYC_BRIDGE_GEMINI_KEY", "fake-key")
        monkeypatch.setattr(
            LLMSummarizer,
            "_call_gemini",
            lambda self, prompt: (_ for _ in ()).throw(OSError("network down")),
        )
        result = summarizer.summarize(MESSAGES)
        assert result
        assert all(s.prose == "" for s in result)
        assert any(s.quotes for s in result)

    def test_quotes_are_never_model_supplied(self, monkeypatch, summarizer):
        """Even if the model returns text, quotes come from real messages."""
        monkeypatch.setattr("engine.digest_builder.NYC_BRIDGE_GEMINI_KEY", "fake-key")
        monkeypatch.setattr(
            LLMSummarizer,
            "_call_gemini",
            lambda self, prompt: "A completely invented quote about nothing.",
        )
        result = summarizer.summarize(MESSAGES)
        source = " ".join(m["message"] for m in MESSAGES)
        for summary in result:
            for quote in summary.quotes:
                assert quote.rstrip("…") in source, "quote not from a real message"

    def test_deterministic_summarizer_never_emits_prose(self):
        for summary in FallbackSummarizer().summarize(MESSAGES):
            assert summary.prose == ""
