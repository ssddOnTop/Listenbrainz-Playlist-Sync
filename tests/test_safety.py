import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.safety import PlaylistOnlySession, UnsafeRequest  # noqa: E402

BASE = "http://plex:32400"


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.s = PlaylistOnlySession()
        patcher = mock.patch.object(requests.Session, "request", return_value="sent")
        self.sent = patcher.start()
        self.addCleanup(patcher.stop)

    def test_reads_allowed_everywhere(self):
        self.assertEqual(self.s.get(f"{BASE}/library/sections/1/all"), "sent")

    def test_playlist_changes_allowed(self):
        self.assertEqual(self.s.post(f"{BASE}/playlists?type=audio&title=x"), "sent")
        self.assertEqual(self.s.put(f"{BASE}/playlists/5/items?uri=x"), "sent")
        self.assertEqual(self.s.delete(f"{BASE}/playlists/5/items/9"), "sent")

    def test_library_changes_blocked(self):
        for method, path in [
            ("DELETE", "/library/metadata/123"),          # delete a track/album (and its files)
            ("PUT", "/library/metadata/123"),             # edit tags/metadata
            ("PUT", "/:/rate?key=123&rating=2"),          # change ratings
            ("PUT", "/library/sections/1/refresh"),       # rescan
            ("PUT", "/library/sections/1/emptyTrash"),    # empty trash
            ("PUT", "/:/prefs?allowMediaDeletion=1"),     # server settings
            ("POST", "/library/metadata/123/posters"),
        ]:
            with self.assertRaises(UnsafeRequest, msg=f"{method} {path}"):
                self.s.request(method, BASE + path)
        self.sent.assert_not_called()

    def test_lookalike_path_blocked(self):
        with self.assertRaises(UnsafeRequest):
            self.s.delete(f"{BASE}/playlistsX/1")


if __name__ == "__main__":
    unittest.main()
