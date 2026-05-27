#!/usr/bin/env python3
"""Fast batch YAML generator for House Drupal EVO members."""
import yaml, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from engine.address_validator import _load_legislators

YAML_DIR = Path("data/contact-congress/members")
LEGISLATORS_FILE = Path("data/congress-legislators/legislators-current.yaml")

# Build member name lookup once
with open(LEGISLATORS_FILE) as f:
    legislator_data = yaml.safe_load(f)

member_urls = {}
for m in legislator_data:
    bio = m.get("id", {}).get("bioguide", "")
    name = m.get("name", {})
    last = name.get("last", "").lower().replace(" ", "").replace("'", "").replace(".", "")
    # Check for official URL in terms
    for term in m.get("terms", []):
        url = term.get("url", "")
        if url and "house.gov" in url:
            try:
                prefix = url.split("://")[1].split(".house.gov")[0]
                member_urls[bio] = prefix
            except:
                pass
    if bio not in member_urls:
        member_urls[bio] = last

# Template
TEMPLATE = """bioguide: {bioguide}
contact_form:
  method: post
  action: ""
  steps:
    - visit: "https://{member_name}.house.gov/contact"
    - find:
        - selector: "#edit-first-name-2"
    - fill_in:
        - name: first_name_2
          selector: "#edit-first-name-2"
          value: $NAME_FIRST
          required: true
        - name: last_name_2
          selector: "#edit-last-name-2"
          value: $NAME_LAST
          required: true
    - select:
        - name: honorific_2
          selector: "#edit-honorific-2"
          value: $NAME_PREFIX
          required: true
          options:
            "Mr.": "Mr."
            "Ms.": "Ms."
            "Mrs.": "Mrs."
            "Miss.": "Miss."
            "Dr.": "Dr."
        - name: suffix_2
          selector: "#edit-suffix-2"
          value: ""
          required: false
          options:
            "- None -": ""
            "Jr.": "Jr."
            "Sr.": "Sr."
            "II": "II"
            "III": "III"
    - click_on:
        - value: "Next Page"
          selector: "#edit-wizard-next"
    - find:
        - selector: "input[name='email']"
    - fill_in:
        - name: email
          selector: "input[name='email']"
          value: $EMAIL
          required: true
        - name: street
          selector: "input[name='street']"
          value: $ADDRESS_STREET
          required: true
        - name: city
          selector: "input[name='city']"
          value: $ADDRESS_CITY
          required: true
        - name: zip
          selector: "input[name='zip']"
          value: $ADDRESS_ZIP5
          required: true
        - name: subject
          selector: "input[name='subject']"
          value: $SUBJECT
          required: true
        - name: message
          selector: "textarea[name='message']"
          value: $MESSAGE
          required: true
          options:
            max_length: 5000
    - select:
        - name: topic
          selector: "select[name='topic']"
          value: $TOPIC
          required: true
          options:
            Agriculture: Agriculture
            Budget: Budget
            Civil Rights: Civil Rights
            Defense: Defense
            Economy: Economy
            Education: Education
            Energy: Energy
            Environment: Environment
            Foreign Affairs: Foreign Affairs
            Healthcare: Healthcare
            Homeland Security: Homeland Security
            Housing: Housing
            Immigration: Immigration
            Judiciary: Judiciary
            Labor: Labor
            Science: Science
            Small Business: Small Business
            Social Security: Social Security
            Taxes: Taxes
            Technology: Technology
            Trade: Trade
            Transportation: Transportation
            Veterans: Veterans
            Other: Other
    - click_on:
        - value: "Submit"
          selector: "input[type='submit']"
    - find:
        - selector: "h1"
  success:
    headers:
      status: 200
    body:
      contains: "Thank you"
"""

db = _load_legislators()
generated = 0
for key, rep in db["house"].items():
    bio = rep["bioguide"]
    yaml_path = YAML_DIR / f"{bio}.yaml"

    if yaml_path.exists():
        try:
            import yaml as _yaml
            _yaml.safe_load(yaml_path.read_text())
            # File parses OK - skip if it's not a stub
            content = yaml_path.read_text()
            if "stubforcwc" not in content.lower():
                continue  # Already valid
        except Exception:
            pass  # Broken YAML - regenerate it

    member_name = member_urls.get(bio, "")
    if not member_name:
        continue

    yaml_path.write_text(TEMPLATE.format(bioguide=bio, member_name=member_name))
    generated += 1

print(f"{generated} YAMLs generated")
