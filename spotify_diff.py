import argparse
import datetime
import logging
from thefuzz import process
import os
import mutagen
import unicodedata
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from typing import List, Set, Dict

logging.basicConfig(filename="diff_session.log", encoding="utf-8", level=logging.INFO)

parser = argparse.ArgumentParser()

args = parser.parse_args()

logging.info(f"Starting a new session at {datetime.datetime.now().isoformat()[:16]}")
MUSIC_ROOT_FOLDER = "/Users/fabrol/Library/Mobile Documents/com~apple~CloudDocs/Music/"

scopes = [
    "playlist-read-collaborative",
    "user-library-read",
    "playlist-read-private",
    "playlist-modify-private",
]
sp = spotipy.Spotify(
    oauth_manager=SpotifyOAuth(
        client_id="",
        client_secret="",
        redirect_uri="http://www.farhanabrol.com",
        scope=scopes,
    )
)


def playlist_match(name):
    return name.startswith("F:")


playlist_uri_to_info = {}
playlist_name_to_uri = {}
playlists = sp.current_user_playlists()
while playlists:
    playlist_uri_to_info.update(
        {
            info["uri"]: info
            for info in playlists["items"]
            if playlist_match(info["name"])
        }
    )

    if playlists["next"]:
        playlists = sp.next(playlists)
    else:
        playlists = None

for uri, info in playlist_uri_to_info.items():
    playlist_name_to_uri[info["name"][3:]] = uri

logging.info(f"Operating on {len(playlist_uri_to_info)} playlists from the cloud")

# Build the current state of the playlists in the cloud, keyed by uri
cloud_pl_tracks: Dict[str, Set[str]] = {}  # pl_uri: set('track name')
for pl_uri in playlist_uri_to_info:
    track_name_to_info = {}
    # Get pl tracks
    batch = sp.playlist_tracks(playlist_id=pl_uri)
    while batch:
        track_name_to_info.update(
            {
                unicodedata.normalize("NFD", t["track"]["name"]): t
                for t in batch["items"]
            }
        )
        if batch["next"]:
            batch = sp.next(batch)
        else:
            batch = None
    cloud_pl_tracks[pl_uri] = track_name_to_info


# Build the current state of the playlists on disk. Keyed by uri
disk_pl_tracks = {}  # pl_uri: Set('track name')
playlist_folders = [f for f in os.listdir(MUSIC_ROOT_FOLDER) if not f.startswith(".")]

for pl_name in playlist_folders:
    tracks = []
    for root, _, file_paths in os.walk(os.path.join(MUSIC_ROOT_FOLDER, pl_name)):
        for file_path in file_paths:
            track_file = os.path.join(root, file_path)
            track = mutagen.File(track_file)

            if type(track) == mutagen.mp3.MP3 or type(track) == mutagen.wave.WAVE:
                titles = track.get("TIT2")
                tracks.append(str(titles[0]) if type(titles) == list else str(titles))
            elif type(track) == mutagen.flac.FLAC:
                titles = track.get("title")
                tracks.append(titles[0] if type(titles) == list else titles)

    # Find closest matching uri, alert if not able
    if pl_name not in playlist_name_to_uri:
        logging.info(f"ALERT: Couldnt match local '{pl_name}' with cloud playlist")
        continue

    disk_pl_tracks[playlist_name_to_uri[pl_name]] = set(tracks)

logging.info(
    f"Indexed {len(cloud_pl_tracks)} playlists from the cloud and {len(disk_pl_tracks)} on disk"
)


# Collect all the diffs


def fuzzy_lookup_dict(keys: List, term):
    res = process.extractOne(query=term, choices=keys, score_cutoff=80)
    if not res:
        return None

    return res[0]


diffs_found = {}  # pl_uri : {track_name : track_info}
diffs_track_name_to_pl_uri = {}
for pl_uri, cl_track_name_dict in cloud_pl_tracks.items():
    if pl_uri not in disk_pl_tracks:
        logging.info(
            f'Playlist {pl_uri} {playlist_uri_to_info[pl_uri]["name"]} not found on disk'
        )
        continue

    on_disk = disk_pl_tracks[pl_uri]
    diff = set()
    for track_name in cl_track_name_dict.keys():
        if not fuzzy_lookup_dict(list(on_disk), track_name):
            diff.add(track_name)

    logging.info(f'Diff playlist {playlist_uri_to_info[pl_uri]["name"]}: {diff}')

    if len(diff) == 0:
        continue

    diffs_found[pl_uri] = {
        track_name: cl_track_name_dict[track_name] for track_name in diff
    }
    diffs_track_name_to_pl_uri.update({track_name: pl_uri for track_name in diff})

# Print results
for pl_uri, track_dicts in diffs_found.items():
    print(f'Playlist: {playlist_uri_to_info[pl_uri]["name"]}')
    for track_name, track_info in track_dicts.items():
        artists = " ".join([v["name"] for v in track_info["track"]["artists"]])
        print(f"{track_name}\t{artists}")
    print()
