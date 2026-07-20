# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Keep this file current.** If a change makes anything below inaccurate — a flag, a filename,
a pipeline stage, a line count, the test story — update it in the same commit as the change.
A confidently wrong CLAUDE.md is worse than none. The same goes for `README.md`, which
documents the user-facing contract.

## What this is

**67subtitles** (repo `sixseven-subtitles`) is a single-file Python CLI that burns
word-by-word Swedish captions into vertical (9:16) `.webm` clips. The project is
67subtitles; the executable it installs is called `caption`, which is the name used
throughout this file and the README.

The whole tool is the `caption` script (~890 lines) plus `themes.toml` (look/animation
presets), `add-captions.desktop` (a KDE Dolphin right-click service menu) and
`test_caption.py`. There is no package structure and no build step.

Pipeline: extract 16 kHz mono audio (ffmpeg) → transcribe + word-align Swedish audio
(WhisperX + KB-Whisper + VoxRex) → write an editable transcript with low-confidence words
marked `[?]` → block on `$VISUAL`/`$EDITOR`/Kate for manual correction → re-time (unchanged
lines keep timing, edited/added lines are re-aligned to the audio) → build a themed `.ass`
subtitle file → burn it into the `.webm` with ffmpeg (VP9 video, Vorbis audio copied
through) → write `.srt` and `.json` sidecars next to the output.

It is a personal tool for one user, but it must stay portable between his machines: no
hard-coded paths. Input clips are always 30–60 seconds, which bounds any performance work.

## Commands

No build/lint tooling is configured — no `pyproject.toml` or `requirements.txt`. The checks
that matter:

```bash
make test                            # the test suite: plain asserts, no framework, no ML deps
python3 -m py_compile caption        # syntax check without running anything
python3 caption --list-themes        # exercises arg parsing + themes.toml loading + validation
python3 caption --help
```

`VERSION` at the top of `caption` feeds `--version`; bump it when tagging a release.

`test_caption.py` covers the pure-Python logic — colour/timestamp conversion, `split_even`,
ASS escaping, every `resolve_theme` rejection, the transcript round-trip, `retime` (with the
aligner stubbed), the aligner cache, and the `.srt`/`--from` sidecars. Add to it when you
change any of those; it needs no ML stack and runs in under a second.

CI (`.github/workflows/tests.yml`) runs that suite on Python 3.11 and 3.13 for every push to
`main` and every PR. It installs nothing — keeping `test_caption.py` and the module scope of
`caption` stdlib-only is what makes that possible, so don't add an import that breaks it.

**The resume path is fully exercisable without WhisperX or torch** — it needs only ffmpeg.
That makes it the way to test the real pipeline end to end while iterating: run once with
the ML stack (or drop a hand-written `<output>.json` beside a clip), then

```bash
python3 caption clip.webm --theme sweep      # reuses the saved timings automatically
```

A full transcribe→burn run needs `ffmpeg` (with `libvpx` + `libass`) and the ML stack; the
first real run bootstraps a private venv at `~/.venvs/caption` (override with `$CAPTION_VENV`)
and downloads WhisperX/torch plus the Swedish models (~a few GB) — slow, not something to do
casually while iterating. `--no-bootstrap` prints the manual install recipe instead.

There is no linter configured; match the existing style (double-quoted strings, comment
banners like `# --- Section --- #` separating pipeline stages, functions kept small and
named after the pipeline step they implement).

## Architecture

**Everything in `caption` is one file, organized as sequential pipeline stages** (see the
`# --- Step N --- #` banners). Only the standard library is imported at module scope, so
`--list-themes`/`--help`/arg-parsing and the whole `--from` path work even when
WhisperX/torch aren't installed; `torch`/`whisperx` are imported lazily inside the functions
that need them (`transcribe`, `realign_text`, `load_aligner`, `release_aligner`, and inside
`main` in the non-`--from` branch). Preserve this when adding code — don't move a heavy
import to the top of the file.

Key sections, in the order execution actually flows through `main()`:

- **Dependency bootstrap** (`ensure_deps`, `create_venv_and_install`, `venv_has_deps`): if
  the *current* interpreter lacks WhisperX/torch, the script builds/reuses a venv at
  `VENV_DIR` and re-execs itself inside it via `os.execv`, guarded by the
  `CAPTION_BOOTSTRAPPED` env var so it can't loop forever if the venv is broken.
  `venv_has_deps` actually imports torch (not just `find_spec`) so a torch/torchvision
  ABI mismatch is caught and the venv gets repaired rather than silently misused.
  `--from` skips this entirely — that path needs no ML stack.
- **Themes** (`find_themes_file`, `load_themes`, `resolve_theme`): `themes.toml` is a TOML
  file of `[name]` sections, each a sparse override of `THEME_DEFAULTS`. Lookup order is
  `--themes` path → `~/.config/caption/themes.toml` → next to the script → a built-in
  `classic` fallback (`BUILTIN_THEME`) if none exist. **The cwd is deliberately not
  searched** — a themes.toml you didn't write shouldn't take effect because of where the
  command ran. `resolve_theme` validates everything `build_ass` will consume (position,
  animation, `#RRGGBB` colours, integer keys, unknown key names) and exits with a message
  naming the theme; keep new theme keys validated there. Adding a look is a themes.toml
  edit, not a code change — `POSITION` and the two `animation` modes (`pop`, `sweep`) are
  the only things that require touching `build_ass`.
- **Transcribe + align** (`transcribe`, `load_aligner`, `release_aligner`, `realign_text`,
  `realign_within`): WhisperX does ASR then phoneme-level forced alignment against
  `ALIGN_MODEL` (VoxRex). The big ASR model is freed (`del asr; gc.collect()`) right after
  transcription. The aligner lives behind an `lru_cache` rather than being passed around, so
  `main` can `release_aligner()` before the editor opens — the review pause is unbounded and
  the model is ~1 GB. `retime` asks for it through the same cache, so it is reloaded only if
  a line actually needs re-aligning.
- **Transcript round-trip** (`write_transcript`, `read_transcript`, `clean_words`): the
  editable transcript format is `NNNN | word word [?]word …`. `read_transcript` parses it
  back into `{"kind": "existing"|"new", "idx"?, "tokens"}` entries — this is the contract
  between what the user typed and what `retime` consumes. A line whose word *count* is
  unchanged keeps its original per-word timings verbatim; any other edit (or a brand-new
  line with a leading `+`) gets re-aligned. Get this parsing/round-trip logic right first if
  changing the transcript format — it's the one interactive step in an otherwise unattended
  pipeline.
- **Re-timing** (`retime`): assigns a time window to every row (existing rows use their
  original segment window; runs of new rows subdivide the gap between their nearest timed
  neighbours), then only re-runs alignment for rows that actually changed or were added.
- **Caption layout** (`split_lines`, `split_even`, `layout_lines`): the timing-critical part.
  `split_lines` breaks a segment at pauses longer than `PAUSE` (0.7 s) *before* `split_even`
  balances by word count. This is not optional polish: WhisperX segments are coarse — one
  observed segment spanned a ten-second silence — and a row that straddles silence sits
  frozen on screen with a word highlighted while nobody speaks. `clamp_words` caps a single word at `MAX_WORD` (1.2 s): alignment pads a word to fill the
  silence after it — an observed `klock.` ran 2.9 s when the speaker said it in a fraction of
  that — and capping also exposes the real pause so `split_lines` can close the row.
  `merge_brief` then folds away rows shorter than `MIN_ROW` (0.5 s), which alignment produces
  by packing words 0.02 s apart; it runs on the *flattened* rows because a 0.12 s row can be
  a whole WhisperX segment with nothing beside it to merge, and it never merges across a
  pause. `layout_lines` then pairs each row with its window, holding it `HOLD` (0.4 s) past
  its last word but never into the next row. **Both `build_ass` and `build_srt` go through `layout_lines`** so the sidecar
  always matches the picture; they drifted apart once when only `build_ass` was fixed.
- **ASS generation** (`build_ass`, `ass_text`, `hex_to_ass`, `ts`): rows from `layout_lines`
  are rendered as ASS `Dialogue` events. All word
  text goes through `ass_text`, which escapes `{`/`}`/`\` — the transcript is hand-edited, so
  it is untrusted input to a markup format. `pop` emits one event per active word with inline
  `\c` recolour (+ optional `\fscx/\fscy` size bump); `sweep` emits one event per line using
  karaoke `\kf` tags. Colours are converted `#RRGGBB` → ASS's `&HAABBGGRR` (BGR, alpha
  first) by `hex_to_ass`.
- **Resume** (`pick_saved_words`): the UX rule is *don't redo finished work*. A completed run
  leaves `<output>.json`; the next run reuses it automatically when it is newer than the
  input clip, skipping extraction, ASR, alignment and the review step. A stale file (clip
  re-exported) or `--fresh` falls back to the full pipeline; `--from` names a different file
  explicitly. Keep this the default — flags are for overrides, never for the normal path.
- **Sidecars** (`save_words`, `load_words`, `build_srt`, `srt_ts`): every run writes
  `<output>.json` (the re-timed words, the input to `--from`) and `<output>.srt` (a subtitle
  track matching the burnt-in lines). Both are written *before* the encode, so a failed burn
  doesn't lose timings that cost minutes to produce. `load_words` validates its input — it is
  a user-supplied file path.
- **Burn-in** (`burn`, `_filter_path`): shells out to ffmpeg with `-vf ass=<path>`; paths are
  escaped for ffmpeg's filtergraph syntax (`_filter_path`), separately from shell escaping
  (`run` uses `subprocess.run` with a list, not a shell string — `shlex.quote` there is only
  for the printed echo of the command). Defaults to VP9 with `-row-mt 1`; see the performance
  note below before changing this.

Intermediates (`audio.wav`, `captions.ass`, `transcript.txt`) live in a `tempfile.mkdtemp()`
directory removed in a `finally`. **Do not derive them from the input filename** — they used
to be built with `input.with_suffix()`, which strips only the last extension, so
`my.video.webm` produced `my.wav`, clobbering any such file and then deleting it during
cleanup. `--keep-temp` copies them next to the output.

## Performance notes

Measured on a real 35 s 1080×1920 clip, 16 cores. Don't re-litigate these without new
measurements:

- **The encode dominates, not the ML.** Transcribe + align is ~15 s; the burn was ~188 s
  under the old VP8 default. VP8 in libvpx uses about one core regardless of `--threads`.
- **VP9 with `-row-mt 1` is the default** and does the same clip in ~73 s at the same target
  bitrate and output size (~57 s at `--cpu-used 4`). SVT-AV1 `-preset 8` measured ~27 s but
  is not wired up — it needs its own quality knobs, since `--cpu-used` doesn't apply.
- **A GPU is not worth it.** CUDA touches only the ~15 s of ML work, saving on the order of
  ten seconds of a ~90 s run. Device detection is automatic (`torch.cuda.is_available()`).
- **`--sensitive` must not become the default.** Measured on four real clips (speech
  coverage against an energy estimate): 79%→79%, 84%→86%, 59%→**51%**, 47%→**71%**. It
  rescues clips where speech is dropped and actively hurts others. Per-clip override, as is.
- **Missed speech is a separate problem from caption timing.** If captions feel out of sync,
  check whether words are missing first (compare the `.json` word spans against where the
  audio is actually loud) — a hole in the transcript reads exactly like drift.
- **Batching the re-alignment is not worth it.** `whisperx.align()` loops per segment with
  one model forward each, so N segments in one call costs the same as N calls. Re-alignment
  also only runs for rows whose word count changed, which is rare.

## UX rules

The owner's stated priorities, which override tidiness arguments:

- **Don't redo work that's already done.** If something on disk shows a stage finished, skip
  it and say so. `pick_saved_words` is the current example.
- **Smart defaults, flags only for overrides.** The common path must need no flags at all.
  Before adding one, ask whether the right behaviour can be detected instead.
- **Keep `--help` scannable.** Common options first; everything else in the `recognition`,
  `encoding` and `files and setup` argument groups.
- **Quiet by default.** ffmpeg runs at `-v error`; `-stats` only when stderr is a TTY,
  because its `\r` redraw becomes thousands of lines when piped. `hush_ml_noise()` silences
  WhisperX's dependency chatter, which users reasonably read as a crash. `--verbose` shows
  everything, including the commands.

  `hush_ml_noise` uses `logging.disable(logging.INFO)`, deliberately: whisperx and lightning
  each attach their own handler with their own level *while a model loads*, which is after
  any setup code runs and overrides anything set on their loggers. Per-logger levels were
  tried and don't work; `logging.basicConfig` is worse, because owning the root handler makes
  lightning's message print twice. WARNING and above still pass, so real problems show.
- **One command to install** (`make install`), and it must never clobber a config file the
  user may have edited.

## Notes for changes

- The README documents user-facing behavior in detail (themes, transcript editing rules,
  the sidecars and `--from`, encoding knobs, troubleshooting) — check it before changing CLI
  flags or the transcript format, since both are part of the documented contract, and update
  it in the same commit.
- `themes.toml` shipped at the repo root is installed to `~/.config/caption/themes.toml`; the
  repo copy and a user's installed copy can diverge, so treat repo `themes.toml` as the
  canonical set of shipped example themes rather than a runtime default. The installed copy
  may hold themes the repo doesn't.
- `add-captions.desktop` resolves `caption` through `$PATH` so the same file works on any
  machine. Don't reintroduce an absolute path.
- Replacing the venv bootstrap with `uv`/PEP 723 was evaluated on 2026-07-20 and **declined**:
  the bootstrap already self-installs from `python3` + `python3-venv`, so uv trades one
  prerequisite for another. Revisit only if the `torchvision::nms` mismatch actually recurs.
