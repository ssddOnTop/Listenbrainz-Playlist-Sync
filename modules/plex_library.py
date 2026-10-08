"""Builds an ID index of the Plex music library.

No title search is used anywhere. Tracks are found by:
  * the MusicBrainz release-track id Plex stores on matched tracks (`mbid://...` guids), and
  * ISRCs read directly from the audio files' tags (optional, needs the music folder mounted read-only).

Album types (Plex "subformats" such as Live / Remix / DJ Mix) are collected so whole albums can be excluded.
"""
import os
from dataclasses import dataclass, field

from modules.logger_utils import logger

PAGE = 2000


@dataclass
class Track:
    rating_key: int
    title: str
    artist: str
    album: str
    album_key: int
    file: str
    bitrate: int
    track_ids: set = field(default_factory=set)  # MusicBrainz release-track ids
    isrcs: set = field(default_factory=set)
    album_types: set = field(default_factory=set)


class PlexLibrary:
    def __init__(self, server, section):
        self.server = server
        self.section = section
        self.tracks: dict[int, Track] = {}
        self.by_track_id: dict[str, set] = {}
        self.by_isrc: dict[str, set] = {}

    # ---------------------------------------------------------------- loading
    def _pages(self, libtype: int, extra: dict | None = None):
        start = 0
        while True:
            params = {
                "type": libtype,
                "includeGuids": 1,
                "X-Plex-Container-Start": start,
                "X-Plex-Container-Size": PAGE,
                **(extra or {}),
            }
            data = self.server.query(f"/library/sections/{self.section.key}/all", params=params)
            items = list(data)
            yield from items
            total = int(data.attrib.get("totalSize", data.attrib.get("size", len(items))))
            start += len(items)
            if not items or start >= total:
                break

    def _album_types(self) -> dict[int, set]:
        """Album ratingKey -> Plex album types (Live, Remix, ...). Album listings don't include
        subformats, so each type is queried through the section's `subformat` filter."""
        album_types: dict[int, set] = {}
        types = self.server.query(f"/library/sections/{self.section.key}/subformat", params={"type": 9})
        for d in types:
            key, title = d.attrib.get("key"), d.attrib.get("title", "")
            if not key:
                continue
            for el in self._pages(9, {"subformat": key}):
                album_types.setdefault(int(el.attrib["ratingKey"]), set()).add(title)
        return album_types

    def load(self) -> None:
        album_types = self._album_types()

        for el in self._pages(10):
            media = el.find("Media")
            part = media.find("Part") if media is not None else None
            album_key = int(el.attrib.get("parentRatingKey", 0) or 0)
            track = Track(
                rating_key=int(el.attrib["ratingKey"]),
                title=el.attrib.get("title", ""),
                artist=el.attrib.get("originalTitle") or el.attrib.get("grandparentTitle", ""),
                album=el.attrib.get("parentTitle", ""),
                album_key=album_key,
                file=part.attrib.get("file", "") if part is not None else "",
                bitrate=int(media.attrib.get("bitrate", 0) or 0) if media is not None else 0,
                album_types=album_types.get(album_key, set()),
            )
            for g in el.findall("Guid"):
                gid = g.attrib.get("id", "")
                if gid.startswith("mbid://"):
                    track.track_ids.add(gid[len("mbid://"):])
            self.tracks[track.rating_key] = track
            for tid in track.track_ids:
                self.by_track_id.setdefault(tid, set()).add(track.rating_key)

        with_mbid = sum(1 for t in self.tracks.values() if t.track_ids)
        logger.info(
            f"Plex index: {len(self.tracks)} tracks, {with_mbid} with MusicBrainz ids, "
            f"{len(album_types)} albums with a type (live/remix/compilation/...)"
        )

    # ------------------------------------------------------------------ ISRCs
    def load_isrcs(self, cache, path_map: dict, mode: str = "unmatched") -> None:
        """Reads ISRC tags from the files. mode: 'unmatched' (only tracks Plex has no MBID for), 'all', 'off'."""
        if mode == "off":
            return
        try:
            import mutagen
        except ImportError:
            logger.warning("mutagen not installed, skipping ISRC index")
            return

        todo = [t for t in self.tracks.values() if mode == "all" or not t.track_ids]
        logger.info(f"Reading ISRCs for {len(todo)} tracks (cached after the first run)...")
        unreadable = 0
        for n, track in enumerate(todo, 1):
            local = _map_path(track.file, path_map)
            try:
                st = os.stat(local)
            except OSError:
                unreadable += 1
                continue
            isrcs = cache.get_file_isrcs(local, st.st_mtime, st.st_size)
            if isrcs is None:
                isrcs = _read_isrcs(local, mutagen)
                cache.put_file_isrcs(local, st.st_mtime, st.st_size, isrcs)
            track.isrcs = isrcs
            for isrc in isrcs:
                self.by_isrc.setdefault(isrc, set()).add(track.rating_key)
            if n % 5000 == 0:
                logger.info(f"  ...{n}/{len(todo)}")
        if unreadable:
            logger.warning(
                f"{unreadable} files were not readable; check `path_map` and that the music folder is mounted"
            )
        logger.info(f"ISRC index: {len(self.by_isrc)} distinct ISRCs")

    # ---------------------------------------------------------------- lookups
    def find(self, track_ids, isrcs) -> list[Track]:
        keys = set()
        for tid in track_ids:
            keys |= self.by_track_id.get(tid, set())
        how = "mbid"
        if not keys:
            for isrc in isrcs:
                keys |= self.by_isrc.get(isrc.upper(), set())
            how = "isrc"
        found = [self.tracks[k] for k in keys]
        for t in found:
            t.matched_by = how
        return found


def _map_path(path: str, path_map: dict) -> str:
    for plex_prefix, local_prefix in (path_map or {}).items():
        if path.startswith(plex_prefix):
            return local_prefix + path[len(plex_prefix):]
    return path


def _read_isrcs(path: str, mutagen) -> set:
    try:
        audio = mutagen.File(path)
    except Exception:
        return set()
    if audio is None or audio.tags is None:
        return set()
    values = []
    tags = audio.tags
    try:
        if hasattr(tags, "getall"):  # ID3
            for frame in tags.getall("TSRC"):
                values += list(frame.text)
        elif "----:com.apple.iTunes:ISRC" in tags:  # MP4
            values += [v.decode("utf-8", "ignore") for v in tags["----:com.apple.iTunes:ISRC"]]
        else:  # Vorbis comments (FLAC/Ogg/Opus)
            for key in ("isrc", "ISRC"):
                if key in tags:
                    values += list(tags[key])
    except Exception:
        return set()
    out = set()
    for v in values:
        for part in str(v).replace(";", ",").replace("/", ",").split(","):
            part = part.strip().replace("-", "").upper()
            if len(part) == 12:
                out.add(part)
    return out
