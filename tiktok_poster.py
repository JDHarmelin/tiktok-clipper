"""Handles TikTok video uploads with post-upload verification."""
import time
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
    Uses the class-based TikTokUploader for page access after upload.
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

    try:
        from tiktok_uploader.upload import TikTokUploader

        uploader = TikTokUploader(cookies=str(cookies_abs), headless=True)

        logger.info(f"Starting upload: {vpath}")
        success = uploader.upload_video(
            filename=str(vpath),
            description=caption,
        )

        if not success:
            screenshot = _screenshot(uploader.page, "upload_failed")
            uploader.close()
            logger.error(f"upload_video returned False for {vpath}")
            return {
                "success": False,
                "error": "TikTok uploader reported failure",
                "screenshot": screenshot,
            }

        # The library said success — now actually verify
        logger.info(f"Library reported success, verifying upload for {vpath}")
        verification = _verify_upload(uploader.page, caption)

        uploader.close()

        if verification["verified"]:
            logger.info(f"Upload VERIFIED: {vpath}")
            return {
                "success": True,
                "verified": True,
                "video_path": str(vpath),
                "caption": caption,
                "account": account_name or "default",
            }
        else:
            logger.warning(
                f"Upload NOT verified for {vpath}: {verification['reason']}"
            )
            return {
                "success": False,
                "error": f"Upload unverified: {verification['reason']}",
                "screenshot": verification.get("screenshot"),
            }

    except ImportError:
        logger.error("tiktok-uploader not installed")
        return {"success": False, "error": "tiktok-uploader package not installed. Run: pip install tiktok-uploader"}

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Upload exception for {vpath}: {error_msg}")

        # Try to screenshot before giving up
        screenshot = None
        try:
            if "uploader" in dir() and hasattr(uploader, "page"):
                screenshot = _screenshot(uploader.page, "upload_exception")
                uploader.close()
        except Exception:
            pass

        if "cookie" in error_msg.lower() or "login" in error_msg.lower() or "auth" in error_msg.lower():
            return {
                "success": False,
                "error": "Cookie authentication failed. Re-export cookies from browser.",
                "screenshot": screenshot,
            }
        return {"success": False, "error": f"Upload failed: {error_msg}", "screenshot": screenshot}


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
