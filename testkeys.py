"""Check the key converter against values FreqBlog actually returned."""

from playlistflow.keys import to_camelot, clean_title, primary_artist

# (input, expected). The first block is real FreqBlog output from this project.
cases = [
    ("E-Major", "12B"),      # Devil in Her Eyes — FreqBlog said camelot 12B
    ("C#-Minor", "12A"),     # Believe It — FreqBlog said camelot 12A
    ("C-Major", "8B"),       # Uptown Funk — FreqBlog docs say 8B
    ("Cm", "5A"),            # GetSongBPM style
    ("C#m", "12A"),
    ("Am", "8A"),
    ("F#m", "11A"),
    ("Bbm", "3A"),
    ("Ab", "4B"),
    ("F", "7B"),
    ("D major", "10B"),
    ("g minor", "6A"),
    ("12A", "12A"),          # already Camelot, passes through
    ("5b", "5B"),
    ("nonsense", ""),
    ("", ""),
]

ok = True
print("to_camelot:")
for src, exp in cases:
    got = to_camelot(src)
    good = got == exp
    ok &= good
    print(f"  {src!r:<14} -> {got!r:<5} expected {exp!r:<5} {'ok' if good else 'MISMATCH'}")

print("\nclean_title:")
for src, exp in [
    ("Believe It (feat. Someone)", "Believe It"),
    ("Curiosity - Remastered 2019", "Curiosity"),
    ("OUTLAW [feat. X]", "OUTLAW"),
    ("Addict", ""),                       # unchanged -> empty
    ("Song (Radio Edit)", "Song"),
]:
    got = clean_title(src)
    good = got == exp
    ok &= good
    print(f"  {src!r:<32} -> {got!r:<16} {'ok' if good else 'MISMATCH expected ' + repr(exp)}")

print("\nprimary_artist:")
for src, exp in [
    ("Mark Ronson, Bruno Mars", "Mark Ronson"),
    ("Jared Benjamin", "Jared Benjamin"),
    ("A & B", "A"),
    ("Ekoh feat. Someone", "Ekoh"),
]:
    got = primary_artist(src)
    good = got == exp
    ok &= good
    print(f"  {src!r:<28} -> {got!r:<16} {'ok' if good else 'MISMATCH expected ' + repr(exp)}")

print("\n" + ("KEY TESTS PASSED" if ok else "KEY TESTS FAILED"))
raise SystemExit(0 if ok else 1)
