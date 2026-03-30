"""
Quick test script to debug a single TikTok upload with verification.
Usage: python test_upload.py [clip_path] [account_name]
"""
import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

from tiktok_poster import upload_to_tiktok, list_accounts

def main():
    print("=== TikTok Upload Test ===\n")

    # Show registered accounts
    accounts = list_accounts()
    print(f"Registered accounts: {accounts}\n")

    # Get clip path
    if len(sys.argv) >= 2:
        clip_path = sys.argv[1]
    else:
        # Pick the first clip in ./clips/
        from pathlib import Path
        clips = sorted(Path("clips").glob("*.mp4"))
        if not clips:
            print("No clips found in ./clips/. Pass a path as argument.")
            sys.exit(1)
        clip_path = str(clips[0])
        print(f"Auto-selected: {clip_path}")

    # Get account
    account = sys.argv[2] if len(sys.argv) >= 3 else "default"
    print(f"Account: {account}")
    print(f"Clip: {clip_path}")
    print(f"\nStarting upload...\n")

    result = upload_to_tiktok(
        video_path=clip_path,
        caption="Test upload - please ignore #test",
        account_name=account,
    )

    print(f"\n=== Result ===")
    print(json.dumps(result, indent=2, default=str))

    if result.get("screenshot"):
        print(f"\nScreenshot saved: {result['screenshot']}")

    if result.get("success") and result.get("verified"):
        print("\nUpload VERIFIED - video is live on TikTok")
    elif result.get("success"):
        print("\nUpload reported success but NOT verified")
    else:
        print(f"\nUpload FAILED: {result.get('error')}")


if __name__ == "__main__":
    main()
