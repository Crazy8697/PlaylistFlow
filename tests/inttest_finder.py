import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from playlistflow.config import Prefs, load_env
from playlistflow.auth import SpotifyAuth
from playlistflow.providers import Spotify
from playlistflow.finder import (parse_lines, primary_query, fallback_queries,
                                 classify, Candidate, artist_named, norm,
                                 AUTO, REVIEW, NOTFOUND, DUP)

LIST = """Fighting Tears Wade Forster
Stoic Faces Drayton Farley
Tishomingo Zach Bryan
Save You a Seat Alex Warren
Corralling the Blues Colter Wall
Back To Then Waylon Wyatt
Still Ragin' Jackson Dean
Four Leaf Clover Gavin Adcock
Picture Perfect The Jack Wharff Band
Good News Shaboozey
Whiskey On You Nate Smith
Lover of Mine John Vincent III
Travelin' Soldier Cody Johnson
5 to 9 Hudson Westbrook
23 Chayce Beckham
How Lucky Am I Kaitlin Butts
Lady May Tyler Childers
Burn, Burn, Burn Zach Bryan
El Dorado Zach Bryan
Fade Cole Phillips
Lost Time Bayker Blankenship
Vienna Matt Schuster
Good Horses Lainey Wilson, Miranda Lambert
Boons Zach Bryan
River Washed Hair Zach Bryan
Broken Love Buffalo Traffic Jam
Kate McCannon Colter Wall
If We Said Goodbye Flatland Cavalry
Linger Royel Otis
Finally Stop Dreaming Dylan Gossett
Springsteen Eric Church
Long Gone Cole Barnhill
Stop & Stare Treaty Oak Revival
Rose Ole 60
No One Else Like Me The Red Clay Strays
In My Arms Instead Randy Rogers Band
One Time Thing Treaty Oak Revival
February Snow Flatland Cavalry
Down by the Water Ocie Elliott
Overtime Rainbow Kitten Surprise, Kacey Musgraves
Linda James Nicholas Jamerson, The Morning Jays"""

env = load_env()
sp = Spotify(SpotifyAuth(env.get("SPOTIFY_CLIENT_ID", ""), Prefs()))

lines = parse_lines(LIST)
results = []
for line in lines:
    items = sp.search_tracks(primary_query(line))
    cands = [Candidate.from_json(t) for t in items if t]
    if not cands:
        for q in fallback_queries(line):
            items = sp.search_tracks(q)
            cands = [Candidate.from_json(t) for t in items if t]
            if cands:
                break
    results.append(classify(line, cands))

counts = {}
for r in results:
    counts[r.status] = counts.get(r.status, 0) + 1
print("lines parsed: %d" % len(lines))
print("auto=%d  review=%d  notfound=%d  dup=%d" % (
    counts.get(AUTO, 0), counts.get(REVIEW, 0),
    counts.get(NOTFOUND, 0), counts.get(DUP, 0)))
print()

print("--- NOT FOUND ---")
for r in results:
    if r.status == NOTFOUND:
        print("   ", r.line.raw)
print()

print("--- ARTIST MISMATCH on the default pick ---")
for r in results:
    if r.candidates:
        q = norm(r.line.title if r.line.explicit else r.line.raw)
        if not artist_named(q, r.candidates[0]):
            print("   %-44s -> %s" % (r.line.raw[:44], r.candidates[0].artists))
print()

print("--- handoff spot-checks ---")
WANT = ["23 Chayce", "5 to 9", "Rose Ole 60", "Springsteen", "Vienna",
        "Linger", "Stop & Stare", "Still Ragin", "Good Horses",
        "Kate McCannon", "Burn, Burn"]
for r in results:
    if any(w in r.line.raw for w in WANT):
        c = r.candidates[0] if r.candidates else None
        print("%-44s %-9s" % (r.line.raw[:44], r.status))
        if c:
            print("     %s | %s | %s (%s) %s" % (c.name, c.artists, c.album, c.year, c.duration))
            print("     %s" % c.uri)
