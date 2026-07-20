#!/usr/bin/env python3
"""Self-check for the pure-Python logic in `caption`. Run: python3 test_caption.py

No framework — plain asserts. Covers the bits that silently produce wrong captions
rather than crashing: colour conversion, timestamps, line splitting, ASS escaping,
theme validation and the transcript round-trip.
"""
import importlib.machinery      # not implied by importlib.util outside 3.12
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_loader(
    "caption", importlib.machinery.SourceFileLoader("caption", str(Path(__file__).parent / "caption")))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def test_hex_to_ass():
    assert c.hex_to_ass("#FFD23F") == "&H003FD2FF"      # RGB -> BGR, alpha first
    assert c.hex_to_ass("#000000", "80") == "&H80000000"


def test_ts():
    assert c.ts(0) == "0:00:00.00"
    assert c.ts(-1) == "0:00:00.00"                      # negatives clamp, never wrap
    assert c.ts(3661.5) == "1:01:01.50"


def test_split_even():
    assert c.split_even([], 3) == []
    assert [len(x) for x in c.split_even(list(range(7)), 3)] == [3, 2, 2]   # no lone widow
    assert [len(x) for x in c.split_even(list(range(6)), 3)] == [3, 3]
    assert [len(x) for x in c.split_even(list(range(4)), 1)] == [1, 1, 1, 1]


def test_ass_text():
    # braces would otherwise open an override block and swallow the caption
    assert c.ass_text("{\\an8}hej") == "\\{⧵an8\\}hej"
    assert c.ass_text("vanlig text") == "vanlig text"
    assert "\\N" not in c.ass_text("a\\Nb")              # no forced line break injection


def test_resolve_theme():
    assert c.resolve_theme({"t": {}}, "t")["font"] == c.THEME_DEFAULTS["font"]
    assert c.resolve_theme({"t": {"words_per_line": 5}}, "t")["words_per_line"] == 5

    for broken in ({"position": "middle"}, {"animation": "spin"}, {"accent_colour": "#FFF"},
                   {"font_size": "big"}, {"words_per_line": 0}, {"colour": "#FFFFFF"},
                   {"bold": "yes"}):
        try:
            c.resolve_theme({"t": broken}, "t")
        except SystemExit:
            pass
        else:
            raise AssertionError(f"bad theme accepted: {broken}")


def test_transcript_round_trip(tmp):
    tmp.write_text(
        "# a comment\n"
        "0001 | hej [?]där\n"
        "0002 |\n"                              # emptied -> dropped by retime
        "+ helt ny rad\n"
        "en rad utan plus\n", encoding="utf-8")
    rows = c.read_transcript(tmp)
    assert [r["kind"] for r in rows] == ["existing", "existing", "new", "new"]
    assert rows[0]["idx"] == 0                  # 1-based in the file, 0-based in memory
    assert rows[0]["tokens"] == ["hej", "där"]  # [?] markers stripped
    assert rows[1]["tokens"] == []
    assert rows[2]["tokens"] == ["helt", "ny", "rad"]


def test_srt_ts():
    assert c.srt_ts(0) == "00:00:00,000"
    assert c.srt_ts(-1) == "00:00:00,000"
    assert c.srt_ts(3661.5) == "01:01:01,500"


def test_build_srt(tmp):
    rows = [[{"word": "hej", "start": 0.0, "end": 0.5},
             {"word": "där", "start": 0.5, "end": 1.0},
             {"word": "du", "start": 1.0, "end": 1.5}]]
    n = c.build_srt(rows, {"words_per_line": 2}, tmp)
    assert n == 2                                   # one cue per on-screen line
    body = tmp.read_text(encoding="utf-8")
    # a cue spans from its first word's start to its last word's end
    assert body == ("1\n00:00:00,000 --> 00:00:01,000\nhej där\n\n"
                    "2\n00:00:01,000 --> 00:00:01,500\ndu\n\n")


def test_words_round_trip(tmp):
    rows = [[{"word": "å", "start": 0.0, "end": 0.5}],
            [{"word": "ä", "start": 1.0, "end": 1.5}]]
    c.save_words(rows, tmp)
    assert "å" in tmp.read_text(encoding="utf-8")   # not å — stays readable
    assert c.load_words(tmp) == rows

    for junk in ("[[{}]]", "[[{\"word\": \"a\", \"start\": \"x\", \"end\": 1}]]", "not json", "{}"):
        tmp.write_text(junk, encoding="utf-8")
        try:
            c.load_words(tmp)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"bad timings file accepted: {junk}")


def test_pick_saved_words(tmp):
    """Don't redo finished work — but only when the saved work is still trustworthy."""
    import argparse, os
    d = tmp.parent
    clip, saved, other = d / "clip.webm", d / "clip_captioned.json", d / "other.json"
    clip.write_text("x")
    saved.write_text("[]")
    def args(**kw):
        return argparse.Namespace(**{"input": clip, "from_words": None, "fresh": False, **kw})

    # saved timings newer than the clip -> reuse them
    os.utime(saved, (clip.stat().st_atime + 10, clip.stat().st_mtime + 10))
    assert c.pick_saved_words(args(), saved) == saved

    # re-exported clip (timings now stale) -> transcribe again
    os.utime(saved, (clip.stat().st_atime - 10, clip.stat().st_mtime - 10))
    assert c.pick_saved_words(args(), saved) is None

    os.utime(saved, (clip.stat().st_atime + 10, clip.stat().st_mtime + 10))
    assert c.pick_saved_words(args(fresh=True), saved) is None        # --fresh overrides
    assert c.pick_saved_words(args(), d / "absent.json") is None      # nothing saved yet

    other.write_text("[]")
    assert c.pick_saved_words(args(from_words=other), saved) == other  # explicit path wins
    try:
        c.pick_saved_words(args(from_words=d / "nope.json"), saved)
    except SystemExit:
        pass
    else:
        raise AssertionError("--from with a missing file should fail loudly")
    for f in (clip, saved, other):
        f.unlink()


def test_aligner_cache():
    """Loaded once, dropped on release, reloaded only when asked for again."""
    import sys, types
    loads = []
    fake = types.ModuleType("whisperx")
    fake.load_align_model = lambda **kw: (loads.append(kw) or ("model", "meta"))
    sys.modules["whisperx"] = fake
    try:
        c.load_aligner.cache_clear()
        assert c.load_aligner("cpu", "/tmp") == ("model", "meta")
        c.load_aligner("cpu", "/tmp")
        assert len(loads) == 1                      # memoised, not reloaded
        c.release_aligner("cpu")                    # freed for the review pause
        c.load_aligner("cpu", "/tmp")
        assert len(loads) == 2                      # and brought back on demand
    finally:
        del sys.modules["whisperx"]
        c.load_aligner.cache_clear()


def test_retime_keeps_and_fills():
    segs = [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 3.0}]
    words = [[{"word": "a", "start": 0.0, "end": 1.0}],
             [{"word": "b", "start": 2.0, "end": 3.0}]]
    entries = [{"kind": "existing", "idx": 0, "tokens": ["a"]},
               {"kind": "new", "tokens": ["ny"]},
               {"kind": "existing", "idx": 1, "tokens": ["b"]}]

    # a new row between two timed rows must land in the gap, without touching the aligner
    calls = []
    c.realign_within = lambda toks, s, e, *a: (calls.append((s, e)) or
                                               [{"word": toks[0], "start": s, "end": e}])
    rows = c.retime(segs, words, entries, None, "cpu", "", 5.0)
    assert calls == [(1.0, 2.0)], calls
    assert rows[0][0]["start"] == 0.0 and rows[2][0]["end"] == 3.0   # timings untouched


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "transcript.txt"
        for name, fn in sorted(globals().items()):
            if name.startswith("test_"):
                fn(path) if fn.__code__.co_argcount else fn()
                print(f"  ok  {name}")
    print("all good")
