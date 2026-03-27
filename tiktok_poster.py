"""Handles TikTok video uploads. Supports multiple accounts via account_name parameter."""
import time
import subprocess
import sys
import json
import logging
from pathlib import Path
from config import TIKTOK_COOKIES_PATH, BASE_DIR

logger = logging.getLogger(__name__)

# Account registry: maps account names to cookie file paths.
# Default account uses TIKTOK_COOKIES_PATH from .env.
# Add more accounts by placing cookie files in the project root
# and registering them here or via register_account().
_accounts: dict[str, str] = {
    "default": TIKTOK_COOKIES_PATH,
}


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


def upload_to_tiktok(
    video_path: str,
    caption: str,
    account_name: str | None = None,
) -> dict:
    """
    Upload a single video to TikTok with caption.
    Uses tiktok-uploader (Playwright-based browser automation).
    Pass account_name to target a specific TikTok account.
    """
    logger.info(f"upload_to_tiktok called: video_path={video_path}, account={account_name}")

    # Resolve to absolute path from BASE_DIR if relative
    vpath = Path(video_path)
    if not vpath.is_absolute():
        vpath = BASE_DIR / vpath
    video_path = str(vpath)

    if not vpath.exists():
        logger.error(f"Video not found: {video_path}")
        return {"success": False, "error": f"Video not found: {video_path}"}

    try:
        cookies_path = _get_cookies_path(account_name)
    except ValueError as e:
        logger.error(f"Account lookup failed: {e}")
        return {"success": False, "error": str(e)}
    cookies_abs = Path(cookies_path)
    if not cookies_abs.is_absolute():
        cookies_abs = BASE_DIR / cookies_abs
    cookies_path = str(cookies_abs)

    if not cookies_abs.exists():
        logger.error(f"Cookies not found: {cookies_path}")
        return {
            "success": False,
            "error": f"TikTok cookies file not found at {cookies_path}. Export cookies from browser.",
        }

    # Run upload in a separate process to avoid Playwright/asyncio conflicts
    script = f"""
import sys, signal
signal.alarm(150)  # Hard kill after 150s
try:
    from tiktok_uploader.upload import upload_video
    upload_video(
        filename={video_path!r},
        description={caption!r},
        cookies={cookies_path!r},
        headless=True,
    )
    print("UPLOAD_SUCCESS")
except Exception as e:
    print(f"UPLOAD_ERROR: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
    try:
        logger.info(f"Running upload subprocess for {video_path}")
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(BASE_DIR),
        )
        try:
            stdout, stderr = proc.communicate(timeout=160)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            logger.error(f"Upload timed out for {video_path}, killed subprocess")
            return {"success": False, "error": "Upload timed out after 160 seconds"}

        logger.info(f"Upload subprocess returned code={proc.returncode}")
        logger.info(f"Upload stdout: {stdout[:500]}")
        if stderr:
            logger.info(f"Upload stderr: {stderr[:500]}")

        if proc.returncode == 0 and "UPLOAD_SUCCESS" in stdout:
            logger.info(f"Upload successful: {video_path}")
            return {
                "success": True,
                "video_path": video_path,
                "caption": caption,
                "account": account_name or "default",
            }

        error_msg = stderr.strip() or stdout.strip()
        if "cookie" in error_msg.lower() or "login" in error_msg.lower():
            logger.error(f"Cookie auth failed for {video_path}")
            return {
                "success": False,
                "error": "Cookie authentication failed. Re-export cookies from browser.",
            }
        logger.error(f"Upload failed for {video_path}: {error_msg[-300:]}")
        return {"success": False, "error": f"Upload failed: {error_msg[-300:]}"}
    except Exception as e:
        logger.error(f"Upload exception for {video_path}: {e}")
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
    results = {"posted": 0, "failed": 0, "errors": [], "details": []}

    for i, clip in enumerate(clips):
        result = upload_to_tiktok(
            clip["filepath"], clip["caption"], account_name=account_name
        )
        if result["success"]:
            results["posted"] += 1
        else:
            results["failed"] += 1
            results["errors"].append(result["error"])

        results["details"].append(result)

        if i < len(clips) - 1:
            time.sleep(delay_between)

    return results
