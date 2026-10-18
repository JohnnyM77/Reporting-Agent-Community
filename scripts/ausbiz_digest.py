#!/usr/bin/env python3
"""
One-off script to fetch, transcribe, analyse and email an AusBiz video.

Run on Windows with:
    python scripts/ausbiz_digest.py

Set environment variables:
    NED_VIDEO_URL=<url>
    NED_VIDEO_TITLE_OVERRIDE=<optional title>
    OPENAI_API_KEY=<your key>
    ANTHROPIC_API_KEY=<your key>
    EMAIL_FROM=<your email>
    EMAIL_TO=<recipient>
    EMAIL_APP_PASSWORD=<app password>
"""

import os
import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ned.main import run_video_digest

if __name__ == "__main__":
    video_url = os.environ.get("NED_VIDEO_URL", "").strip()
    title_override = os.environ.get("NED_VIDEO_TITLE_OVERRIDE", "").strip()

    if not video_url:
        print("Error: NED_VIDEO_URL environment variable not set")
        print("\nExample:")
        print('  set NED_VIDEO_URL="https://ausbiz.com.au/media/wealthy-wise-the-most-dangerous-number-in-investing?videoId=51205"')
        print('  set OPENAI_API_KEY="sk-..."')
        print('  set ANTHROPIC_API_KEY="sk-ant-..."')
        print('  python scripts/ausbiz_digest.py')
        sys.exit(1)

    exit_code = run_video_digest(video_url, title_override)
    sys.exit(exit_code)
