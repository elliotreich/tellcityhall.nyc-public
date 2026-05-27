"""
Headless browser form submission engine using Playwright.
Translates contact-congress YAML steps into Playwright actions.
"""
import asyncio
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeout

from config import BROWSER_HEADLESS, BROWSER_TIMEOUT, FORM_SUBMIT_TIMEOUT, CAPTCHA_API_KEY
from engine.yaml_parser import ParsedForm, UserContext, FormStep
from engine.captcha_solver import CaptchaSolver


# ---- Data Models ----

@dataclass
class SubmissionResult:
    """Result of a form submission attempt."""
    bioguide: str
    success: bool
    error: Optional[str] = None
    message: str = ""
    duration_seconds: float = 0.0
    captcha_solved: bool = False
    status_code: Optional[int] = None
    response_body_preview: str = ""


# ---- Main Submitter ----

class FormSubmitter:
    """
    Submits a message to a representative's contact form using Playwright.
    """

    def __init__(self):
        self._browser: Optional[Browser] = None
        self._captcha: Optional[CaptchaSolver] = None
        if CAPTCHA_API_KEY:
            self._captcha = CaptchaSolver(CAPTCHA_API_KEY)

    async def start(self):
        """Launch the browser."""
        pw = await async_playwright().start()
        self._browser = await pw.chromium.launch(
            headless=BROWSER_HEADLESS,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )

    async def stop(self):
        """Close the browser."""
        if self._browser:
            await self._browser.close()

    async def submit(
        self,
        form: ParsedForm,
        context: UserContext,
        timeout: int = FORM_SUBMIT_TIMEOUT
    ) -> SubmissionResult:
        """
        Submit a message using a parsed form definition.

        Args:
            form: Parsed form definition from YAML
            context: User data for variable resolution
            timeout: Max seconds for entire submission

        Returns:
            SubmissionResult indicating success/failure
        """
        start_time = time.time()
        result = SubmissionResult(bioguide=form.bioguide, success=False)

        if self._browser is None:
            result.error = "Browser not started. Call start() first."
            return result

        page: Optional[Page] = None
        try:
            page = await self._browser.new_page()
            page.set_default_timeout(BROWSER_TIMEOUT)

            captured_response = None

            # Intercept the final form submission response
            async def capture_response(response):
                nonlocal captured_response
                if response.request.method in ("POST", "GET") and response.status:
                    captured_response = response

            page.on("response", capture_response)

            # Execute each step
            for step in form.steps:
                try:
                    await self._execute_step(page, form, step, context)
                except PlaywrightTimeout as e:
                    result.error = f"Timeout on step '{step.step_type}': {e}"
                    return result
                except Exception as e:
                    result.error = f"Failed on step '{step.step_type}' ({step.params.get('selector', step.params.get('url', ''))}): {e}"
                    return result

            # Wait for network to settle after submit
            await asyncio.sleep(2)

            # Check success
            if form.success_criteria:
                success = await self._check_success(page, form.success_criteria)
                result.success = success
                if success:
                    result.message = "Message delivered successfully."
                else:
                    result.message = "Form submission may have failed - success criteria not detected."
            else:
                # No success criteria defined - assume success if no errors
                result.success = True
                result.message = "Message submitted (no success criteria to verify)."

            if captured_response:
                result.status_code = captured_response.status

        except asyncio.TimeoutError:
            result.error = f"Overall submission timed out after {timeout}s."
        except Exception as e:
            result.error = f"Unexpected error: {e}"
        finally:
            if page:
                try:
                    body = await page.content()
                    result.response_body_preview = body[:500]
                except Exception:
                    pass
                await page.close()

        result.duration_seconds = time.time() - start_time
        return result

    async def _execute_step(
        self,
        page: Page,
        form: ParsedForm,
        step: FormStep,
        context: UserContext
    ):
        """Execute a single form step."""
        st = step.step_type

        if st == "visit":
            url = step.params.get("url", "")
            if url:
                await page.goto(url, wait_until="networkidle")

        elif st == "wait":
            seconds = step.params.get("value", 1)
            try:
                seconds = float(seconds)
            except (ValueError, TypeError):
                seconds = 1
            await asyncio.sleep(seconds)

        elif st == "find":
            selector = step.params.get("selector", "")
            text = step.params.get("value", "")
            wait_ms = int(step.params.get("wait", 10)) * 1000
            if text:
                await page.wait_for_selector(f"{selector}", timeout=wait_ms)
                # Also check text content
                await page.wait_for_function(
                    f"document.querySelector('{selector}')?.textContent?.includes('{text}')",
                    timeout=wait_ms
                )
            else:
                await page.wait_for_selector(selector, timeout=wait_ms)

        elif st == "fill_in":
            selector = step.params.get("selector", "")
            value = step.params.get("value", "")
            max_len = step.params.get("max_length")

            # Resolve variable
            resolved = context.resolve_value(value)

            # Handle max length
            if max_len and isinstance(resolved, str) and len(resolved) > int(max_len):
                resolved = resolved[:int(max_len)]

            if selector:
                try:
                    # Try to fill by selector
                    await page.fill(selector, str(resolved))
                except Exception:
                    # Fall back to name attribute
                    name = step.params.get("name", "")
                    if name:
                        await page.fill(f"[name='{name}']", str(resolved))

        elif st == "select":
            selector = step.params.get("selector", "")
            value = step.params.get("value", "")
            name = step.params.get("name", "")
            options = step.params.get("options", [])

            resolved = context.resolve_value(value)

            if selector:
                # Try to find matching option in the select
                option_to_select = resolved
                for opt in options:
                    if opt.get("value", "").lower() == resolved.lower():
                        option_to_select = opt.get("label", opt.get("value", resolved))
                        break

                try:
                    await page.select_option(selector, label=option_to_select)
                except Exception:
                    # Try by value
                    try:
                        await page.select_option(selector, value=option_to_select)
                    except Exception:
                        # Try to find by partial text match
                        if options:
                            await page.select_option(selector, index=0)  # Select first as fallback

        elif st == "click_on":
            selector = step.params.get("selector", "")
            button_text = step.params.get("value", "")

            if selector:
                try:
                    if button_text:
                        # Find button with matching text/value
                        btn = page.locator(selector).filter(has_text=button_text)
                        if await btn.count() > 0:
                            await btn.first.click()
                        else:
                            await page.click(selector)
                    else:
                        await page.click(selector)
                except Exception as e:
                    # Try clicking by visible text
                    if button_text:
                        try:
                            await page.get_by_role("button", name=button_text).click()
                        except Exception:
                            await page.get_by_text(button_text).click()
                    else:
                        raise

        elif st == "check":
            selector = step.params.get("selector", "")
            name = step.params.get("name", "")
            value = step.params.get("value", "")
            resolved = context.resolve_value(value)

            if selector:
                if name:
                    # Check specific checkbox by value
                    await page.check(f"{selector}[value='{resolved}']")
                else:
                    await page.check(selector)

        elif st == "choose":
            # Radio buttons
            selector = step.params.get("selector", "")
            value = step.params.get("value", "")
            resolved = context.resolve_value(value)

            if selector and resolved:
                try:
                    await page.check(f"{selector}[value='{resolved}']")
                except Exception:
                    # Try by label
                    pass

        elif st == "javascript":
            js_code = step.params.get("value", "")
            if js_code:
                await page.evaluate(js_code)

        elif st == "recaptcha":
            if self._captcha:
                sitekey = await self._detect_captcha_sitekey(page)
                if sitekey:
                    solution = await self._captcha.solve_recaptcha(page.url, sitekey)
                    await page.evaluate(f"""
                        document.getElementById('g-recaptcha-response').value = '{solution}';
                        document.getElementById('g-recaptcha-response').style.display = 'block';
                    """)

    async def _detect_captcha_sitekey(self, page: Page) -> Optional[str]:
        """Try to detect reCAPTCHA sitekey from the page."""
        sitekey = await page.evaluate("""
            () => {
                const el = document.querySelector('.g-recaptcha');
                if (el) return el.getAttribute('data-sitekey');
                const script = document.querySelector('script[src*="recaptcha"]');
                if (script) {
                    const match = script.src.match(/[?&]k=([^&]+)/);
                    if (match) return match[1];
                }
                return null;
            }
        """)
        return sitekey

    async def _check_success(self, page: Page, criteria: dict) -> bool:
        """Check if form submission was successful based on YAML success criteria."""
        contains = criteria.get("body", {}).get("contains", "")
        matches = criteria.get("body", {}).get("matches", "")

        if not contains and not matches:
            # No criteria - check for common success patterns
            body = await page.content()
            success_patterns = [
                "thank you", "message has been sent", "successfully submitted",
                "we have received", "your message was sent", "thank you for contacting",
                "thank you for your message", "thanks for contacting",
                "confirmation", "received your message",
            ]
            body_lower = body.lower()
            return any(p in body_lower for p in success_patterns)

        body = await page.content()

        if contains:
            if contains.lower() in body.lower():
                return True

        if matches:
            if re.search(matches, body, re.IGNORECASE):
                return True

        return False


# ---- Convenience Functions ----

async def submit_message(
    bioguide: str,
    context: UserContext,
    submitter: Optional[FormSubmitter] = None
) -> SubmissionResult:
    """
    High-level function: load YAML, submit form, return result.
    """
    from engine.yaml_parser import load_form

    form = load_form(bioguide)
    if form is None:
        return SubmissionResult(
            bioguide=bioguide,
            success=False,
            error=f"No form definition found for {bioguide}",
        )

    own_submitter = submitter is None
    if own_submitter:
        submitter = FormSubmitter()
        await submitter.start()

    try:
        result = await submitter.submit(form, context)
    finally:
        if own_submitter:
            await submitter.stop()

    return result
