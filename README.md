# caption — word-by-word Swedish captions for vertical short-form video

Edit the clip in Kdenlive, export a 9:16 `.webm`, then run one command (or right-click
the file). The tool transcribes and word-aligns the Swedish audio, opens the transcript so
you can fix any misheard or misspelt words, then animates an "active-word" highlight and
burns it into the `.webm`.

```
webm in
  → extract 16 kHz mono audio                 (ffmpeg)
  → transcribe + word-align, Swedish          (WhisperX + KB-Whisper + VoxRex)
  → write an editable transcript              (low-confidence words marked [?])
  → you fix words in $EDITOR / Kate           ← the one pause
  → re-time                                   (unchanged lines keep timing; edited lines re-align)
  → build a themed ASS file                   (themes.toml)
  → burn it in                                (ffmpeg, VP8 video, Vorbis copied through)
```

The pause is by design: a step that lets you correct words cannot also be unattended. On
KDE the packaging is still one click — right-click → *Captions* → *Add captions*.

---

## Requirements

- **ffmpeg** built with `libvpx` (VP8) and `libass` (subtitle burn-in). Check:
  ```
  ffmpeg -hide_banner -encoders | grep -w libvpx     # VP8 encoder present
  ffmpeg -hide_banner -filters  | grep -w ass        # ass filter present
  ```
- **Python 3.11+** (uses the stdlib `tomllib`; falls back to `tomli` on older Pythons).
- **python3-venv** for the first-run bootstrap. On Debian/Ubuntu: `sudo apt install python3-venv`.

You do **not** need to install WhisperX or PyTorch yourself. On first run the tool builds a
private virtual environment at `~/.venvs/caption` (override with `$CAPTION_VENV`), installs
WhisperX plus the CPU build of PyTorch into it, and re-executes itself from there. It asks
before doing this; pass `-y` to skip the prompt, or `--no-bootstrap` to just print the manual
recipe. If you have a CUDA GPU, add `--gpu` during setup to keep the CUDA build of torch.

The Swedish models (`KBLab/kb-whisper-small` and `KBLab/wav2vec2-large-voxrex-swedish`)
download on the first transcription to `~/.cache/caption-models` — a few GB, once.

---

## Install

```bash
# 1. the tool  (the service menu expects it here)
install -Dm755 caption ~/.local/bin/caption

# 2. themes
install -Dm644 themes.toml ~/.config/caption/themes.toml

# 3. the Dolphin right-click menu (KDE Plasma 6)
install -Dm755 add-captions.desktop ~/.local/share/kio/servicemenus/add-captions.desktop
kbuildsycoca6                       # refresh menus, then reopen Dolphin
```

`chmod +x` on the `.desktop` file is **required** on Plasma 6 — an un-executable service
menu is ignored. `install -Dm755` above already sets that bit.

The `.desktop` file hard-codes `/home/kenneth/.local/bin/caption`. If your home path differs,
edit the two `Exec=` lines (or point them at `caption` alone, which resolves via `$PATH`).

`themes.toml` is searched for in this order: the path given to `--themes`, then
`~/.config/caption/themes.toml`, then next to the `caption` script, then the current
directory. With none found, a built-in `classic` theme is used.

---

## Use

From the command line:

```bash
caption clip.webm                    # classic theme, opens the editor to correct words
caption clip.webm -t cyan-centre     # a named theme
caption clip.webm --ask-theme        # pick a theme interactively
caption clip.webm --sensitive        # catch softer/quieter speech the recogniser tends to drop
caption clip.webm --no-review        # fully unattended (skip the correction step)
caption --list-themes                # show the themes and their settings
```

If quiet speech is being missed, `--sensitive` lowers the voice-detection and no-speech
thresholds so more of it is transcribed. For finer control, set them yourself with
`--vad-onset` / `--vad-offset` (defaults 0.5 / 0.363; lower catches fainter speech) and
`--no-speech-threshold` (default 0.6; lower keeps more borderline-quiet audio). It's a
trade-off — go too low and breaths or background noise get transcribed as words.

From Dolphin: right-click a `.webm` → **Captions** → **Add captions (Swedish, classic)** or
**Add captions (choose theme…)**. It opens in Konsole with `--hold`, so the window stays put
for the editor prompt and the result.

### The correction step

The transcript opens in `$VISUAL`/`$EDITOR`, or Kate if neither is set (GUI editors are
launched so the tool waits for you to save and close). **What you leave in the file is exactly
what gets captioned.** Format:

```
0001 | det [?]hare en fin dag
0002 | och solen skiner
```

- `[?]` marks a word the aligner was unsure about — **check those first**. The marker is
  stripped either way.
- **Fix or rewrite a line** — edit the words freely. A spelling-only change keeps the exact
  timings; changing the number of words re-aligns just that line against its own audio.
- **Add a line the recogniser missed** — write it on its own line, in reading order, e.g.
  `+ de här orden var för tysta` (the leading `+` is optional; a bare line works too). It gets
  placed in the time gap between its neighbours automatically — no timestamps to type. This is
  the fix for soft speech that was dropped entirely; forced alignment matches the words you
  typed straight to the waveform, so as long as they were spoken (just quietly) they land in
  roughly the right place.
- **Delete a caption** — remove its whole line, or clear the words after the `|`.

Longer lines are split into on-screen rows automatically, balanced so you never get a single
word stranded on its own row, and wrapped to stay inside the frame if they'd be too wide.

---

## Themes

A theme sets colour, position, words-per-line and the animation. It only lists what differs
from the defaults. Add a new look by adding a `[section]` to `themes.toml` — no code change.

```toml
[classic]                 # white text, yellow active word, bottom third
accent_colour = "#FFD23F"
words_per_line = 3
animation      = "pop"    # pop = active word recoloured (+ optional size bump)
pop_scale      = 1.12

[cyan-centre]
accent_colour  = "#34E0E0"
position       = "centre"  # bottom | centre | top
words_per_line = 2

[sweep]
animation      = "sweep"   # karaoke-style progressive fill across the line
words_per_line = 4
```

Shipped themes: `classic`, `cyan-centre`, `one-word`, `sweep`, `top-magenta`, `mint`.
Run `caption --list-themes` to see them.

Keys: `font`, `font_size`, `base_colour`, `accent_colour`, `outline`, `outline_width`,
`shadow`, `position`, `margin_v`, `margin_h`, `wrap`, `words_per_line`, `animation`
(`pop`|`sweep`), `pop_scale`, `bold`. Colours are `#RRGGBB` (the tool converts them to ASS's
`&HAABBGGRR` BGR form for you). `words_per_line` is a target maximum per on-screen row, not a
hard split — words are grouped in balanced rows and long ones wrap to fit. `wrap` is libass's
WrapStyle (`0` = balanced wrapping, the default; `2` = never wrap), and `margin_h` is the side
margin in pixels — raise it if wide words still crowd the edges.

---

## Encoding knobs (VP8)

Defaults: `--bitrate 4M`, `--cpu-used 2` (libvpx speed 0–5, higher = faster/rougher),
`--threads 0` (auto). Add `--crf N` for constant-quality with the bitrate as a ceiling.
The audio track is copied through untouched (`-c:a copy`), so only the video is re-encoded.

---

## Troubleshooting

**`operator torchvision::nms does not exist` (at step 2/5)** — a `torchvision` built against
a different `torch` than the CPU build in the venv. WhisperX never uses vision, so just remove
it:

```bash
~/.venvs/caption/bin/pip uninstall -y torchvision
```

Fresh installs now do this automatically, and the dependency check will repair an existing
venv on the next run.

**`torchcodec is not installed correctly …` (a warning at step 2/5)** — harmless. It's the same
kind of torch/companion version mismatch, but torchcodec is only Pyannote's file decoder, which
isn't used (WhisperX passes audio in-memory), so the run continues. To silence it:

```bash
~/.venvs/caption/bin/pip uninstall -y torchcodec
```

---

## Honest caveats

- **Burning re-encodes the video**, and VP8 is not fast. That is the price of a `.webm` out
  that matches your existing Kdenlive/Vorbis workflow. If you ever don't need webm, H.264/mp4
  encodes several times faster and the platforms re-compress the upload anyway.
- **Changing the theme re-runs transcription** — there is no cached-transcript reuse. Pick the
  theme up front with `-t` or `--ask-theme` to avoid transcribing twice.
- **Added rows are placed by forced alignment**, which assigns every word you type a time. A
  word that was genuinely spoken (just too quietly to be caught) lands in the right place; a
  word that *isn't* in the audio at all gets forced in somewhere anyway. Add what was said, in
  reading order, and it works; invent words and the timing will drift.
- **Tuned for 9:16** (PlayRes 1080×1920). Other aspect ratios render, but the margins and
  sizes assume vertical.
- **Swedish by design** (KB-Whisper + the VoxRex aligner). Another language would need
  different models.
- This was assembled in a sandbox without network access to the ML stack, so the end-to-end
  transcribe→burn run could not be exercised there. The pure-Python logic (colour conversion,
  timestamp formatting, transcript round-trip, re-timing, ASS generation) is unit-tested, and
  the WhisperX/ffmpeg calls follow the official KBLab KB-Whisper recipe and the FFmpeg
  libass/libvpx documentation. Do a first run on a short clip to confirm the models fetch and
  the encode completes on your machine.
