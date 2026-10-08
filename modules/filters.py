"""Decides whether a matched track may go into a playlist.

Three independent layers, all configurable:
  1. MusicBrainz relationships of the recording (authoritative):
     cover / live / karaoke / instrumental performances, remixes, edits, DJ-mixes, mash-ups.
  2. Plex album type ("subformat") of the file's album, e.g. Live, Remix, DJ Mix.
  3. Title/album keyword patterns as a safety net for data MusicBrainz is missing,
     plus explicit per-track exclusions and low user ratings.
"""
import re

DEFAULTS = {
    "exclude_covers": True,
    "exclude_remixes": True,
    "exclude_live": True,
    "exclude_karaoke": True,
    "exclude_instrumental": False,
    # Edits (radio/single/album edits) are the original artist's own recording, often the canonical
    # version (e.g. Michael Jackson's "Billie Jean" album/single version), so they are kept by default.
    "exclude_edits": False,
    "exclude_album_types": ["Live", "Remix", "DJ Mix"],
    "exclude_title_patterns": [
        r"\bremix(ed)?\b",
        r"\b(re-?edit|rework|bootleg|mash-?up|vip mix|club mix|extended mix|dub mix)\b",
        r"\bsped up\b|\bslowed\b|\bnightcore\b|\b8d audio\b",
        r"\bcover\b|\bkaraoke\b|\bin the style of\b|\btribute to\b",
        r"[\(\[-]\s*live\b|\blive (at|from|in|on)\b",
    ],
    "exclude_rating_keys": [],
    "exclude_rating_at_or_below": 1,  # stars (0 disables); 1 = tracks rated 1 star (or half) are never added
}

# Recording -> work "performance" attributes that mean "not the original studio recording"
_PERFORMANCE_FLAGS = {
    "cover": "exclude_covers",
    "live": "exclude_live",
    "karaoke": "exclude_karaoke",
    "instrumental": "exclude_instrumental",
}
# Recording -> recording relationships where *this* recording is derived from another one
_DERIVED_TYPES = {"remix", "DJ-mix", "mashes up", "compilation"}


class Filters:
    def __init__(self, cfg: dict | None):
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.album_types = {a.lower() for a in self.cfg["exclude_album_types"] or []}
        self.patterns = [re.compile(p, re.I) for p in self.cfg["exclude_title_patterns"] or []]
        self.rating_keys = {int(k) for k in self.cfg["exclude_rating_keys"] or []}

    def recording_reason(self, rec: dict) -> str | None:
        """Reason to reject a MusicBrainz recording, or None if it's fine."""
        for rel in rec.get("relations", []):
            if rel["target_type"] == "work" and rel["type"] == "performance":
                for attr in rel.get("attributes", []):
                    key = _PERFORMANCE_FLAGS.get(attr)
                    if key and self.cfg[key]:
                        return f"MusicBrainz: {attr} performance"
            if rel["target_type"] == "recording" and rel["direction"] == "forward":
                if self.cfg["exclude_remixes"] and rel["type"] in _DERIVED_TYPES:
                    return f"MusicBrainz: {rel['type']} of another recording"
                if self.cfg["exclude_edits"] and rel["type"] == "edit":
                    return "MusicBrainz: edit of another recording"
        if self.cfg["exclude_live"] and rec.get("disambiguation", "").lower().startswith("live"):
            return "MusicBrainz: live recording"
        return None

    def track_reason(self, track) -> str | None:
        """Reason to reject a Plex track, or None if it's fine."""
        if track.rating_key in self.rating_keys:
            return "excluded in config"
        bad_types = {t.lower() for t in track.album_types} & self.album_types
        if bad_types:
            return f"Plex album type: {', '.join(sorted(bad_types))}"
        for p in self.patterns:
            if p.search(track.title) or p.search(track.album):
                return f"title/album matches /{p.pattern}/"
        return None
