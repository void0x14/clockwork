"""yt-dlp based subtitle downloader.

No YouTube auth required. FFmpeg must be installed for VTT→SRT conversion.
"""

import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

import yt_dlp


def _check_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        print(
            "[WARN] ffmpeg not found in PATH. Subtitle format conversion may fail.\n"
            "       Install: https://ffmpeg.org/download.html",
            file=sys.stderr,
        )


def _find_srt(video_dir: Path, video_id: str, lang_priority: List[str]) -> Optional[Path]:
    """Return the best SRT file in video_dir according to language priority."""
    all_srts = list(video_dir.glob("*.srt"))
    if not all_srts:
        return None

    # Prefer by language order
    for lang in lang_priority:
        for srt in all_srts:
            # yt-dlp names: VIDEO_ID.LANG.srt  (or .LANG.auto.srt for some configs)
            if f".{lang}." in srt.name or srt.name.endswith(f".{lang}.srt"):
                return srt

    return all_srts[0]


class SubtitleDownloader:
    def __init__(
        self,
        output_dir: str,
        lang_priority: List[str],
        prefer_manual: bool = True,
    ):
        _check_ffmpeg()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.lang_priority = lang_priority
        self.prefer_manual = prefer_manual

    # ---------------------------------------------------- single video ---------

    def download(self, video_url: str, video_id: str) -> Optional[Path]:
        """
        Download subtitles for one video.
        Returns Path to .srt file, or None if no subtitles found.
        Skips download if .srt already exists.
        """
        video_dir = self.output_dir / video_id
        video_dir.mkdir(exist_ok=True)

        existing = _find_srt(video_dir, video_id, self.lang_priority)
        if existing:
            return existing

        ydl_opts = {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "srt",
            "subtitleslangs": self.lang_priority,
            "skip_download": True,
            "outtmpl": str(video_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            # Convert VTT/other formats to SRT via FFmpeg
            "postprocessors": [
                {"key": "FFmpegSubtitlesConvertor", "format": "srt"}
            ],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
        except Exception:
            pass  # ignoreerrors handles most issues; we check files below

        return _find_srt(video_dir, video_id, self.lang_priority)

    # ---------------------------------------------------- channel batch --------

    def download_channel(self, channel_url: str) -> Dict[str, Optional[Path]]:
        """
        List all videos in channel via yt-dlp (no auth needed) and download subs.
        Returns {video_id: srt_path_or_None}.
        """
        video_ids = self._list_channel_videos(channel_url)
        results: Dict[str, Optional[Path]] = {}
        for vid_id in video_ids:
            url = f"https://www.youtube.com/watch?v={vid_id}"
            results[vid_id] = self.download(url, vid_id)
        return results

    def _list_channel_videos(self, channel_url: str) -> List[str]:
        ydl_opts = {
            "extract_flat": "in_playlist",
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
        }
        # Append /videos to land on the videos tab
        url = channel_url.rstrip("/") + "/videos"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return []

        entries = info.get("entries") or []
        return [e["id"] for e in entries if e and e.get("id")]
