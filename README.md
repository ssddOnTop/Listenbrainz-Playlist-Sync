# ListenBrainz Playlist Sync for Plex (ID-matched fork)

Syncs your ListenBrainz **Weekly Jams**, **Daily Jams** and **Weekly Exploration** playlists into Plex /
Plexamp, for every user on the server, using **only tracks you already own**.

This fork never searches Plex by title. Tracks are matched by global identifiers:

1. **MusicBrainz IDs.** ListenBrainz gives a *recording* MBID. MusicBrainz expands it to every
   *release-track* MBID of that recording, which is what Plex stores on matched tracks (`mbid://…`).
2. **ISRC (fallback).** For tracks Plex hasn't matched, the ISRC is read straight from the file tags
   (read-only mount) and compared with the recording's ISRCs.

Because a cover, remix or live version is a *different recording* with different IDs, it can never stand
in for the original. On top of that, every candidate goes through exclusion filters:

| Layer | Rejects |
|---|---|
| MusicBrainz relationships | cover / live / karaoke (optionally instrumental) performances; remixes, edits, DJ‑mixes, mash‑ups |
| Plex album type | albums typed `Live`, `Remix`, `DJ Mix` (configurable) |
| Title / album patterns | "remix", "cover", "karaoke", "- live", "sped up", ... (safety net) |
| Your ratings | tracks the user rated ≤ 1★ (configurable) |
| Artist sanity check | file artist shares no word with the MusicBrainz artist |

If several files match (e.g. the album and a compilation), the highest‑bitrate non‑excluded one wins.

**It never downloads anything.** Its only writes are Plex playlists it created itself (marked `[lb-sync]` in
the summary). It refuses to modify a playlist with the same name that it didn't create.

## Setup

1. Each person scrobbles to their own ListenBrainz account (Plex → ListenBrainz via multi-scrobbler,
   eavesdrop.fm, etc.). For Daily Jams, follow the `troi-bot` user on ListenBrainz.
2. Copy `config.yml.example` to `config/config.yml` and fill it in:
   * `plex.token`: the **server owner's** token. Other users are listed under `users:` with `plex_user`
     (username/email/id) and get their own playlists via Plex's `switchUser`.
   * `plex.path_map`: Plex's path prefix → where the music is mounted in the container (for ISRCs).
3. Try it without writing anything:

   ```bash
   docker compose run --rm listenbrainz-sync python main.py --dry-run
   ```

   The log lists every track as `added`, `excluded` (with the reason) or `missing` (not in your library).
4. Start it: `docker compose up -d --build`. With `LOOP=1` it re-syncs every `run_every_hours`.

The first run reads ISRC tags from unmatched files and resolves MusicBrainz data at ~1 request/s
(MusicBrainz's limit). Both are cached in `config/cache.sqlite`, so later runs are fast.

## Without Docker

```bash
pip install -r requirements.txt
python main.py --dry-run          # report only
python main.py                    # sync once
python main.py --loop             # keep syncing
python main.py --user Darkbeast58 # one user only
```

## Tests

```bash
python -m unittest discover tests
```

## Credits

Original project by [Mjsciarabba](https://github.com/Mjsciarabba/Listenbrainz-Playlist-Sync).
Uses [Python-PlexAPI](https://github.com/pkkid/python-plexapi), the
[ListenBrainz API](https://listenbrainz.readthedocs.io/en/latest/users/api/index.html) and the
[MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API).
