# ned/video_transcript_fetcher.py
#
# Generic video transcript fetcher for any accessible video URL.
#
# Uses Playwright to download video via headless Chrome, extracts audio with
# ffmpeg, and transcribes with Whisper. Falls back to direct HTTP download if
# Playwright is not available (e.g., in local dev without Chrome).
#
# Intended for financial videos (AusBiz, etc.) where the video URL might be:
# - Behind a JavaScript-rendered player
# - Geo-blocked from cloud IPs but accessible from local networks
# - Served via a JavaScript app that needs a real browser session

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import requests

from ned.youtube_transcript_fetcher import TranscriptResult, TranscriptError
from ned.podcast_transcript_fetcher import (
    _WHISPER_MAX_BYTES,
    _COMPRESSED_BITRATE,
    _COMPRESSED_SAMPLE_RATE,
    _CHUNK_SECONDS,
    _HTTP_TIMEOUT,
    _USER_AGENT,
    _MAX_WHISPER_ATTEMPTS,
    _RETRY_BACKOFF_SECONDS,
)

import time
import json


def fetch_video_transcript(
    video_url: str,
    title_override: str = "",
) -> TranscriptResult:
    """Download a video from any URL, extract audio, transcribe with Whisper.

    Args:
        video_url: URL to the video (may be behind JavaScript player or network-restricted)
        title_override: Optional title to use instead of extracting from page

    Returns:
        TranscriptResult with the transcribed text and segments

    Raises:
        TranscriptError: if download, extraction, or transcription fails
    """

    # Try Playwright download first (for JS-rendered pages, network-restricted)
    audio_file = None
    try:
        audio_file = _download_video_via_playwright(video_url)
        print(f"[ned/video] Downloaded video via Playwright")
    except Exception as exc:
        print(f"[ned/video] Playwright download failed ({exc}); trying direct HTTP")
        try:
            audio_file = _download_video_direct(video_url)
            print(f"[ned/video] Downloaded video via direct HTTP")
        except Exception as exc2:
            raise TranscriptError(f"Could not download video: {exc2}")

    if not audio_file or not audio_file.exists():
        raise TranscriptError("Video download produced no file")

    try:
        # Compress audio for Whisper
        compressed = _compress_audio(audio_file)
        print(f"[ned/video] Compressed audio: {compressed.stat().st_size / 1024 / 1024:.1f} MB")

        # Transcribe
        transcript_text, segments = _transcribe_with_whisper(compressed)

        # Extract title from URL or use override
        title = title_override or _extract_title_from_url(video_url)

        result = TranscriptResult(
            video_id=_slugify_url(video_url),
            plain_text=transcript_text,
            segments=segments,
            title=title,
            is_generated=True,  # Always Whisper-generated for video
        )
        return result
    finally:
        # Cleanup temporary files
        if audio_file.exists():
            audio_file.unlink()
        if 'compressed' in locals() and compressed.exists():
            compressed.unlink()


def _download_video_via_playwright(video_url: str) -> Path:
    """Use Playwright + Chrome to download video from a potentially JS-rendered page.

    This is needed for pages that serve video via JavaScript players, or for
    content behind geo-IP or corporate network restrictions that only work from
    a real browser session.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise TranscriptError("Playwright not installed")

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        output_path = Path(tmp.name)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context()
            page = context.new_page()

            # Intercept video responses
            video_url_found = [None]
            def handle_response(response):
                if response.status == 200 and any(
                    ext in response.url.lower()
                    for ext in ['.mp4', '.webm', '.m4a', '.mov', '.m3u8', '.mpd']
                ):
                    video_url_found[0] = response.url

            page.on("response", handle_response)
            page.goto(video_url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)  # Give any lazy-loaded videos time to load

            # If not found via intercept, try extracting from page using JavaScript
            if not video_url_found[0]:
                try:
                    # Use JavaScript to find video elements and extract src
                    video_url_found[0] = page.evaluate("""() => {
                        // Try <video> tag with <source> children
                        let sources = document.querySelectorAll('video source');
                        for (let source of sources) {
                            let src = source.src || source.getAttribute('src');
                            if (src && (src.includes('.mp4') || src.includes('.m3u8'))) {
                                return src;
                            }
                        }

                        // Try <video> tag src attribute directly
                        let videos = document.querySelectorAll('video');
                        for (let video of videos) {
                            let src = video.src || video.getAttribute('src');
                            if (src && (src.includes('.mp4') || src.includes('.m3u8'))) {
                                return src;
                            }
                        }

                        // Try data attributes and common JS patterns
                        let pageText = document.documentElement.outerHTML;
                        let matches = [
                            pageText.match(/"src":"([^"]*\.mp4[^"]*)"/),
                            pageText.match(/"url":"([^"]*\.mp4[^"]*)"/),
                            pageText.match(/src="([^"]*\.mp4[^"]*)"/) ,
                            pageText.match(/"videoUrl":"([^"]*)"/),
                            pageText.match(/data-video-url="([^"]*)"/),
                        ];

                        for (let match of matches) {
                            if (match && match[1]) return match[1];
                        }

                        return null;
                    }""")
                except Exception as e:
                    print(f"[ned/video] JavaScript video extraction failed: {e}")
                    # Fall back to regex on page content
                    page_content = page.content()
                    import re
                    for pattern in [
                        r'"src":"([^"]*\.mp4[^"]*)"',
                        r'src="([^"]*\.mp4[^"]*)"',
                        r'"url":"([^"]*\.mp4[^"]*)"',
                    ]:
                        match = re.search(pattern, page_content)
                        if match:
                            video_url_found[0] = match.group(1)
                            if video_url_found[0].startswith('http'):
                                break

            browser.close()

            if video_url_found[0]:
                # Download the intercepted video
                return _download_url_to_file(video_url_found[0], output_path)
            else:
                raise TranscriptError("Could not find video URL in page")
    except Exception as exc:
        if output_path.exists():
            output_path.unlink()
        raise


def _download_video_direct(video_url: str) -> Path:
    """Direct HTTP download of video file (for direct .mp4 URLs and accessible CDNs)."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        output_path = Path(tmp.name)

    try:
        return _download_url_to_file(video_url, output_path)
    except Exception:
        if output_path.exists():
            output_path.unlink()
        raise


def _download_url_to_file(url: str, output_path: Path) -> Path:
    """Download URL to file with streaming and progress."""
    response = requests.get(url, stream=True, timeout=_HTTP_TIMEOUT, headers={"User-Agent": _USER_AGENT})
    response.raise_for_status()

    total_size = int(response.headers.get('content-length', 0))
    downloaded = 0

    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total_size:
                    pct = (downloaded / total_size) * 100
                    print(f"[ned/video] Download: {pct:.0f}% ({downloaded / 1024 / 1024:.1f} MB)")

    return output_path


def _compress_audio(video_file: Path) -> Path:
    """Extract and compress audio for Whisper using ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".opus", delete=False) as tmp:
        output_path = Path(tmp.name)

    try:
        subprocess.run(
            [
                "ffmpeg", "-i", str(video_file),
                "-vn",  # No video
                "-acodec", "libopus",
                "-b:a", _COMPRESSED_BITRATE,
                "-ar", _COMPRESSED_SAMPLE_RATE,
                str(output_path),
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
        return output_path
    except subprocess.CalledProcessError as exc:
        if output_path.exists():
            output_path.unlink()
        raise TranscriptError(f"ffmpeg failed: {exc.stderr.decode() if exc.stderr else exc}")
    except FileNotFoundError:
        raise TranscriptError("ffmpeg not found; please install it (apt-get install ffmpeg on Linux, brew install ffmpeg on macOS)")


def _transcribe_with_whisper(audio_file: Path) -> tuple[str, list[dict]]:
    """Transcribe audio file using OpenAI Whisper API.

    Handles chunking if file is too large.

    Returns:
        (transcript_text, segments) where segments is a list of {text, start, duration}
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise TranscriptError("OPENAI_API_KEY not set")

    file_size = audio_file.stat().st_size

    if file_size > _WHISPER_MAX_BYTES:
        print(f"[ned/video] Audio is {file_size / 1024 / 1024:.1f} MB; chunking into {_CHUNK_SECONDS}s pieces")
        return _transcribe_chunked(audio_file, api_key)

    return _transcribe_single_file(audio_file, api_key)


def _transcribe_single_file(audio_file: Path, api_key: str) -> tuple[str, list[dict]]:
    """Transcribe a single audio file with Whisper."""
    import openai

    client = openai.OpenAI(api_key=api_key)

    for attempt in range(_MAX_WHISPER_ATTEMPTS):
        try:
            with open(audio_file, 'rb') as f:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="verbose_json",
                )

            text = response.text
            # Whisper's verbose response includes `segments` but no `start`/`duration`
            # Construct simple segments from the text
            segments = [{"text": text, "start": 0.0, "duration": 0.0}]

            return text, segments
        except Exception as exc:
            if attempt < _MAX_WHISPER_ATTEMPTS - 1:
                wait = _RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)]
                print(f"[ned/video] Whisper attempt {attempt + 1} failed ({exc}); retrying in {wait}s")
                time.sleep(wait)
            else:
                raise TranscriptError(f"Whisper transcription failed after {_MAX_WHISPER_ATTEMPTS} attempts: {exc}")


def _transcribe_chunked(audio_file: Path, api_key: str) -> tuple[str, list[dict]]:
    """Split large audio into chunks, transcribe each, and concatenate."""
    import openai

    client = openai.OpenAI(api_key=api_key)

    # Use ffmpeg to split audio into chunks
    chunks = _split_audio_into_chunks(audio_file)

    all_text = []
    all_segments = []
    current_offset = 0.0

    for i, chunk_file in enumerate(chunks, 1):
        print(f"[ned/video] Transcribing chunk {i}/{len(chunks)}")
        try:
            with open(chunk_file, 'rb') as f:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="verbose_json",
                )

            text = response.text
            all_text.append(text)
            all_segments.append({
                "text": text,
                "start": current_offset,
                "duration": 0.0,  # We don't have precise timing across chunks
            })
            current_offset += _CHUNK_SECONDS
        finally:
            chunk_file.unlink()

    return " ".join(all_text), all_segments


def _split_audio_into_chunks(audio_file: Path) -> list[Path]:
    """Split audio file into ~20-minute chunks using ffmpeg."""
    chunks = []
    tmp_dir = Path(tempfile.gettempdir())

    # Get duration
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1:nokey=1",
            str(audio_file),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        raise TranscriptError("Could not determine audio duration")

    num_chunks = (int(duration) + _CHUNK_SECONDS - 1) // _CHUNK_SECONDS

    for i in range(num_chunks):
        start_time = i * _CHUNK_SECONDS
        chunk_file = tmp_dir / f"chunk_{i:03d}.opus"

        subprocess.run(
            [
                "ffmpeg", "-i", str(audio_file),
                "-ss", str(start_time),
                "-to", str(start_time + _CHUNK_SECONDS),
                "-c", "copy",
                str(chunk_file),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        chunks.append(chunk_file)

    return chunks


def _extract_title_from_url(url: str) -> str:
    """Try to extract a sensible title from the URL."""
    # Remove query params and fragments
    path = url.split('?')[0].split('#')[0]

    # Try to get the last path component
    parts = path.rstrip('/').split('/')
    if parts:
        candidate = parts[-1]
        # Decode URL encoding and clean up
        candidate = candidate.replace('%20', ' ').replace('-', ' ').replace('_', ' ')
        if candidate and len(candidate) > 3:
            return candidate.title()

    return url


def _slugify_url(url: str) -> str:
    """Create a slug from URL for use as video_id."""
    slug = re.sub(r'[^a-z0-9]+', '-', url.lower())
    return slug.strip('-')[:50]
