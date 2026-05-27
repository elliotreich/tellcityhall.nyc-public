"""
Civic Bridge configuration.
Set values via environment variables or edit directly.
"""
import os
from pathlib import Path

# ---- Paths ----
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
YAML_DIR = DATA_DIR / "contact-congress" / "members"
LEGISLATORS_FILE = DATA_DIR / "congress-legislators" / "legislators-current.yaml"
SUPPORT_DIR = DATA_DIR / "contact-congress" / "support"

# ---- Address Validation ----
# Primary: US Census Geocoder (free, no key required)
CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/address"

# Optional: Google Civic Information API (requires key, much better)
GOOGLE_CIVIC_API_KEY = os.environ.get("GOOGLE_CIVIC_API_KEY", "")
GOOGLE_CIVIC_URL = "https://www.googleapis.com/civicinfo/v2/representatives"

# ---- Captcha Solving ----
# 2captcha / Anti-Captcha API (optional - only needed for captcha-protected forms)
CAPTCHA_API_KEY = os.environ.get("CAPTCHA_API_KEY", "")
CAPTCHA_SERVICE = os.environ.get("CAPTCHA_SERVICE", "2captcha")  # or "anticaptcha"

# ---- Form Submission ----
# Headless browser settings
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "true").lower() == "true"
BROWSER_TIMEOUT = int(os.environ.get("BROWSER_TIMEOUT", "30000"))  # ms
FORM_SUBMIT_TIMEOUT = int(os.environ.get("FORM_SUBMIT_TIMEOUT", "60"))  # seconds

# ---- Message Defaults ----
DEFAULT_PREFIX = "Mr."
DEFAULT_TOPIC = "Other"
DEFAULT_SUBJECT = "Message from a constituent"
DEFAULT_PHONE = ""  # Leave empty if not required

# ---- Email for delivery confirmation ----
DEFAULT_FROM_EMAIL = os.environ.get("FROM_EMAIL", "constituent@civicbridge.local")

# ---- Rate Limiting ----
MAX_CONCURRENT_SUBMISSIONS = int(os.environ.get("MAX_CONCURRENT", "5"))
DELAY_BETWEEN_SUBMISSIONS = float(os.environ.get("SUBMIT_DELAY", "1.0"))  # seconds

# ---- CWC API (House - requires vendor application) ----
CWC_API_KEY = os.environ.get("CWC_API_KEY", "")
CWC_HOST = os.environ.get("CWC_HOST", "https://cwc.house.gov/")
CWC_DELIVERY_AGENT = os.environ.get("CWC_DELIVERY_AGENT", "Civic Bridge")
CWC_CONTACT_EMAIL = os.environ.get("CWC_CONTACT_EMAIL", "")
CWC_CONTACT_PHONE = os.environ.get("CWC_CONTACT_PHONE", "")
