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
  → burn it in                                (ffmpeg, VP9 video, Vorbis copied through)
  → leave a .srt and a .json beside the output
```

The pause is by design: a step that lets you correct words cannot also be unattended. On
KDE the packaging is still one click — right-click → *Captions* → *Add captions*.

---

## Requirements

- **ffmpeg** built with `libvpx` (VP8/VP9) and `libass` (subtitle burn-in). Check:
  ```
  ffmpeg -hide_banner -encoders | grep -w libvpx-vp9  # VP9 encoder present (the default)
  ffmpeg -hide_banner -filters  | grep -w ass         # ass filter present
  ```
- **Python 3.11+** (uses the stdlib `tomllib`).
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
# 1. the tool  (anywhere on $PATH; the service menu resolves it by name)
install -Dm755 caption ~/.local/bin/caption

# 2. themes
install -Dm644 themes.toml ~/.config/caption/themes.toml

# 3. the Dolphin right-click menu (KDE Plasma 6)
install -Dm755 add-captions.desktop ~/.local/share/kio/servicemenus/add-captions.desktop
kbuildsycoca6                       # refresh menus, then reopen Dolphin
```

`chmod +x` on the `.desktop` file is **required** on Plasma 6 — an un-executable service
menu is ignored. `install -Dm755` above already sets that bit.

The `.desktop` file calls `caption` through `$PATH`, so the three commands above are the
whole install on any machine. If your desktop session doesn't have `~/.local/bin` on `$PATH`,
put an absolute path in the two `Exec=` lines instead.

`themes.toml` is searched for in this order: the path given to `--themes`, then
`~/.config/caption/themes.toml`, then next to the `caption` script. With none found, a
built-in `classic` theme is used. The current directory is deliberately *not* searched — a
`themes.toml` you didn't write shouldn't take effect just because of where you ran the
command; pass it explicitly with `--themes` if that's what you want.

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

# try another look without transcribing again — seconds instead of minutes
caption clip.webm -t mint --from clip_captioned.json
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

## What you get

Three files land next to the output:

| File | What it's for |
|---|---|
| `clip_captioned.webm` | the clip with the captions burnt in |
| `clip_captioned.srt` | the same captions as a subtitle track — selectable, searchable, translatable, and readable by a screen reader, none of which burnt-in text can be |
| `clip_captioned.json` | the word timings, so you can re-theme without transcribing again |

Burnt-in captions can't be turned off, resized, or read out. Upload the `.srt` alongside the
video anywhere that accepts a subtitle track and the captions work for people who need them
adjustable.

The `.json` is the input to `--from`:

```bash
caption clip.webm -t sweep --from clip_captioned.json
```

That skips audio extraction, transcription, the correction step and re-timing, and goes
straight to building and burning — so trying a different theme costs an encode, not a
transcription. It doesn't need WhisperX or PyTorch installed at all, only `ffmpeg`. The
corrections you made in the editor are already baked into the timings, so you don't redo them.

Add `--keep-temp` to also keep the intermediate `.wav`, `.ass` and edited `.txt`.

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

## Encoding knobs

Defaults: `--codec vp9`, `--bitrate 4M`, `--cpu-used 2` (libvpx speed 0–5, higher =
faster/rougher), `--threads 0` (auto). Add `--crf N` for constant-quality with the bitrate as
a ceiling. The audio track is copied through untouched (`-c:a copy`), so only the video is
re-encoded.

VP9 is the default because VP8 encodes on roughly one core no matter what `--threads` says.
Measured on a 35 s 1080×1920 clip on 16 cores, same target bitrate, same output size:

| | encode time |
|---|---|
| VP8 (the old default) | 188 s |
| **VP9 `--cpu-used 2`** | **73 s** |
| VP9 `--cpu-used 4` | 57 s |

Either way the output is webm with the Vorbis track copied through, which every current
browser plays. `--codec vp8` is still there if something downstream insists on it.

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

- **Burning re-encodes the video**, and that is the slowest step by a distance — roughly 73 s
  of a 90 s run on a 35 s clip, against 15 s for the transcription. It is the price of a
  `.webm` out that matches your existing Kdenlive/Vorbis workflow. If you ever don't need
  webm, H.264/mp4 encodes faster still and the platforms re-compress the upload anyway.
- **A GPU barely helps.** CUDA accelerates transcription and alignment only, which is the
  small end of the run; on a 35 s clip it saves on the order of ten seconds. The encode is
  CPU-bound either way. `--device cuda` works if you have a CUDA torch installed, but don't
  install one expecting a big win.
- **Added rows are placed by forced alignment**, which assigns every word you type a time. A
  word that was genuinely spoken (just too quietly to be caught) lands in the right place; a
  word that *isn't* in the audio at all gets forced in somewhere anyway. Add what was said, in
  reading order, and it works; invent words and the timing will drift.
- **Tuned for 9:16** (PlayRes 1080×1920). Other aspect ratios render, but the margins and
  sizes assume vertical.
- **Swedish by design** (KB-Whisper + the VoxRex aligner). Another language would need
  different models.
- The pure-Python logic (colour conversion, timestamp formatting, line splitting, ASS
  escaping, theme validation, transcript round-trip, re-timing, the `.srt` and `--from`
  sidecars) is covered by `test_caption.py` — plain asserts, no framework, no ML deps:

  ```bash
  python3 test_caption.py
  ```

  The `--from` path is exercisable end to end with only `ffmpeg` installed. The full
  transcribe→burn run needs the ML stack, so the WhisperX calls follow the official KBLab
  KB-Whisper recipe and the ffmpeg calls the FFmpeg libass/libvpx documentation. Do a first
  run on a short clip to confirm the models fetch and the encode completes on your machine.
