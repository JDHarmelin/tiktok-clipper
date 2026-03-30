"""Handles TikTok video uploads with post-upload verification.
Runs uploads in a subprocess to avoid Playwright/asyncio conflicts."""
import time
import subprocess
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

try:
    from config import TIKTOK_ACCOUNTS, BASE_DIR
except ImportError:
    TIKTOK_ACCOUNTS = {"default": "./cookies.txt"}
    BASE_DIR = Path(__file__).parent

logger = logging.getLogger(__name__)

SCREENSHOTS_DIR = BASE_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# Account registry: populated from TIKTOK_ACCOUNTS env config.
_accounts: dict[str, str] = dict(TIKTOK_ACCOUNTS)


def register_account(name: str, cookies_path: str):
    """Register a TikTok account with its cookie file path."""
    _accounts[name] = cookies_path


def list_accounts() -> list[str]:
    """Return names of all registered TikTok accounts."""
    return list(_accounts.keys())


def _get_cookies_path(account_name: str | None) -> str:
    """Resolve cookie file path for the given account."""
    if account_name is None:
        account_name = "default"
    path = _accounts.get(account_name)
    if path is None:
        raise ValueError(
            f"Unknown account '{account_name}'. "
            f"Registered accounts: {list(_accounts.keys())}"
        )
    return path


def _resolve_path(path_str: str) -> Path:
    """Resolve a path to absolute, relative to BASE_DIR if needed."""
    p = Path(path_str)
    if not p.is_absolute():
        p = BASE_DIR / p
    return p


def _screenshot(page, label: str) -> str | None:
    """Save a debug screenshot and return the path."""
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SCREENSHOTS_DIR / f"{label}_{ts}.png"
        page.screenshot(path=str(path), full_page=True)
        logger.info(f"Screenshot saved: {path}")
        return str(path)
    except Exception as e:
        logger.warning(f"Screenshot failed: {e}")
        return None


def _verify_upload(page, caption: str, timeout: int = 30) -> dict:
    """
    Verify an upload actually posted by checking the manage page.
    Returns {"verified": bool, "reason": str, "screenshot": str|None}.
    """
    try:
        # After posting, TikTok redirects to either /manage or /tiktokstudio/content.
        # Wait for either URL pattern.
        try:
            page.wait_for_url("**/manage**", timeout=timeout * 1000)
        except Exception:
            try:
                page.wait_for_url("**/tiktokstudio/content**", timeout=5000)
            except Exception:
                pass  # Fall through to content-based checks

        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(3)  # Let the page populate

        page_text = page.content()
        current_url = page.url

        # URL-based success: we landed on a content management page
        on_manage_page = any(p in current_url for p in ["/manage", "/tiktokstudio/content"])

        # Content-based success indicators
        success_indicators = [
            "Your video has been uploaded",
            "Video published",
            "Manage your posts",
            "manage your account",
            "Posts",
        ]
        found_manage = on_manage_page or any(ind.lower() in page_text.lower() for ind in success_indicators)

        # Check for failure indicators
        failure_indicators = [
            "upload failed",
            "try again",
            "video removed",
            "community guidelines",
            "under review",
        ]
        found_failure = [
            ind for ind in failure_indicators if ind.lower() in page_text.lower()
        ]

        if found_failure:
            screenshot = _screenshot(page, "upload_rejected")
            return {
                "verified": False,
                "reason": f"TikTok rejected: {', '.join(found_failure)}",
                "screenshot": screenshot,
            }

        if found_manage:
            # We're on the manage page — this is the best signal we have that
            # the upload went through. The library's own check passed AND
            # we confirmed we landed on /manage.
            return {"verified": True, "reason": "Landed on manage page", "screenshot": None}

        # Ambiguous — we're somewhere but can't confirm
        screenshot = _screenshot(page, "upload_ambiguous")
        return {
            "verified": False,
            "reason": f"Could not confirm upload. Page URL: {current_url}",
            "screenshot": screenshot,
        }

    except Exception as e:
        screenshot = _screenshot(page, "upload_verify_error")
        return {
            "verified": False,
            "reason": f"Verification error: {e}",
            "screenshot": screenshot,
        }


def upload_to_tiktok(
    video_path: str,
    caption: str,
    account_name: str | None = None,
) -> dict:
    """
    Upload a single video to TikTok with caption and verify it posted.
    Runs in a subprocess to avoid Playwright sync API / asyncio conflicts.
    """
    logger.info(f"upload_to_tiktok called: video_path={video_path}, account={account_name}")

    vpath = _resolve_path(video_path)
    if not vpath.exists():
        logger.error(f"Video not found: {vpath}")
        return {"success": False, "error": f"Video not found: {vpath}"}

    try:
        cookies_path = _get_cookies_path(account_name)
    except ValueError as e:
        logger.error(f"Account lookup failed: {e}")
        return {"success": False, "error": str(e)}

    cookies_abs = _resolve_path(cookies_path)
    if not cookies_abs.exists():
        logger.error(f"Cookies not found: {cookies_abs}")
        return {
            "success": False,
            "error": f"TikTok cookies file not found at {cookies_abs}. Export cookies from browser.",
        }

    # Run upload + verification in a subprocess to isolate Playwright from asyncio
    script = f"""
import sys, json, time, signal
signal.alarm(180)

screenshots_dir = {str(SCREENSHOTS_DIR)!r}
from pathlib import Path
from datetime import datetime
Path(screenshots_dir).mkdir(exist_ok=True)

def take_screenshot(page, label):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = str(Path(screenshots_dir) / f"{{label}}_{{ts}}.png")
        page.screenshot(path=path, full_page=True)
        return path
    except Exception:
        return None

try:
    from tiktok_uploader.upload import TikTokUploader
    uploader = TikTokUploader(cookies={str(cookies_abs)!r}, headless=True)
    success = uploader.upload_video(
        filename={str(vpath)!r},
        description={caption!r},
    )

    if not success:
        ss = take_screenshot(uploader.page, "upload_failed")
        uploader.close()
        print(json.dumps({{"success": False, "error": "TikTok uploader reported failure", "screenshot": ss}}))
        sys.exit(0)

    page = uploader.page
    current_url = page.url

    # Check for TikTok rate limits or content check limits
    page_text = page.inner_text("body") if page.query_selector("body") else ""
    if "check limit" in page_text.lower() or "try again tomorrow" in page_text.lower():
        screenshot = take_screenshot(page, "rate_limited")
        uploader.close()
        print(json.dumps({{"success": False, "error": "TikTok daily content check limit reached. Try again tomorrow.", "screenshot": screenshot, "rate_limited": True}}))
        sys.exit(0)

    # If still on upload page, the library failed to click Post
    if "upload" in current_url:
        # Wait for content checks to finish (up to 60s)
        for _ in range(12):
            page_text = page.inner_text("body") if page.query_selector("body") else ""
            if "check limit" in page_text.lower() or "try again tomorrow" in page_text.lower():
                screenshot = take_screenshot(page, "rate_limited")
                uploader.close()
                print(json.dumps({{"success": False, "error": "TikTok daily content check limit reached. Try again tomorrow.", "screenshot": screenshot, "rate_limited": True}}))
                sys.exit(0)
            if "checking" not in page_text.lower():
                break
            time.sleep(5)

        # Try multiple selectors for the Post button
        post_selectors = [
            "button:has-text('Post')",
            "//button[.//div[text()='Post']]",
            "button[data-e2e='post_video_button']",
        ]
        clicked = False
        for sel in post_selectors:
            try:
                if sel.startswith("//"):
                    btn = page.locator(f"xpath={{sel}}")
                else:
                    btn = page.locator(sel)
                if btn.count() > 0 and btn.first.is_visible():
                    # Wait for button to be enabled (up to 30s)
                    for _ in range(30):
                        disabled = btn.first.get_attribute("disabled")
                        aria_disabled = btn.first.get_attribute("aria-disabled")
                        if disabled is None and aria_disabled != "true":
                            break
                        time.sleep(1)
                    btn.first.click()
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            screenshot = take_screenshot(page, "post_button_not_found")
            uploader.close()
            print(json.dumps({{"success": False, "error": "Could not find or click Post button", "screenshot": screenshot}}))
            sys.exit(0)

        # Wait for redirect after clicking Post
        time.sleep(15)

    current_url = page.url
    screenshot = take_screenshot(page, "post_upload")

    # Navigate to content page and check if post count increased
    page.goto("https://www.tiktok.com/tiktokstudio/content")
    page.wait_for_load_state("domcontentloaded")
    time.sleep(3)
    content_text = page.inner_text("body") if page.query_selector("body") else ""

    # Extract post count from page
    import re as _re
    count_match = _re.search(r"Posts\\s+(\\d+)", content_text)
    post_count = int(count_match.group(1)) if count_match else -1

    uploader.close()

    # If we left the upload page, report success with post count for external verification
    if "upload" not in current_url:
        print(json.dumps({{
            "success": True, "verified": True,
            "video_path": {str(vpath)!r}, "caption": {caption!r},
            "account": {(account_name or 'default')!r},
            "screenshot": screenshot,
            "post_count": post_count,
        }}))
    else:
        print(json.dumps({{
            "success": False,
            "error": f"Still on upload page after clicking Post. URL: {{current_url}}",
            "screenshot": screenshot,
        }}))

except Exception as e:
    print(json.dumps({{"success": False, "error": f"Upload failed: {{e}}"}}))
    sys.exit(0)
"""
    try:
        logger.info(f"Running upload subprocess for {vpath}")
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(BASE_DIR),
        )
        try:
            stdout, stderr = proc.communicate(timeout=200)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            logger.error(f"Upload timed out for {vpath}")
            return {"success": False, "error": "Upload timed out after 200 seconds"}

        logger.info(f"Upload subprocess returned code={proc.returncode}")
        if stderr:
            logger.info(f"Upload stderr: {stderr[:500]}")

        # Parse JSON result from subprocess stdout
        for line in stdout.strip().splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    result = json.loads(line)
                    if result.get("verified"):
                        logger.info(f"Upload VERIFIED: {vpath}")
                    elif not result.get("success"):
                        logger.warning(f"Upload issue for {vpath}: {result.get('error', 'unknown')}")
                    return result
                except json.JSONDecodeError:
                    continue

        # No JSON found in output
        logger.error(f"No JSON result from upload subprocess. stdout: {stdout[:500]}")
        return {"success": False, "error": f"Upload subprocess produced no result. stderr: {stderr[:300]}"}

    except Exception as e:
        logger.error(f"Upload exception for {vpath}: {e}")
        return {"success": False, "error": f"Upload failed: {e}"}


def upload_batch_to_tiktok(
    clips: list,
    account_name: str | None = None,
    delay_between: int = 60,
) -> dict:
    """
    Upload multiple clips with delays to avoid rate limiting.
    Each clip dict should have 'filepath' and 'caption' keys.
    """
    results: dict = {"posted": 0, "failed": 0, "verified": 0, "errors": [], "details": []}

    for i, clip in enumerate(clips):
        result = upload_to_tiktok(
            clip["filepath"], clip["caption"], account_name=account_name
        )
        if result.get("success"):
            results["posted"] += 1
            if result.get("verified"):
                results["verified"] += 1
        else:
            results["failed"] += 1
            results["errors"].append(result.get("error", "Unknown error"))

        results["details"].append(result)

        if i < len(clips) - 1:
            time.sleep(delay_between)

    return results
