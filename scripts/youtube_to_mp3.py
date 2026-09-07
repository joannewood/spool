#!/usr/bin/env python3
"""Download a YouTube video's audio track and save it locally as an MP3.

Usage:
    python3 scripts/youtube_to_mp3.py <youtube-url> [-o OUTPUT_DIR] [-q QUALITY]

Requires:
    - yt-dlp (pip install yt-dlp)
    - ffmpeg on PATH (e.g. `brew install ffmpeg` on macOS)
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    print(
        "error: yt-dlp is not installed. Install it with:\n"
        "    pip install yt-dlp",
        file=sys.stderr,
    )
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "-o",
        "--output-dir",
        default=".",
        help="Directory to save the MP3 in (default: current directory)",
    )
    parser.add_argument(
        "-q",
        "--quality",
        default="192",
        help="MP3 bitrate in kbps (default: 192)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if shutil.which("ffmpeg") is None:
        print(
            "error: ffmpeg is required but was not found on PATH. "
            "Install it with `brew install ffmpeg` (macOS) or your "
            "system's package manager.",
            file=sys.stderr,
        )
        sys.exit(1)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": args.quality,
            }
        ],
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(args.url, download=True)
    except yt_dlp.utils.DownloadError as e:
        print(f"error: failed to download video: {e}", file=sys.stderr)
        sys.exit(1)

    title = info.get("title", "audio")
    mp3_path = output_dir / f"{title}.mp3"
    print(f"Saved: {mp3_path}")


if __name__ == "__main__":
    main()
