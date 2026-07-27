"""
NYC Bridge configuration.
Set values via environment variables or edit directly.
"""
import os
from pathlib import Path

# ---- Paths ----
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
OFFICIALS_FILE = DATA_DIR / "nyc_officials.yaml"
COUNCIL_GEOJSON = DATA_DIR / "nyc_council_districts.geojson"
COUNTY_BOROUGH_FILE = DATA_DIR / "county_borough.yaml"
FORMS_DIR = DATA_DIR / "forms"

# ---- Address Validation ----
CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/address"
CENSUS_AUTOCOMPLETE_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"

# NYC county FIPS codes for filtering
NYC_COUNTY_FIPS = {"005", "047", "061", "081", "085"}

# Optional: Google Civic Information API (fallback)
GOOGLE_CIVIC_API_KEY = os.environ.get("GOOGLE_CIVIC_API_KEY", "")
GOOGLE_CIVIC_URL = "https://www.googleapis.com/civicinfo/v2/representatives"

# ---- Captcha Solving ----
CAPTCHA_API_KEY = os.environ.get("CAPTCHA_API_KEY", "")
CAPTCHA_SERVICE = os.environ.get("CAPTCHA_SERVICE", "2captcha")

# ---- Form Submission ----
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "true").lower() == "true"
BROWSER_TIMEOUT = int(os.environ.get("BROWSER_TIMEOUT", "30000"))
FORM_SUBMIT_TIMEOUT = int(os.environ.get("FORM_SUBMIT_TIMEOUT", "60"))

# ---- Email ----
FROM_EMAIL = os.environ.get("FROM_EMAIL", "constituent@nyc-bridge.local")
FROM_NAME = os.environ.get("FROM_NAME", "NYC Bridge")

# SMTP configuration
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.sendgrid.net")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "apikey")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"

# SendGrid / Mailgun API keys (optional, preferred over raw SMTP)
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN", "")

# ---- Message Defaults ----
DEFAULT_TOPIC = "Other"
DEFAULT_SUBJECT = "Message from a constituent"

# ---- Rate Limiting ----
EMAILS_PER_MINUTE = int(os.environ.get("EMAILS_PER_MINUTE", "10"))
MAX_CONCURRENT_SUBMISSIONS = int(os.environ.get("MAX_CONCURRENT", "3"))
DELAY_BETWEEN_SUBMISSIONS = float(os.environ.get("SUBMIT_DELAY", "1.0"))

# ---- Digest Mode ----
DIGEST_DB_PATH = DATA_DIR / "queue.db"
"""Path to the SQLite database for digest message queue."""

DIGEST_MIN_FOR_SUMMARY = int(os.environ.get("DIGEST_MIN_FOR_SUMMARY", "12"))
"""Minimum pending messages before the AI cover letter is generated.

Below this, messages are forwarded plainly with no summary page. A cover
letter "summarising" a handful of messages a staffer could read directly is
noise, and it makes the tool look like it is performing analysis rather than
doing it. 12 is roughly where raw volume becomes a real reading burden."""

DIGEST_DOMAIN_DELAY = float(os.environ.get("DIGEST_DOMAIN_DELAY", "2.0"))
"""Minimum seconds between sends to the same recipient domain."""

DIGEST_TIMEZONE = os.environ.get("DIGEST_TIMEZONE", "America/New_York")
"""Timezone for digest delivery timing."""

DIGEST_VERIFY_BASE_URL = os.environ.get("DIGEST_VERIFY_BASE_URL", "http://localhost:8000")
"""Base URL for verification links in confirmation emails."""

# ---- Digest AI summarisation (Gemini) ----
NYC_BRIDGE_GEMINI_KEY = os.environ.get("NYC_BRIDGE_GEMINI_KEY", "")
"""Dedicated Google AI Studio key for digest summarisation.

Lives in its OWN AI Studio project so free-tier quota is not shared, and is
deliberately NOT part of the LiteLLM free pool. Empty => deterministic
(quotes + tallies only) digests.
"""

DIGEST_GEMINI_MODEL = os.environ.get("DIGEST_GEMINI_MODEL", "gemini-flash-lite-latest")
"""Model used for per-topic prose. Cheap/fast is correct here: the model only
writes 2-3 sentences per topic and never supplies facts or quotes."""

DIGEST_GEMINI_TIMEOUT = float(os.environ.get("DIGEST_GEMINI_TIMEOUT", "30"))
"""Seconds to wait on the summarisation call before falling back."""
