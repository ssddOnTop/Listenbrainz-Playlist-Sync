"""Matches ListenBrainz playlists to Plex tracks by ID and writes the Plex playlists."""
import re
import unicodedata

import plexapi.exceptions

from modules.listenbrainz import PLAYLISTS
from modules.logger_utils import logger

MARKER = "[lb-sync]"


def _norm_tokens(name: str) -> set:
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    stop = {"the", "and", "feat", "ft", "with", "his", "her", "orchestra", "band", "trio", "quartet", "x"}
    return {t for t in re.findall(r"[a-z0-9]+", name) if len(t) > 1 and t not in stop}


def artist_mismatch(mb_artist: str, plex_artist: str) -> bool:
    """True only when both names are comparable and share nothing (e.g. a cover band matched by mistake)."""
    a, b = _norm_tokens(mb_artist), _norm_tokens(plex_artist)
    if not a or not b:  # non-Latin scripts etc.: can't judge, don't reject
        return False
    return not (a & b)


class Syncer:
    def __init__(self, library, mb, lb, filters, dry_run=False, require_artist_match=True):
        self.library = library
        self.mb = mb
        self.lb = lb
        self.filters = filters
        self.dry_run = dry_run
        self.require_artist_match = require_artist_match

    def resolve(self, lb_tracks, low_rated: set):
        """Returns (plex tracks in order, report rows)."""
        chosen, seen, report = [], set(), []
        for t in lb_tracks:
            label = f"{t['artist']} - {t['title']}"
            rec = self.mb.recording(t["recording_id"])
            if rec is None:
                report.append(("missing", label, "unknown to MusicBrainz"))
                continue
            reason = self.filters.recording_reason(rec)
            if reason:
                report.append(("excluded", label, reason))
                continue
            candidates = self.library.find(rec["track_ids"], rec["isrcs"])
            if not candidates:
                report.append(("missing", label, "not in library"))
                continue
            ok, rejected = [], []
            for c in candidates:
                why = self.filters.track_reason(c)
                if not why and c.rating_key in low_rated:
                    why = "rated low by this user"
                if not why and self.require_artist_match and artist_mismatch(rec["artist"], c.artist):
                    why = f"artist mismatch ({c.artist!r} vs {rec['artist']!r})"
                (rejected if why else ok).append((c, why))
            if not ok:
                report.append(("excluded", label, rejected[0][1]))
                continue
            best = max((c for c, _ in ok), key=lambda c: c.bitrate)
            if best.rating_key in seen:
                continue
            seen.add(best.rating_key)
            chosen.append(best)
            report.append(("added", label, f"{best.album} [{best.matched_by}]"))
        return chosen, report

    def sync_user(self, user_cfg: dict, server, low_rated: set) -> None:
        lb_user = user_cfg["listenbrainz_username"]
        prefix = user_cfg.get("playlist_prefix", "") or ""
        for patch in user_cfg.get("playlists", ["weekly-jams"]):
            if patch not in PLAYLISTS:
                logger.error(f"Unknown playlist type {patch!r}; use one of {sorted(PLAYLISTS)}")
                continue
            name = prefix + PLAYLISTS[patch]
            try:
                src = self.lb.latest_created_for(lb_user, patch, user_cfg.get("listenbrainz_token"))
            except Exception as e:
                logger.error(f"[{lb_user}] could not list ListenBrainz playlists: {e}")
                continue
            if src is None:
                hint = " (follow 'troi-bot' on ListenBrainz to get Daily Jams)" if patch == "daily-jams" else ""
                logger.warning(f"[{lb_user}] no {PLAYLISTS[patch]} playlist on ListenBrainz yet{hint}")
                continue
            lb_tracks = self.lb.playlist_tracks(src["id"], user_cfg.get("listenbrainz_token"))
            logger.info(f"[{lb_user}] {src['title']}: {len(lb_tracks)} tracks")
            tracks, report = self.resolve(lb_tracks, low_rated)
            for status, label, detail in report:
                log = logger.info if status == "added" else logger.warning if status == "excluded" else logger.debug
                log(f"  {status:8s} {label}  ({detail})")
            counts = {s: sum(1 for r in report if r[0] == s) for s in ("added", "excluded", "missing")}
            logger.info(
                f"[{lb_user}] {name}: {counts['added']} matched, {counts['excluded']} excluded, "
                f"{counts['missing']} not in library"
            )
            summary = (
                f"{src['annotation']}\n\nSource: {src['title']} "
                f"(https://listenbrainz.org/playlist/{src['id']}). "
                f"{counts['added']} of {len(lb_tracks)} tracks are in this library. {MARKER}"
            ).strip()
            self.write_playlist(server, name, tracks, summary)

    def write_playlist(self, server, name: str, tracks, summary: str) -> None:
        keys = [t.rating_key for t in tracks]
        try:
            playlist = server.playlist(name)
        except plexapi.exceptions.NotFound:
            playlist = None

        if playlist is not None and (playlist.smart or playlist.playlistType != "audio"):
            logger.error(f"A non-audio or smart playlist called {name!r} already exists; not touching it")
            return
        if playlist is not None and MARKER not in (playlist.summary or "") and len(playlist.items()) > 0:
            logger.error(
                f"Playlist {name!r} exists but wasn't created by this tool; rename it or set a playlist_prefix"
            )
            return

        if self.dry_run:
            logger.info(f"DRY RUN: would write {len(keys)} tracks to {name!r}")
            return
        if not keys:
            logger.warning(f"No tracks for {name!r}; leaving it unchanged")
            return

        items = server.fetchItems(keys)
        by_key = {i.ratingKey: i for i in items}
        items = [by_key[k] for k in keys if k in by_key]

        if playlist is None:
            playlist = server.createPlaylist(name, items=items)
            playlist.editSummary(summary)
            logger.info(f"Created playlist {name!r} with {len(items)} tracks")
            return

        current = [i.ratingKey for i in playlist.items()]
        if current == keys:
            logger.info(f"Playlist {name!r} already up to date")
        else:
            if current:
                playlist.removeItems(playlist.items())
            playlist.addItems(items)
            logger.info(f"Updated playlist {name!r}: {len(items)} tracks")
        if (playlist.summary or "") != summary:
            playlist.editSummary(summary)
