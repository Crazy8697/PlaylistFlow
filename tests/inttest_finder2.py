import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from playlistflow.config import Prefs, load_env
from playlistflow.auth import SpotifyAuth
from playlistflow.providers import Spotify
from playlistflow.finder import (parse_lines, primary_query, fallback_queries,
                                 classify, Candidate, AUTO, REVIEW, NOTFOUND)

ARTIST_FIRST = """Colter Wall Cowpoke
Colter Wall The Trains Are Gone
Ian Noe Off This Mountaintop
Uncle Lucius Keep The Wolves Away
Charles Wesley Godwin Seneca Creek
Pony Bradshaw Sawtoothed Jericho
Cole Chaney Wishing Well
Benjamin Tod Using Again
Corb Lund Gettin' Down on the Mountain
Josh Turner Long Black Train
Zach Bryan Something in the Orange
Johnny Cash Hurt
Alex Warren Save You a Seat
Colter Wall Corralling the Blues
John Vincent III Lover of Mine
Waylon Wyatt Riches To Rags
Ian Noe Between the Country
Zach Bryan Open the Gate
Koe Wetzel February 28, 2016
The Band Of Heathens Hurricane
Wyatt Flores West Of Tulsa"""

TITLE_FIRST = """Tishomingo Zach Bryan
Kate McCannon Colter Wall
23 Chayce Beckham
Springsteen Eric Church
Lady May Tyler Childers
Stop & Stare Treaty Oak Revival"""

env = load_env()
sp = Spotify(SpotifyAuth(env.get("SPOTIFY_CLIENT_ID", ""), Prefs()))

def run(label, text):
    counts = {}
    bad = []
    for line in parse_lines(text):
        items = sp.search_tracks(primary_query(line))
        cands = [Candidate.from_json(t) for t in items if t]
        if not cands:
            for q in fallback_queries(line):
                items = sp.search_tracks(q)
                cands = [Candidate.from_json(t) for t in items if t]
                if cands:
                    break
        r = classify(line, cands)
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.status != AUTO:
            c = r.candidates[0] if r.candidates else None
            bad.append((line.raw, r.note, f"{c.name} | {c.artists}" if c else "-"))
    print("%s: auto=%d review=%d notfound=%d" % (
        label, counts.get(AUTO, 0), counts.get(REVIEW, 0), counts.get(NOTFOUND, 0)))
    for raw, note, top in bad:
        print("   %-36s %-42s %s" % (raw[:36], note[:42], top[:44]))
    print()

run("ARTIST-FIRST", ARTIST_FIRST)
run("TITLE-FIRST ", TITLE_FIRST)
