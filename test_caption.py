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


def _ass_secs(t):
    h, m, rest = t.split(":")
    s, cs = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100


def _spans(path):
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("Dialogue:"):
            f = ln.split(",", 9)
            out.append((_ass_secs(f[1]), _ass_secs(f[2])))
    return out


def test_split_lines_breaks_at_pauses():
    """A row must never straddle silence — see test_no_frozen_caption for why."""
    w = lambda t: {"word": "x", "start": t, "end": t + 0.3}
    lines = c.split_lines([w(0.0), w(0.4), w(0.8), w(11.0), w(11.4)], 3)
    assert [len(l) for l in lines] == [3, 2]
    for l in lines:                                   # no row spans the 10s gap
        assert l[-1]["end"] - l[0]["start"] < 2.0
    # without a pause it behaves exactly like split_even
    packed = [w(i * 0.4) for i in range(7)]
    assert [len(l) for l in c.split_lines(packed, 3)] == [3, 2, 2]


def test_no_frozen_caption(tmp):
    """The real bug this guards: WhisperX returns coarse segments, one of which spanned a
    ten-second silence. Splitting by word count alone left 'så bra Du' on screen for 10.6s
    with a word highlighted while nobody spoke."""
    words = [{"word": f"w{i}", "start": s, "end": s + 0.3}
             for i, s in enumerate([0.0, 0.4, 0.8, 11.0, 11.4, 11.8])]
    silences = [(a["end"], b["start"]) for a, b in zip(words, words[1:])
                if b["start"] - a["end"] > c.PAUSE]
    assert silences, "the fixture is supposed to contain a silence"

    for anim in ("pop", "sweep"):
        theme = c.resolve_theme({"t": {"animation": anim}}, "t")
        c.build_ass([words], theme, tmp)
        spans = _spans(tmp)
        # nothing may be on screen while nobody is speaking (beyond the brief hold)
        for s_start, s_end in silences:
            mid = (s_start + s_end) / 2
            assert not any(a <= mid <= b for a, b in spans), \
                f"{anim}: caption still up {mid - s_start:.1f}s into a silence"
        # and no row may outlast its own last word by more than the hold
        assert max(b for _, b in spans) <= words[-1]["end"] + c.HOLD + 1e-9
        for (_, end), (nxt, _) in zip(spans, spans[1:]):
            assert end <= nxt + 1e-9, f"{anim}: events overlap"

    # the .srt must agree with the picture — these drifted apart once
    theme = c.resolve_theme({"t": {}}, "t")
    c.build_srt([words], theme, tmp)
    cues = []
    for block in tmp.read_text(encoding="utf-8").strip().split("\n\n"):
        a, b = block.splitlines()[1].split(" --> ")
        to_s = lambda t: (int(t[:2]) * 3600 + int(t[3:5]) * 60
                          + int(t[6:8]) + int(t[9:]) / 1000)
        cues.append((to_s(a), to_s(b)))
    for s_start, s_end in silences:
        mid = (s_start + s_end) / 2
        assert not any(a <= mid <= b for a, b in cues), "srt cue spans a silence"


def test_clamp_words():
    """Alignment pads a word to fill the silence after it — an observed 'klock.' ran 2.9s
    when it was said in a fraction of that."""
    out = c.clamp_words([{"word": "klock.", "start": 6.36, "end": 9.28},
                         {"word": "kort", "start": 9.30, "end": 9.50}])
    assert out[0]["end"] == 6.36 + c.MAX_WORD          # capped
    assert out[1]["end"] == 9.50                       # a normal word is untouched
    # capping must expose the real pause, so split_lines can close the row
    assert out[1]["start"] - out[0]["end"] > c.PAUSE


def test_merge_brief():
    """A row too short to read is worse than a slightly fuller one."""
    row = lambda t, n: [{"word": "x", "start": t + i * 0.05, "end": t + i * 0.05 + 0.04}
                        for i in range(n)]
    merged = c.merge_brief([row(0.0, 1), row(0.2, 1), row(0.4, 1)], 3)
    assert len(merged) == 1 and len(merged[0]) == 3     # three flashes become one row

    # never merge across a pause — that would undo split_lines and re-freeze the caption
    across = c.merge_brief([row(0.0, 1), row(10.0, 1)], 3)
    assert len(across) == 2

    # never grow past twice the target
    wide = c.merge_brief([row(0.0, 3), row(0.2, 3), row(0.4, 3)], 3)
    assert all(len(r) <= 6 for r in wide)


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
    # A cue runs from its first word's start until HOLD past its last word — except when
    # the next cue is already due, which truncates the first one exactly at 1.000.
    assert body == ("1\n00:00:00,000 --> 00:00:01,000\nhej där\n\n"
                    "2\n00:00:01,000 --> 00:00:01,900\ndu\n\n")


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

    # -o put the output elsewhere, but the clip's own timings are still good: use them
    # rather than silently re-running a transcription that's already been done.
    assert c.pick_saved_words(args(), d / "elsewhere.json") == saved

    lonely = d / "lonely.webm"
    lonely.write_text("x")
    assert c.pick_saved_words(args(input=lonely), d / "lonely_captioned.json") is None
    lonely.unlink()

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


def test_split_segments():
    """WhisperX segments run long — an observed one covered 2.95s to 23.01s, swallowing a
    ten-second silence. With no line boundary at the pause there is nowhere to add the
    sentence that was missed, so it lands in the gap after the segment instead."""
    seg = {"start": 0.0, "end": 20.0, "words": [
        {"word": "a", "start": 0.0, "end": 0.3}, {"word": "b", "start": 0.4, "end": 0.7},
        {"word": "c", "start": 18.0, "end": 18.3}]}
    out = c.split_segments([seg])
    assert len(out) == 2, "the silence must become a line boundary"
    assert (out[0]["start"], out[0]["end"]) == (0.0, 0.7)
    assert (out[1]["start"], out[1]["end"]) == (18.0, 18.3)
    assert [w["word"] for w in out[0]["words"]] == ["a", "b"]


def test_parse_at(tmp):
    """Speech under game audio is inaudible to the aligner, so the time has to be sayable."""
    assert c.parse_at(["@12.5", "hej"]) == (["hej"], (12.5, None))
    assert c.parse_at(["@12.5-14", "hej"]) == (["hej"], (12.5, 14.0))
    assert c.parse_at(["hej", "@12"]) == (["hej", "@12"], None)   # only leading counts
    assert c.parse_at(["12.5", "hej"]) == (["12.5", "hej"], None)  # needs the @

    tmp.write_text("0001 | ett\n+ @12.5 tva\n+ @20-22.5 tre\n", encoding="utf-8")
    e = c.read_transcript(tmp)
    assert [x.get("at") for x in e] == [None, (12.5, None), (20.0, 22.5)]

    # an explicit time is used verbatim, without consulting the aligner (audio=None proves it)
    segs = [{"start": 1.0, "end": 2.0}]
    words = [[{"word": "ett", "start": 1.0, "end": 2.0}]]
    rows = c.retime(segs, words, e, None, "cpu", "", 30.0)
    assert rows[1][0]["start"] == 12.5
    assert (rows[2][0]["start"], rows[2][-1]["end"]) == (20.0, 22.5)


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
