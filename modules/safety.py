"""Hard guard: this tool may only ever change Plex *playlists*.

Every request PlexAPI sends goes through one requests.Session. This wraps it so any
non-GET request whose path is not under /playlists is refused before it leaves the
process. Library items, metadata, ratings, files and settings therefore cannot be
modified or deleted, even by a bug.
"""
from urllib.parse import urlparse

import requests

READ_METHODS = {"GET", "HEAD", "OPTIONS"}


class UnsafeRequest(RuntimeError):
    pass


class PlaylistOnlySession(requests.Session):
    def request(self, method, url, *args, **kwargs):
        path = urlparse(url).path
        if method.upper() not in READ_METHODS and not _is_playlist_path(path):
            raise UnsafeRequest(f"Blocked {method.upper()} {path}: only playlist changes are allowed")
        return super().request(method, url, *args, **kwargs)


def _is_playlist_path(path: str) -> bool:
    return path == "/playlists" or path.startswith("/playlists/")
