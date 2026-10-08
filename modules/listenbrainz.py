"""Read-only ListenBrainz client for the 'Created for you' playlists."""
import re

import requests

BASE = "https://api.listenbrainz.org/1"

# ListenBrainz `source_patch` -> default Plex playlist name
PLAYLISTS = {
    "weekly-jams": "Weekly Jams",
    "daily-jams": "Daily Jams",
    "weekly-exploration": "Weekly Exploration",
}
_TITLE_PREFIX = {
    "weekly-jams": "Weekly Jams for",
    "daily-jams": "Daily Jams for",
    "weekly-exploration": "Weekly Exploration for",
}


class ListenBrainz:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "ListenBrainzPlaylistSync/2.0"

    def _get(self, path: str, token: str | None = None, params: dict | None = None):
        headers = {"Authorization": f"Token {token}"} if token else {}
        r = self.session.get(f"{BASE}/{path}", headers=headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def latest_created_for(self, username: str, patch: str, token: str | None = None) -> dict | None:
        """Newest 'created for' playlist of the given kind (e.g. 'weekly-jams'), or None."""
        data = self._get(f"user/{username}/playlists/createdfor", token, {"count": 100})
        candidates = []
        for item in data.get("playlists", []):
            pl = item["playlist"]
            ext = pl.get("extension", {}).get("https://musicbrainz.org/doc/jspf#playlist", {})
            source = ext.get("additional_metadata", {}).get("algorithm_metadata", {}).get("source_patch")
            if source == patch or (source is None and pl.get("title", "").startswith(_TITLE_PREFIX[patch])):
                candidates.append(pl)
        if not candidates:
            return None
        newest = max(candidates, key=lambda p: p.get("date", ""))
        return {
            "id": newest["identifier"].rstrip("/").split("/")[-1],
            "title": newest.get("title", ""),
            "date": newest.get("date", ""),
            "annotation": _strip_html(newest.get("annotation", "")),
        }

    def playlist_tracks(self, playlist_id: str, token: str | None = None) -> list[dict]:
        data = self._get(f"playlist/{playlist_id}", token)
        tracks = []
        for t in data.get("playlist", {}).get("track", []):
            ids = [i.rstrip("/").split("/")[-1] for i in t.get("identifier", []) if "/recording/" in i]
            if not ids:
                continue
            tracks.append({"recording_id": ids[0], "title": t.get("title", ""), "artist": t.get("creator", "")})
        return tracks


def _strip_html(text: str) -> str:
    return " ".join(re.sub(r"<[^<]+?>", "", text or "").split())
