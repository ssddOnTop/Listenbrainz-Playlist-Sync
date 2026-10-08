"""ListenBrainz -> Plex playlist sync, matched by MusicBrainz IDs / ISRCs only.

Usage:
  python main.py              # sync once
  python main.py --dry-run    # resolve and report, don't touch Plex playlists
  python main.py --loop       # keep running, re-sync every `run_every_hours`
"""
import argparse
import os
import sys
import time
import uuid

import plexapi
import yaml
from plexapi.server import PlexServer

from modules.cache import Cache
from modules.filters import Filters
from modules.listenbrainz import ListenBrainz
from modules.logger_utils import logger
from modules.musicbrainz import MusicBrainz
from modules.plex_library import PlexLibrary
from modules.sync import Syncer


def load_config():
    root = os.path.dirname(os.path.abspath(__file__))
    path = os.environ.get("CONFIG_PATH") or os.path.join(root, "config.yml")
    with open(path) as fh:
        cfg = yaml.safe_load(fh) or {}
    cfg["_dir"] = os.path.dirname(os.path.abspath(path))
    return cfg


def client_id(config_dir: str) -> str:
    path = os.path.join(config_dir, "UUID")
    if os.path.exists(path):
        with open(path) as fh:
            value = fh.read().strip()
            if value:
                return value
    value = str(uuid.uuid4())
    with open(path, "w") as fh:
        fh.write(value)
    return value


def low_rated_keys(server, section_key, stars: float) -> set:
    """Tracks this user rated at or below `stars` (Plex stores ratings 0-10)."""
    if not stars:
        return set()
    section = server.library.sectionByID(int(section_key))
    keys = set()
    for t in section.searchTracks(filters={"userRating<<=": stars * 2}):
        if t.userRating is not None and 0 < t.userRating <= stars * 2:
            keys.add(t.ratingKey)
    return keys


def run_once(cfg, dry_run: bool, only_user: str | None) -> None:
    plex_cfg = cfg["plex"]
    plexapi.BASE_HEADERS["X-Plex-Client-Identifier"] = client_id(cfg["_dir"])
    plexapi.BASE_HEADERS["X-Plex-Product"] = "ListenBrainz Playlist Sync"
    admin = PlexServer(plex_cfg["baseurl"], plex_cfg["token"], timeout=120)
    section = admin.library.section(plex_cfg["music_section"])

    cache = Cache(os.path.join(cfg["_dir"], "cache.sqlite"))
    library = PlexLibrary(admin, section)
    library.load()
    library.load_isrcs(cache, plex_cfg.get("path_map") or {}, plex_cfg.get("isrc_index", "unmatched"))

    mb = MusicBrainz(cache, cfg.get("musicbrainz_contact", ""), cfg.get("musicbrainz_cache_days", 30))
    filters = Filters(cfg.get("filters"))
    syncer = Syncer(
        library, mb, ListenBrainz(), filters,
        dry_run=dry_run, require_artist_match=cfg.get("require_artist_match", True),
    )

    stars = (cfg.get("filters") or {}).get("exclude_rating_at_or_below", 1)
    for user in cfg.get("users", []):
        if only_user and only_user not in (user.get("plex_user"), user["listenbrainz_username"]):
            continue
        plex_user = user.get("plex_user")
        try:
            server = admin.switchUser(plex_user) if plex_user else admin
        except Exception as e:
            logger.error(f"Could not act as Plex user {plex_user!r}: {e}")
            continue
        try:
            low = low_rated_keys(server, section.key, stars)
        except Exception as e:
            logger.warning(f"Could not read ratings for {plex_user or 'admin'}: {e}")
            low = set()
        logger.info(f"=== {plex_user or 'admin'} <- ListenBrainz {user['listenbrainz_username']}")
        syncer.sync_user(user, server, low)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="resolve and report only; never write to Plex")
    ap.add_argument("--loop", action="store_true", help="run forever, every run_every_hours")
    ap.add_argument("--user", help="only sync this plex_user / listenbrainz_username")
    args = ap.parse_args()

    cfg = load_config()
    dry_run = args.dry_run or bool(cfg.get("dry_run", False))
    loop = args.loop or os.environ.get("LOOP") == "1"
    hours = float(cfg.get("run_every_hours", 6))
    while True:
        try:
            run_once(cfg, dry_run, args.user)
        except Exception:
            logger.exception("Sync failed")
            if not loop:
                return 1
        if not loop:
            return 0
        logger.info(f"Sleeping {hours}h")
        time.sleep(hours * 3600)


if __name__ == "__main__":
    sys.exit(main())
