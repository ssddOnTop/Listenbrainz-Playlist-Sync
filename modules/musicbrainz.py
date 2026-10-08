"""Minimal MusicBrainz client.

Resolves a recording MBID (what ListenBrainz playlists contain) into:
  * the canonical recording id (MusicBrainz merges ids over time),
  * every release-track id of that recording (what Plex stores as `mbid://` guids on tracks),
  * its ISRCs (what purchased files carry in their tags),
  * its relationships (used to detect covers, remixes, live recordings, karaoke).

Only read-only GET requests are made. Requests are rate limited to ~1/s as the
MusicBrainz API requires, and results are cached.
"""
import time

import requests

from modules.logger_utils import logger

BASE = "https://musicbrainz.org/ws/2"
LOOKUP_RELEASE_CAP = 25  # recording lookups embed at most 25 releases
MAX_BROWSE_RELEASES = 1000


class MusicBrainz:
    def __init__(self, cache, contact: str, ttl_days: float = 30):
        self.cache = cache
        self.ttl = ttl_days * 86400
        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"ListenBrainzPlaylistSync/2.0 ( {contact or 'unknown'} )"
        self._last = 0.0

    def _get(self, path: str, params: dict):
        params = {**params, "fmt": "json"}
        for attempt in range(6):
            wait = 1.1 - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.session.get(f"{BASE}/{path}", params=params, timeout=30)
            except requests.RequestException as e:
                logger.warning(f"MusicBrainz request failed ({e}), retrying...")
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"MusicBrainz request kept failing: {path}")

    def recording(self, recording_id: str) -> dict | None:
        """Returns a summary dict for a recording, or None if MusicBrainz doesn't know it."""
        cached = self.cache.get("mb_recording", recording_id, self.ttl)
        if cached is not None:
            return cached or None

        data = self._get(
            f"recording/{recording_id}",
            {"inc": "isrcs+releases+media+work-rels+recording-rels+artist-credits"},
        )
        if data is None:
            self.cache.put("mb_recording", recording_id, {})
            return None

        canonical = data["id"]
        track_ids = {
            track["id"]
            for release in data.get("releases", [])
            for medium in release.get("media", [])
            for track in medium.get("tracks", []) or []
        }
        if len(data.get("releases", [])) >= LOOKUP_RELEASE_CAP:
            track_ids |= self._browse_track_ids(canonical)

        info = {
            "id": canonical,
            "title": data.get("title", ""),
            "artist": "".join(
                c.get("name", "") + c.get("joinphrase", "") for c in data.get("artist-credit", [])
            ),
            "disambiguation": data.get("disambiguation", ""),
            "isrcs": sorted(set(data.get("isrcs", []))),
            "track_ids": sorted(track_ids),
            "relations": [
                {
                    "type": rel.get("type", ""),
                    "direction": rel.get("direction", ""),
                    "attributes": rel.get("attributes", []),
                    "target_type": rel.get("target-type", ""),
                }
                for rel in data.get("relations", [])
            ],
        }
        self.cache.put("mb_recording", recording_id, info)
        if canonical != recording_id:
            self.cache.put("mb_recording", canonical, info)
        return info

    def _browse_track_ids(self, recording_id: str) -> set:
        """Pages through every release of a recording (lookups are capped at 25 releases)."""
        track_ids, offset = set(), 0
        while offset < MAX_BROWSE_RELEASES:
            data = self._get(
                "release",
                {"recording": recording_id, "inc": "media+recordings", "limit": 100, "offset": offset},
            )
            if not data or not data.get("releases"):
                break
            for release in data["releases"]:
                for medium in release.get("media", []):
                    for track in medium.get("tracks", []) or []:
                        if track.get("recording", {}).get("id") == recording_id:
                            track_ids.add(track["id"])
            offset += len(data["releases"])
            if offset >= data.get("release-count", 0):
                break
        return track_ids
