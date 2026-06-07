"""YouTube Data API v3 wrapper.

Auth:  OAuth 2.0 (installed-app flow, browser-based, token cached to disk)
Quota: Uses playlistItems.list (1 unit/page) instead of search.list (100 units/call).
       videos.list   = 1 unit/call (batched 50/call)
       videos.update = 50 units/call
"""

import json
import re
import time
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
MAX_DESC_BYTES = 4900  # YouTube hard limit is 5000 bytes, leave margin


class YouTubeAPI:
    def __init__(self, client_secrets: str, token_file: str):
        self._secrets = client_secrets
        self._token_file = token_file
        self._svc = None  # built after authenticate()

    # ------------------------------------------------------------------ auth --

    def authenticate(self) -> None:
        creds: Optional[Credentials] = None

        if Path(self._token_file).exists():
            creds = Credentials.from_authorized_user_file(self._token_file, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not Path(self._secrets).exists():
                    raise FileNotFoundError(
                        f"'{self._secrets}' not found.\n"
                        "  1. console.cloud.google.com → New Project\n"
                        "  2. APIs & Services → Library → YouTube Data API v3 → Enable\n"
                        "  3. APIs & Services → Credentials → Create OAuth 2.0 Client ID\n"
                        "     Application type: Desktop app\n"
                        "  4. Download JSON → rename to client_secrets.json"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(self._secrets, SCOPES)
                creds = flow.run_local_server(port=0)

            Path(self._token_file).write_text(creds.to_json(), encoding="utf-8")

        self._svc = build("youtube", "v3", credentials=creds)

    def _ensure_auth(self) -> None:
        if self._svc is None:
            raise RuntimeError("Call authenticate() first.")

    # ---------------------------------------------------------------- channel -

    def resolve_channel_id(self, channel_url: str) -> str:
        """Resolve @handle or /channel/ID URLs to a channel ID."""
        self._ensure_auth()

        if "/channel/" in channel_url:
            return channel_url.split("/channel/")[1].split("/")[0]

        handle = re.search(r"@([\w.-]+)", channel_url)
        if handle:
            resp = self._svc.channels().list(
                part="id", forHandle=handle.group(1)
            ).execute()
            items = resp.get("items", [])
            if items:
                return items[0]["id"]

        raise ValueError(f"Cannot resolve channel ID from: {channel_url}")

    def get_uploads_playlist_id(self, channel_id: str) -> str:
        resp = self._svc.channels().list(
            part="contentDetails", id=channel_id
        ).execute()
        return resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def iter_playlist_video_ids(self, playlist_id: str) -> Iterator[str]:
        """Yields video IDs from a playlist, page by page (1 unit/page)."""
        page_token = None
        while True:
            resp = self._svc.playlistItems().list(
                part="contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=page_token,
            ).execute()
            for item in resp.get("items", []):
                yield item["contentDetails"]["videoId"]
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    def batch_video_details(self, video_ids: List[str]) -> List[Dict]:
        """Fetch snippet for up to 50 videos per API call (1 unit/call)."""
        self._ensure_auth()
        results = []
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i : i + 50]
            resp = self._svc.videos().list(
                part="snippet,contentDetails",
                id=",".join(chunk),
            ).execute()
            for item in resp.get("items", []):
                vid_id = item["id"]
                snip = item["snippet"]
                results.append(
                    {
                        "id": vid_id,
                        "title": snip["title"],
                        "description": snip.get("description", ""),
                        "url": f"https://www.youtube.com/watch?v={vid_id}",
                        "duration": item["contentDetails"]["duration"],
                        "_snippet": snip,  # keep for update
                    }
                )
        return results

    def get_channel_videos(self, channel_url: str) -> List[Dict]:
        self._ensure_auth()
        channel_id = self.resolve_channel_id(channel_url)
        playlist_id = self.get_uploads_playlist_id(channel_id)
        video_ids = list(self.iter_playlist_video_ids(playlist_id))
        return self.batch_video_details(video_ids)

    def get_video(self, video_id: str) -> Optional[Dict]:
        videos = self.batch_video_details([video_id])
        return videos[0] if videos else None

    # -------------------------------------------------------------- description

    def update_description(
        self, video: Dict, new_description: str, dry_run: bool = False
    ) -> bool:
        """Update a video's description. `video` must be a dict from batch_video_details."""
        self._ensure_auth()

        # Enforce YouTube 5000-byte limit
        encoded = new_description.encode("utf-8")
        if len(encoded) > MAX_DESC_BYTES:
            new_description = encoded[:MAX_DESC_BYTES].decode("utf-8", errors="ignore")

        if dry_run:
            return True

        snippet = dict(video["_snippet"])
        snippet["description"] = new_description

        try:
            self._svc.videos().update(
                part="snippet",
                body={"id": video["id"], "snippet": snippet},
            ).execute()
            return True
        except HttpError as e:
            raise RuntimeError(f"YouTube API error updating {video['id']}: {e}") from e

    # ----------------------------------------------------------- chapter check -

    @staticmethod
    def has_chapters(description: str) -> bool:
        """True if description already contains a YouTube-compatible chapter block."""
        pattern = re.compile(r"^(?:\d+:)?\d+:\d{2}\s+\S", re.MULTILINE)
        return len(pattern.findall(description)) >= 3
