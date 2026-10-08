import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.filters import Filters  # noqa: E402
from modules.plex_library import PlexLibrary, Track  # noqa: E402
from modules.sync import Syncer, artist_mismatch  # noqa: E402


def rec(rid, artist="Daft Punk", tids=(), isrcs=(), relations=(), disambiguation=""):
    return {
        "id": rid, "title": rid, "artist": artist, "disambiguation": disambiguation,
        "track_ids": list(tids), "isrcs": list(isrcs), "relations": list(relations),
    }


def perf(*attrs):
    return {"type": "performance", "direction": "forward", "attributes": list(attrs), "target_type": "work"}


class FakeMB:
    def __init__(self, recs):
        self.recs = recs

    def recording(self, rid):
        return self.recs.get(rid)


def library(*tracks):
    lib = PlexLibrary(None, None)
    for t in tracks:
        lib.tracks[t.rating_key] = t
        for tid in t.track_ids:
            lib.by_track_id.setdefault(tid, set()).add(t.rating_key)
        for i in t.isrcs:
            lib.by_isrc.setdefault(i, set()).add(t.rating_key)
    return lib


def track(key, title="Song", artist="Daft Punk", album="Album", tids=(), isrcs=(), album_types=(), bitrate=1000):
    return Track(key, title, artist, album, key * 10, f"/data/{key}.flac", bitrate,
                 set(tids), set(isrcs), set(album_types))


def lb(*rids):
    return [{"recording_id": r, "title": r, "artist": "x"} for r in rids]


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.f = Filters(None)

    def test_cover_and_live_and_karaoke_performances_rejected(self):
        for attr in ("cover", "live", "karaoke"):
            self.assertIsNotNone(self.f.recording_reason(rec("r", relations=[perf(attr)])), attr)

    def test_plain_performance_ok(self):
        self.assertIsNone(self.f.recording_reason(rec("r", relations=[perf()])))

    def test_remix_direction_matters(self):
        remix_of = {"type": "remix", "direction": "forward", "attributes": [], "target_type": "recording"}
        remixed_by = {**remix_of, "direction": "backward"}
        self.assertIsNotNone(self.f.recording_reason(rec("r", relations=[remix_of])))
        # The ORIGINAL has a backward 'remix' relation (it was remixed); it must stay.
        self.assertIsNone(self.f.recording_reason(rec("r", relations=[remixed_by])))

    def test_live_disambiguation(self):
        self.assertIsNotNone(self.f.recording_reason(rec("r", disambiguation="live, 1988-04-05: Mainz")))

    def test_options_can_disable(self):
        f = Filters({"exclude_live": False})
        self.assertIsNone(f.recording_reason(rec("r", relations=[perf("live")])))

    def test_track_title_and_album_type(self):
        self.assertIsNotNone(self.f.track_reason(track(1, title="Technologic (Vitalic Remix)")))
        self.assertIsNotNone(self.f.track_reason(track(1, title="Hallelujah - Live")))
        self.assertIsNotNone(self.f.track_reason(track(1, album_types={"Live"})))
        self.assertIsNone(self.f.track_reason(track(1, title="Live and Let Die")))
        self.assertIsNone(self.f.track_reason(track(1, title="Alive", album_types={"Compilation"})))


class MatchTests(unittest.TestCase):
    def syncer(self, lib, recs):
        return Syncer(lib, FakeMB(recs), None, Filters(None), dry_run=True)

    def test_matches_by_mbid_never_by_title(self):
        lib = library(track(1, title="Same Title", tids={"t-orig"}), track(2, title="Same Title", tids={"t-other"}))
        chosen, _ = self.syncer(lib, {"r1": rec("r1", tids=["t-orig"])}).resolve(lb("r1"), set())
        self.assertEqual([t.rating_key for t in chosen], [1])

    def test_isrc_fallback_when_no_mbid(self):
        lib = library(track(1, isrcs={"USRE11100770"}))
        chosen, report = self.syncer(lib, {"r1": rec("r1", isrcs=["USRE11100770"])}).resolve(lb("r1"), set())
        self.assertEqual([t.rating_key for t in chosen], [1])
        self.assertIn("[isrc]", report[0][2])

    def test_cover_recording_never_substitutes_original(self):
        # Library owns only a cover; ListenBrainz asks for the original -> nothing is added.
        lib = library(track(1, artist="Cover Band", tids={"t-cover"}))
        chosen, report = self.syncer(lib, {"orig": rec("orig", tids=["t-orig"])}).resolve(lb("orig"), set())
        self.assertEqual(chosen, [])
        self.assertEqual(report[0][0], "missing")

    def test_cover_requested_is_excluded(self):
        lib = library(track(1, tids={"t-cover"}))
        recs = {"c": rec("c", tids=["t-cover"], relations=[perf("cover")])}
        chosen, report = self.syncer(lib, recs).resolve(lb("c"), set())
        self.assertEqual(chosen, [])
        self.assertEqual(report[0][0], "excluded")

    def test_prefers_non_live_copy_and_highest_bitrate(self):
        lib = library(
            track(1, tids={"t"}, album_types={"Live"}, bitrate=9000),
            track(2, tids={"t"}, bitrate=900),
            track(3, tids={"t"}, bitrate=4000),
        )
        chosen, _ = self.syncer(lib, {"r": rec("r", tids=["t"])}).resolve(lb("r"), set())
        self.assertEqual([t.rating_key for t in chosen], [3])

    def test_low_rated_and_duplicates_skipped(self):
        lib = library(track(1, tids={"a"}), track(2, tids={"b"}))
        recs = {"ra": rec("ra", tids=["a"]), "rb": rec("rb", tids=["b"])}
        chosen, _ = self.syncer(lib, recs).resolve(lb("ra", "rb", "ra"), {2})
        self.assertEqual([t.rating_key for t in chosen], [1])

    def test_artist_mismatch(self):
        self.assertTrue(artist_mismatch("Leonard Cohen", "Jeff Buckley"))
        self.assertFalse(artist_mismatch("Duke Ellington", "Duke Ellington and His Orchestra"))
        self.assertFalse(artist_mismatch("渡辺貞夫", "Sadao Watanabe"))  # can't compare scripts -> allow


if __name__ == "__main__":
    unittest.main()
