"""
Parse contact-congress YAML form definitions.
Resolves variables, validates structure, produces executable step list.
"""
import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Optional

from config import YAML_DIR, SUPPORT_DIR

# ---- Variable definitions (from contact-congress support/variables.yaml) ----

VARIABLE_DEFAULTS = {
    "$NAME_PREFIX": "Mr.",
    "$NAME_FIRST": "John",
    "$NAME_LAST": "Citizen",
    "$NAME_FULL": "John Citizen",
    "$ADDRESS_STREET": "1600 Pennsylvania Ave NW",
    "$ADDRESS_STREET_2": "",
    "$ADDRESS_CITY": "Washington",
    "$ADDRESS_STATE_POSTAL_ABBREV": "DC",
    "$ADDRESS_STATE_FULL": "District of Columbia",
    "$ADDRESS_COUNTY": "",
    "$ADDRESS_ZIP5": "20500",
    "$ADDRESS_ZIP4": "",
    "$ADDRESS_ZIP_PLUS_4": "20500-0003",
    "$PHONE": "202-555-0123",
    "$PHONE_PARENTHESES": "(202) 555-0123",
    "$EMAIL": "constituent@example.com",
    "$TOPIC": "Other",
    "$SUBJECT": "Message from a constituent",
    "$MESSAGE": "Hello, I am writing to share my thoughts.",
    "$CAPTCHA_SOLUTION": "",
    "$CAMPAIGN_UUID": "",
    "$PERMALINK": "",
    "$ORG_URL": "",
    "$ORG_NAME": "",
}

# Load constants (US_STATES, etc.)
_CONSTANTS: dict[str, list] = {}
_constants_path = SUPPORT_DIR / "constants.yaml"
if _constants_path.exists():
    with open(_constants_path) as f:
        _CONSTANTS = yaml.safe_load(f) or {}


# ---- Data Models ----

@dataclass
class FormStep:
    """A single step in the form submission process."""
    step_type: str  # "visit", "fill_in", "select", "click_on", "check", "choose", "find", "wait", "javascript", "recaptcha"
    params: dict = field(default_factory=dict)


@dataclass
class ParsedForm:
    """A fully parsed contact form definition."""
    bioguide: str
    method: str  # GET or POST
    action: str  # Form action URL
    steps: list[FormStep]
    success_criteria: dict  # How to detect successful submission
    has_captcha: bool
    captcha_type: str = ""  # "recaptcha", "hcaptcha", "turnstile", or ""
    captcha_sitekey: str = ""
    raw_yaml: dict = field(default_factory=dict)

    @property
    def has_required_captcha(self) -> bool:
        """Does this form REQUIRE captcha solving (not just present but needed)?"""
        return self.has_captcha and self.captcha_type in ("recaptcha", "hcaptcha")


# ---- Context for Variable Resolution ----

@dataclass
class UserContext:
    """User data used to resolve form variables."""
    prefix: str = "Mr."
    first_name: str = ""
    last_name: str = ""
    address_street: str = ""
    address_street_2: str = ""
    address_city: str = ""
    address_state: str = ""       # 2-letter postal abbreviation
    address_state_full: str = ""  # Full state name
    address_zip5: str = ""
    address_zip4: str = ""
    phone: str = ""
    email: str = ""
    topic: str = "Other"
    subject: str = "Message from a constituent"
    message: str = ""
    org_name: str = ""
    org_url: str = ""
    campaign_uuid: str = ""

    def resolve(self, var_name: str) -> str:
        """Resolve a $VARIABLE to its value from user context."""
        mapping = {
            "$NAME_PREFIX": self.prefix,
            "$NAME_FIRST": self.first_name,
            "$NAME_LAST": self.last_name,
            "$NAME_FULL": f"{self.first_name} {self.last_name}".strip(),
            "$ADDRESS_STREET": self.address_street,
            "$ADDRESS_STREET_2": self.address_street_2,
            "$ADDRESS_CITY": self.address_city,
            "$ADDRESS_STATE_POSTAL_ABBREV": self.address_state,
            "$ADDRESS_STATE_FULL": self.address_state_full,
            "$ADDRESS_ZIP5": self.address_zip5,
            "$ADDRESS_ZIP4": self.address_zip4,
            "$ADDRESS_ZIP_PLUS_4": f"{self.address_zip5}-{self.address_zip4}" if self.address_zip4 else self.address_zip5,
            "$PHONE": self.phone,
            "$PHONE_PARENTHESES": _format_phone_parens(self.phone),
            "$EMAIL": self.email,
            "$TOPIC": self.topic,
            "$SUBJECT": self.subject,
            "$MESSAGE": self.message,
            "$CAPTCHA_SOLUTION": "",  # Filled at runtime
            "$CAMPAIGN_UUID": self.campaign_uuid,
            "$ORG_NAME": self.org_name,
            "$ORG_URL": self.org_url,
        }
        return mapping.get(var_name, var_name)

    def resolve_value(self, value: Any) -> Any:
        """Resolve a value that might be a variable reference."""
        if isinstance(value, str) and value.startswith("$"):
            return self.resolve(value)
        return value


def _format_phone_parens(phone: str) -> str:
    """Format phone as (202) 555-0123."""
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return phone


# ---- Main Parser ----

def load_form(bioguide: str) -> Optional[ParsedForm]:
    """
    Load and parse a contact form YAML for a given bioguide ID.

    Returns None if the file doesn't exist or is a stub.
    """
    yaml_path = YAML_DIR / f"{bioguide}.yaml"
    if not yaml_path.exists():
        return None

    try:
        with open(yaml_path) as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        # Skip broken YAML files — these are upstream issues
        return None

    if not raw:
        return None

    cf = raw.get("contact_form", {})
    if isinstance(cf, dict):
        if cf.get("stubforcwc"):
            return None
        # Check if any step value contains stubforcwc
        steps = cf.get("steps", [])
        for step in steps:
            step_str = str(step).lower()
            if "stubforcwc" in step_str:
                return None
    elif isinstance(cf, str) and "stubforcwc" in cf.lower():
        return None

    # Also check raw top-level
    raw_str = str(raw).lower()
    if "stubforcwc" in raw_str and "visit:" in raw_str:
        # Has a visit: stubforcwc step → it's a stub
        if raw_str.count("visit:") <= 1 and raw_str.count("fill_in:") == 0:
            return None

    try:
        return _parse_yaml(raw, bioguide)
    except Exception:
        return None


def _parse_yaml(raw: dict, bioguide: str) -> ParsedForm:
    """Parse raw YAML into a ParsedForm."""
    cf = raw.get("contact_form", raw)
    method = cf.get("method", "POST").upper()
    action = cf.get("action", "")
    raw_steps = cf.get("steps", [])
    success = cf.get("success", {})

    steps = []
    has_captcha = False
    captcha_type = ""
    captcha_sitekey = ""

    for step_group in raw_steps:
        if isinstance(step_group, dict):
            for step_type, step_items in step_group.items():
                if step_type == "recaptcha":
                    has_captcha = True
                    captcha_type = "recaptcha"
                    steps.append(FormStep(step_type="recaptcha", params={"value": True}))
                    continue

                if not isinstance(step_items, list):
                    step_items = [step_items]

                for item in step_items:
                    steps.append(_parse_step(step_type, item))

    # Detect captcha sitekey from fill_in steps (hCaptcha often uses hidden inputs)
    for s in steps:
        if s.step_type == "fill_in":
            name = s.params.get("name", "").lower()
            selector = s.params.get("selector", "").lower()
            if "h-captcha" in selector or "hcaptcha" in name or "captcha" in name:
                has_captcha = True
                captcha_type = captcha_type or "hcaptcha"

    return ParsedForm(
        bioguide=bioguide,
        method=method,
        action=action,
        steps=steps,
        success_criteria=success,
        has_captcha=has_captcha,
        captcha_type=captcha_type,
        raw_yaml=raw,
    )


def _parse_step(step_type: str, item: dict) -> FormStep:
    """Parse a single step item."""
    params = {}

    if step_type == "visit":
        params["url"] = item.get("visit", item) if isinstance(item, dict) else item
        if isinstance(item, dict):
            params["url"] = item.get("visit", item.get("value", ""))

    elif step_type == "fill_in":
        params["name"] = item.get("name", "")
        params["selector"] = item.get("selector", "")
        params["value"] = item.get("value", "")
        params["required"] = item.get("required", False) in (True, "true", "Yes", "yes")
        opts = item.get("options", {})
        if isinstance(opts, dict):
            params["max_length"] = opts.get("max_length")

    elif step_type == "select":
        params["name"] = item.get("name", "")
        params["selector"] = item.get("selector", "")
        params["value"] = item.get("value", "")
        params["required"] = item.get("required", False) in (True, "true", "Yes", "yes")
        params["options"] = _normalize_options(item.get("options", []))

    elif step_type == "click_on":
        params["selector"] = item.get("selector", "")
        params["value"] = item.get("value", "")

    elif step_type in ("check", "choose"):
        params["name"] = item.get("name", "")
        params["selector"] = item.get("selector", "")
        params["value"] = item.get("value", "")
        params["options"] = _normalize_options(item.get("options", []))

    elif step_type == "find":
        params["selector"] = item.get("selector", "")
        params["value"] = item.get("value", "")
        wait_opts = item.get("options", {})
        if isinstance(wait_opts, dict):
            params["wait"] = wait_opts.get("wait", 10)

    elif step_type == "wait":
        params["value"] = item.get("value", 1)

    elif step_type == "javascript":
        params["value"] = item.get("value", "")

    elif step_type == "recaptcha":
        params["value"] = item.get("value", True)

    return FormStep(step_type=step_type, params=params)


def _normalize_options(options: list) -> list[dict]:
    """Normalize options into a consistent [{"label": ..., "value": ...}] format."""
    result = []
    if isinstance(options, str):
        # Reference to constants like "US_STATES"
        const_values = _CONSTANTS.get(options, {}).get("value", [])
        for v in const_values:
            result.append({"label": v, "value": v})
        return result

    if not isinstance(options, list):
        return result

    for opt in options:
        if isinstance(opt, dict):
            for label, value in opt.items():
                result.append({"label": str(label), "value": str(value)})
        elif isinstance(opt, str):
            result.append({"label": opt, "value": opt})
    return result


# ---- Form Validation ----

def validate_form(form: ParsedForm) -> list[str]:
    """Validate a parsed form and return any issues found."""
    issues = []

    if not form.steps:
        issues.append("No steps defined")
        return issues

    has_visit = any(s.step_type == "visit" for s in form.steps)
    if not has_visit:
        issues.append("No visit step (no URL to navigate to)")

    # Check for some kind of submit action: click_on or javascript click
    has_submit = any(
        s.step_type == "click_on" or
        (s.step_type == "javascript" and ".click()" in str(s.params.get("value", "")))
        for s in form.steps
    )
    if not has_submit:
        issues.append("No click_on or submit step")

    if not form.success_criteria:
        issues.append("No success criteria defined")

    return issues


# ---- Utility ----

def list_available_senators() -> list[str]:
    """List all bioguide IDs that have valid (non-stub) YAML files."""
    available = []
    for yaml_file in YAML_DIR.glob("*.yaml"):
        bio = yaml_file.stem
        form = load_form(bio)
        if form is not None:
            available.append(bio)
    return sorted(available)


def get_form_summary(form: ParsedForm) -> dict:
    """Get a human-readable summary of a parsed form."""
    steps_summary = []
    for s in form.steps:
        if s.step_type == "visit":
            steps_summary.append(f"Navigate to {s.params.get('url', '?')}")
        elif s.step_type == "fill_in":
            steps_summary.append(f"Fill '{s.params.get('name', '?')}' with {s.params.get('value', '?')}")
        elif s.step_type == "select":
            steps_summary.append(f"Select '{s.params.get('value', '?')}' in dropdown '{s.params.get('name', '?')}'")
        elif s.step_type == "click_on":
            steps_summary.append(f"Click '{s.params.get('selector', '?')}'")
        elif s.step_type == "recaptcha":
            steps_summary.append("Solve CAPTCHA")
        elif s.step_type == "find":
            steps_summary.append(f"Wait for '{s.params.get('selector', '?')}'")
        else:
            steps_summary.append(s.step_type)

    return {
        "bioguide": form.bioguide,
        "method": form.method,
        "action": form.action,
        "steps_count": len(form.steps),
        "has_captcha": form.has_captcha,
        "captcha_type": form.captcha_type,
        "steps": steps_summary,
    }
