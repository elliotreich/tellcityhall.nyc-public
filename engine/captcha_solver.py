"""
CAPTCHA solving integration.
Supports 2captcha and Anti-Captcha services.
Used when a form requires reCAPTCHA, hCaptcha, or Turnstile.
"""
import asyncio
import time
from typing import Optional

import httpx

from config import CAPTCHA_API_KEY, CAPTCHA_SERVICE


class CaptchaSolver:
    """
    Solves CAPTCHAs using a third-party solving service.

    Supported services: 2captcha (2captcha.com), anticaptcha (anti-captcha.com)
    Supported captcha types: reCAPTCHA v2, hCaptcha, Cloudflare Turnstile
    """

    # API endpoints
    ENDPOINTS = {
        "2captcha": {
            "submit": "https://api.2captcha.com/createTask",
            "result": "https://api.2captcha.com/getTaskResult",
        },
        "anticaptcha": {
            "submit": "https://api.anti-captcha.com/createTask",
            "result": "https://api.anti-captcha.com/getTaskResult",
        },
    }

    def __init__(self, api_key: str, service: str = None):
        self.api_key = api_key
        self.service = service or CAPTCHA_SERVICE or "2captcha"
        self.endpoints = self.ENDPOINTS.get(self.service, self.ENDPOINTS["2captcha"])

    async def solve_recaptcha(
        self,
        page_url: str,
        sitekey: str,
        invisible: bool = False,
        timeout: int = 120
    ) -> Optional[str]:
        """
        Solve a Google reCAPTCHA v2 challenge.

        Args:
            page_url: The URL of the page containing the captcha
            sitekey: The reCAPTCHA sitekey
            invisible: Whether it's an invisible reCAPTCHA
            timeout: Max seconds to wait for solution

        Returns:
            The g-recaptcha-response token, or None if solving failed
        """
        task = {
            "type": "RecaptchaV2TaskProxyless",
            "websiteURL": page_url,
            "websiteKey": sitekey,
            "isInvisible": invisible,
        }
        return await self._solve_task(task, timeout)

    async def solve_hcaptcha(
        self,
        page_url: str,
        sitekey: str,
        timeout: int = 120
    ) -> Optional[str]:
        """Solve an hCaptcha challenge."""
        task = {
            "type": "HCaptchaTaskProxyless",
            "websiteURL": page_url,
            "websiteKey": sitekey,
        }
        return await self._solve_task(task, timeout)

    async def solve_turnstile(
        self,
        page_url: str,
        sitekey: str,
        timeout: int = 120
    ) -> Optional[str]:
        """Solve a Cloudflare Turnstile challenge."""
        task = {
            "type": "TurnstileTaskProxyless",
            "websiteURL": page_url,
            "websiteKey": sitekey,
        }
        return await self._solve_task(task, timeout)

    async def _solve_task(self, task: dict, timeout: int = 120) -> Optional[str]:
        """Submit a captcha task and poll for the solution."""
        payload = {
            "clientKey": self.api_key,
            "task": task,
        }

        async with httpx.AsyncClient(timeout=timeout + 30) as client:
            # Submit task
            try:
                resp = await client.post(self.endpoints["submit"], json=payload)
                data = resp.json()
            except Exception as e:
                print(f"Captcha submit failed: {e}")
                return None

            if data.get("errorId", 1) != 0:
                print(f"Captcha error: {data.get('errorDescription', 'Unknown')}")
                return None

            task_id = data.get("taskId")
            if not task_id:
                return None

            # Poll for result
            start = time.time()
            while time.time() - start < timeout:
                await asyncio.sleep(3)

                try:
                    resp = await client.post(
                        self.endpoints["result"],
                        json={"clientKey": self.api_key, "taskId": task_id}
                    )
                    result = resp.json()
                except Exception:
                    continue

                if result.get("status") == "ready":
                    solution = result.get("solution", {})
                    # Different captcha types return different keys
                    return (
                        solution.get("gRecaptchaResponse") or
                        solution.get("token") or
                        solution.get("gRecaptchaResponse")
                    )

                if result.get("errorId", 1) != 0:
                    print(f"Captcha solve error: {result.get('errorDescription', '')}")
                    return None

            print(f"Captcha solving timed out after {timeout}s")
            return None


# ---- Sitekey Detection Helpers ----

async def detect_captcha_type(page_source: str) -> tuple[str, str]:
    """
    Detect captcha type and sitekey from page HTML.

    Returns:
        (captcha_type, sitekey) where type is "recaptcha", "hcaptcha", "turnstile", or ""
    """
    import re

    # reCAPTCHA
    recaptcha_match = re.search(r'data-sitekey=["\']([^"\']+)["\']', page_source)
    if recaptcha_match:
        return ("recaptcha", recaptcha_match.group(1))

    # Also check script src
    recaptcha_script = re.search(r'recaptcha/api\.js[^"\']*[?&]k=([^&"\']+)', page_source)
    if recaptcha_script:
        return ("recaptcha", recaptcha_script.group(1))

    # hCaptcha
    hcaptcha_match = re.search(r'data-sitekey=["\']([^"\']+)["\']', page_source)
    hcaptcha_class = 'h-captcha' in page_source or 'hcaptcha' in page_source.lower()
    if hcaptcha_class:
        sitekey = re.search(r'h-captcha["\'\s].*?data-sitekey=["\']([^"\']+)', page_source, re.DOTALL)
        if sitekey:
            return ("hcaptcha", sitekey.group(1))

    # Cloudflare Turnstile
    turnstile_match = re.search(r'turnstile\.render\s*\([^,]+,\s*["\']([^"\']+)["\']', page_source)
    if turnstile_match:
        return ("turnstile", turnstile_match.group(1))
    turnstile_src = re.search(r'challenges\.cloudflare\.com/turnstile/v0/api\.js', page_source)
    if turnstile_src:
        sitekey_match = re.search(r'data-sitekey=["\']([^"\']+)["\']', page_source)
        if sitekey_match:
            return ("turnstile", sitekey_match.group(1))

    return ("", "")
