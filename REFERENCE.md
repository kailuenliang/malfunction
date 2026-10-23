# malfunction: technical reference

How it works inside: engines, every flag, the install internals, sync, output files and the full reading list. For the short intro see [README.md](README.md); for the hands-on guide see [MANUAL.md](MANUAL.md).

A DVD ripper that datamoshes the disc **while it reads it**.

As the video comes off the drive, a Python engine goes through the compressed bitstream one picture at a time. It removes keyframes, repeats P-frames and overwrites bytes. You watch it happen in a live preview. The result is a moshed rip, "baked" to H.264 so it looks the same in every player. If you want it, you also get the raw corrupted bitstream and a clean copy.

```
DVD ──ffmpeg──▶ compressed frames ──▶ [FFglitch: motion-vector hacks] ──▶ MOSH ENGINE ──┬──▶ live preview
               (MPEG-2 / MPEG-4 / H.264)                                I-drop/bloom/  ├──▶ raw moshed stream
                                                                        databend       └──▶ H.264 bake ──▶ .mp4 (+audio)

DVD ──ffmpeg──▶ raw pixels ──▶ FLOW ENGINE (optical flow + motion hacks) ──▶ H.264 bake ──▶ .mp4 (+audio)
```

## Install (Mac and Windows, one folder, nothing else touched)

**For students:** see `START HERE.txt`.

| | first time | after that |
|---|---|---|
| Mac | In Terminal: type `bash `, drag `malfunction.command` into the window, press Enter. (Double-clicking also works on older macOS.) | double-click `malfunction.command` |
| Windows | Extract the zip, double-click `malfunction.bat`. If SmartScreen appears: More info → Run anyway. | double-click `malfunction.bat` |
| Linux (x86-64) | `bash malfunction.command` | same |

The first launch sets up everything inside a hidden **`.runtime/`** folder in the malfunction folder. It needs about 600–750 MB and a few minutes; later launches open straight away.

| in `.runtime/` | what it is | from |
|---|---|---|
| `uv/` | the tool that fetches Python | [astral-sh/uv](https://github.com/astral-sh/uv) GitHub releases |
| `python/`, `venv/` | a private Python 3.12 and its environment | python-build-standalone, via uv |
| packages | numpy, OpenCV, truststore, certifi (`requirements.txt`) | PyPI, via uv |
| `ffmpeg/` | ffmpeg, ffprobe, ffplay 9.x static builds | Mac/Linux: [martin-riedl.de](https://ffmpeg.martin-riedl.de); Windows: [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) essentials (checksum verified) |
| `ffglitch/` | FFglitch 0.10.2 | [ffglitch.org](https://ffglitch.org) (checksum verified) |

**Isolation:**

- No admin rights are needed.
- Nothing is installed system-wide.
- No PATH, shell profile or registry changes are made.
- The computer's own Python and ffmpeg (if any) are never used or modified.
- uv is pointed at `.runtime/` for its Python installs, cache and tools.
- On Windows, the private Python isn't registered in the registry (`UV_PYTHON_NO_REGISTRY`).

I checked this with a fresh install using an empty home folder: nothing was written outside the malfunction folder. **Uninstall = delete the folder.**

**Robustness:**

- Every launch checks the setup. If the folder was moved (which breaks the private Python's links) or a download was interrupted, it repairs itself on the next launch.
- Downloads retry, and use the computer's own certificate store (school web filters often add their own certificate).
- After the first successful setup, the installer removes macOS's quarantine flag (or Windows' Mark of the Web) from its own folder only, so double-clicking works from then on.

**Command line with the private setup:** `.runtime/venv/bin/python malfunction.py …` (Mac/Linux) or `.runtime\venv\Scripts\python.exe malfunction.py …` (Windows). The private ffmpeg is picked up automatically.

**Without the installer** (your own Python 3.8+ and ffmpeg on PATH): `pip install -r requirements.txt` for the optional extras, and `./malfunction.py --install-ffglitch` for FFglitch. The core needs only the standard library.

## UI

Double-click **`malfunction.command`** in Finder, or run:

```bash
./malfunction_ui.py          # opens http://127.0.0.1:8765
```

It's a local web page served from your own computer only (it listens on 127.0.0.1).

- **Source:** inserted discs and recent videos from this folder, ~/Movies, ~/Desktop and ~/Downloads, plus a native "choose file…" picker.
- **Settings:** a preset, then sliders for keyframe removal, refresh, bloom and databending.
- **Live mosh:** the corrupted stream decoded into the page as it rips, with the frame strip and counters.
- **Stop + keep:** ends the rip early and saves what's done.
- **Stop + discard:** ends the rip and deletes everything it wrote.
- **Renders:** past rips, which you can play inline, reveal in Finder or delete (with their whole folder).

Renders go to `./renders` by default.

## Command line

```bash
./malfunction.py --list                           # show discs / title sets
./malfunction.py --preview                        # rip the main title with the default preset (liquid)
./malfunction.py --preset melt --preview          # classic blocky melt
./malfunction.py --preset rot --keep-clean -o ~/Movies/mosh
./malfunction.py --source /Volumes/MYDISC --title 2 --preset bloom --bloom-len 90
./malfunction.py --source anything.mp4 --preset total --duration 60   # works on any video too
```

Hit `Ctrl-C` at any point and it will finish whatever it has already moshed.

The terminal readout shows a strip of the last frames:

| glyph | meaning |
|---|---|
| `█` | keyframe let through |
| `▓` | keyframe removed and replaced by the previous P-frame |
| `╳` | keyframe deleted outright (`--i-mode drop`) |
| `✺` `∞` | a bloom starting, then repeated frames |
| `░` | databent frame |
| `·` | ordinary delta frame |

## Modes

Every rip has an **engine** (which compressed stream gets corrupted) and a **preset** (how hard and in which ways). The preset picks an engine for you; `--engine` overrides it.

### Engines

| | `flow` | `h264` | `xvid` | `native` |
|---|---|---|---|---|
| What gets corrupted | nothing in a codec: the real pixel motion is measured and a frozen image is dragged along it | a fresh H.264 re-encode | a fresh MPEG-4 ASP (Xvid) re-encode | the DVD's own MPEG-2 frames, straight off the disc |
| Block size | none: every pixel moves on its own | down to 4×4 px, deblocked | 8×8 / 16×16 px | 16×16 px, fixed |
| Working resolution | `--scale` (default 1080p) | `--scale` (default 1080p) | `--scale` (default 1080p) | always 720×480; `--scale` only upscales the result |
| Keyframes | scene cuts (detected from frame differences) | only at scene cuts | only at scene cuts | every ~15 frames (twice a second) |
| Motion hacking (`--mv`) | yes, on the optical-flow field | no (switches to `xvid`) | yes, via FFglitch | yes, via FFglitch |
| Databending | no (no bitstream) | yes | yes | yes |
| Look | liquid marbling: streaks and folds like paint dragged across glass | liquid: smears flow in soft gradients | the classic datamosh: hard-edged shards, every cut melts into the next | constant smear with partial refreshes; B-frames pull in odd backward references |
| Speed | slowest (optical flow per frame) | slow (two H.264 encodes) | medium | fastest (no re-encode) |
| Needs | numpy + OpenCV | – | – (FFglitch for `--mv`) | – (FFglitch for `--mv`) |
| Source | any video | any video | any video | MPEG-2 only (DVD / VOB); anything else falls back to `h264` |

**Which to use:**
- `flow` if you want no blocks at all.
- `h264` if you want it smooth but still codec-made.
- `xvid` for the recognizable 2000s datamosh.
- `native` if the point is that you're corrupting the disc itself. Nothing gets re-encoded, and the pictures stored on the DVD are the ones being damaged.

**How `flow` works:** a codec's P-frames are instructions: "take this block from over there in the previous picture." Datamoshing works by applying those instructions to the wrong picture. The flow engine does the same thing with optical flow (OpenCV's DIS algorithm) instead of codec vectors:

1. It measures where every pixel of the new frame came from in the previous frame.
2. It moves a canvas that never refreshes along that motion.
3. Scene cuts act as keyframes: removed by default, kept with `--drop-i` or `--refresh`.
4. Blooms repeat one flow field.
5. `--flow-leak` lets a little of the real footage bleed back in each frame.

### Presets

| preset | engine | keyframes removed | refresh | blooms | databending | smoothing | character |
|---|---|---|---|---|---|---|---|
| `flow` | flow | all | never | off | off | – | per-pixel melt, no blocks at all |
| `flow-bleed` | flow | all | never | off | off | – | flow melt where moving things and outlines of the real footage break through (`--bleed motion,edges`) |
| `native-bleed` | native | all (partly kept) | never | off | off | off | bands of each removed keyframe still get through (`--bleed slices`) |
| `looper` | h264 | all, plus loop restarts | never | off | off | light | randomized frame looper: 30-frame loops, 4 s per position, each position starts clean (`--loop`) |
| `looper-flow` | flow | all, plus loop restarts | never | off | off | – | the same on the flow engine: 24-frame loops, 5 s per position |
| `looper-slow` | h264 @720p | all, plus loop restarts | never | off | off | light | ultra slow motion: 20-frame loops at ×0.1, interpolated, tape-slowed sound, 14 s per position |
| `flow-swirl` | flow | all | never | every ~12 s, ~40 frames | off | – | flow melt turning in a slow vortex (`--mv swirl`, amount 0.25) |
| `vector` | xvid @720p | all | never | off | off | off | FFglitch: motion averaged over time and pulled downward (`--mv average,sink`, amount 0.4) |
| `echo` | native | all | every 30 s | off | off | off | FFglitch on the disc's MPEG-2: each moment moves with the motion from 3 s earlier (`--mv echo`) |
| `liquid` (default) | h264 | all | never | off | off | light | smooth, flowing melt |
| `liquid-bloom` | h264 | all | never | every ~10 s, ~45 frames | off | light | liquid melt that periodically swells |
| `melt` | xvid | all | never | off | off | off | pure keyframe removal: every cut melts into the next (Murata-style) |
| `bloom` | xvid | all | never | every ~8 s, ~40 frames | off | off | melt plus P-frame blooms |
| `native` | native | all | every 45 s | off | off | off | the disc's own GOPs smearing, with a real image returning every 45 s |
| `rot` | native | 85% | never | every ~20 s, ~20 frames | 35% of frames | off | byte rot: colour smear and block tearing in the slice data |
| `total` | xvid | all | never | every ~4 s, ~30 frames | 12% of frames | off | everything at once |

The `vector` and `echo` presets need FFglitch, and `flow` / `flow-swirl` need numpy + OpenCV. Presets without a resolution setting work at 1080p. Bloom timing is jittered ±50% around the interval, and bloom length ±40%.

### Technique modes

- **Keyframe handling (`--i-mode`)**
  - `hold` (default): swaps each removed keyframe for a copy of the previous P-frame. Timing stays exact, and that frame's motion is applied twice, which gives a small push at every cut.
  - `drop`: deletes the keyframe outright. It's cleaner, but each removal makes the video one frame shorter.
- **Blooms (`--bloom-mode`)**
  - `replace` (default): the repeated P-frame overwrites the frames that follow it. Duration and audio sync are preserved.
  - `insert`: the repeats are added on top, which stretches time. The video ends up longer than the audio.
- **Smoothing (`--smooth`)**: this happens after decoding, at mosh resolution, before any upscaling.
  - `0` off
  - `1` light deblock
  - `2` strong deblock
  - `3` strong deblock at 16 and 8 px plus a slight blur
- **Audio (`--audio`)**
  - `clean`: the disc's soundtrack.
  - `crushed`: the soundtrack through a bitcrusher.
  - `none`: no audio.

### Motion hacking (`--mv`)

Instead of deleting frames, rewrite the motion itself. Pick one or more modes (comma-separated; they apply in order) and a strength with `--mv-amount` (0–1, can go higher).

| mode | what happens to the motion |
|---|---|
| `exaggerate` | every vector scaled up, so motion overshoots and smears |
| `invert` | all motion reversed: things move backward over the image |
| `sink` / `rise` | a constant downward / upward pull; the image drips or floats |
| `drift` | a constant sideways pull |
| `zoom-in` / `zoom-out` | a radial field: the image explodes outward or collapses inward |
| `swirl` | a rotational field: a vortex around the centre |
| `mirror` | the left half's motion drives the right half, mirrored |
| `transpose` | x and y swapped: horizontal motion becomes vertical |
| `echo` | uses the motion from `--mv-delay` frames ago (default 90 ≈ 3 s), so one shot's movement drives another's image |
| `average` | motion smoothed over time: slow, syrupy drift |
| `freeze` | every `--mv-every` seconds, the current motion is locked for `--mv-hold` frames |
| `jitter` | random per-block noise |

Where it happens depends on the engine:

- **`xvid`**: re-encoded with FFglitch's own encoder. `forcemv` gives every block a vector, and `nopimb` stops the image from repairing itself with fresh blocks. Then `ffedit` runs `mv_hack.js` on the motion vectors as the stream passes through.
- **`native`**: `ffedit` rewrites the vectors inside the disc's own MPEG-2. This is motion-vector hacking of the DVD itself.
- **`flow`**: the same modes are applied to the optical-flow field, in `FlowHack` inside `malfunction.py`. No FFglitch is needed, and the result is smooth.
- **`h264`**: FFglitch can't edit H.264, so `--mv` switches to `xvid`.

Keyframe removal, blooms and databending run after the motion hacks, so everything combines. `--mv-script my.js` runs any FFglitch script instead of the built-in one, such as those in [ffglitch-scripts](https://github.com/ramiropolla/ffglitch-scripts).

### Bleed (`--bleed`): letting the real frame back in

A pure mosh never shows the new footage: the old image just keeps moving. `--bleed` decides where the real frame breaks through, and `--bleed-amount` (0–1) decides how much. Modes combine; with more than one, the strongest wins at each pixel.

| mode | where the real footage shows through |
|---|---|
| `motion` | wherever something moves: moving subjects punch through the smear. This is the most like a real datamosh leaking. |
| `edges` | the real scene's outlines, drawn over the mosh |
| `bright` | highlights of the real frame |
| `blocks` | random DVD-sized squares of the real frame pop in, like a codec refreshing blocks |
| `slices` | random horizontal bands of the real frame |
| `uniform` | the whole frame fades in evenly (the older `--flow-leak` does the same) |

**Flow engine:** all modes. What bleeds in becomes part of the canvas and is then smeared along with everything else, so pieces of truth appear and then melt.

**Native engine:** any bleed mode switches on *partial keyframes*. Instead of throwing a removed keyframe away, it keeps a share of its slices (the horizontal rows of blocks MPEG-2 is built from), and the decoder fills the missing rows from the moshed image. Bands of the true picture land in the smear. Partial keyframes show as `▒` in the strip. On many discs the encoder already lets a lot of real image back in by itself, so this can be subtle.

`xvid` and `h264` ignore `--bleed`.

Presets: `flow-bleed` (flow, `motion,edges` at 0.5) and `native-bleed` (native, slices at 0.4).

### Looper (`--loop`): randomized frame loops under the mosh

Instead of reading the film straight through, the looper does this:

1. It picks a random point in the source.
2. It decodes `--loop-frames` frames plus the matching audio.
3. It plays that loop over and over for `--loop-hold` seconds.
4. It jumps to another random point and starts again.

The next position is fetched in the background, so there's no pause at a jump. The looped stream then goes through the chosen engine like any other footage.

**How the mosh sits on the repetition:** when a loop starts over, the picture jumps back a fraction of a second. Within one shot, the encoder codes that jump as an ordinary delta frame that snaps the image back. So the mosh engines treat each loop restart like a keyframe:

- `h264` / `xvid` / `native`: the snap-back frame is swallowed (subject to `--drop-i`).
- `flow`: the restart is treated as a cut.

The next repetition's motion therefore lands on the end of the previous one, and the smear builds up with every pass.

**`--loop-fresh`** (the default) keeps the first keyframe after each jump to a new position, so each position starts clean and decays over its repeats. `--no-loop-fresh` moshes the jumps too.

- **Output length:** with `--loop`, `--duration` sets the length of the *output*. Loops are drawn from the whole title, after `--start` if given.
- **Sound:** the audio loops in sync with the frames.
- **Clean copy:** `--keep-clean` saves the looped edit without the mosh.
- **Engines:** `native` re-encodes the looped frames as DVD-style MPEG-2 without B-frames, so restarts line up with frame numbers.
- **Speed:** `--loop-speed` plays each loop faster or slower: 0.1 is ten times slower, and values above 1 skip frames. `--loop-slow` picks how the extra frames are made:
  - `interpolate`: optical-flow in-betweens (OpenCV DIS). Each in-between frame pulls the frames before and after it along the measured motion and mixes them. This is the smoothest, and it warps where the motion is ambiguous. Without numpy + OpenCV it falls back to ffmpeg's `minterpolate`, which is about 100× slower.
  - `blend`: cross-dissolves, via ffmpeg's `minterpolate` blend mode.
  - `repeat`: held frames, for a stepped look.

  `--loop-slow-audio tape` resamples the sound so its pitch drops with the speed. `stretch` time-stretches it with chained `atempo` filters and keeps the pitch. One pass of a loop lasts `loop-frames / fps / loop-speed` seconds, so raise `--loop-hold` to fit repeats.
- **Jumping on demand:** the UI's **jump to a new position** button tells a running looper to jump (it writes `jump` to the engine's stdin with `--control-stdin`; on Mac/Linux `kill -USR1 <pid>` works too).

### Sound (`--audio-fx`): corrupting the audio with the picture

While moshing, the engine logs one entry per output frame:

- **event**: normal, keyframe kept, keyframe or loop restart removed, bloom start, bloom, or partial keyframe. These are the same events as the strip glyphs.
- **staleness**: frames since the last real keyframe.
- **motion** (0–1):
  - flow engine: the mean optical-flow magnitude.
  - codec engines: the picture's size compared to recent delta frames. A proxy for how much changed.
- **bleed** (0–1): the mean bleed mask on flow, or the kept-slice share on native.

With `--audio-fx`, the soundtrack is captured as uncompressed 48 kHz stereo while the picture is ripped. After the picture is finished, `AudioFX` walks the log and rewrites the audio frame by frame (1/fps s per entry):

| mode | effect |
|---|---|
| `stutter` | On a removed keyframe or swallowed loop restart, the last 30–210 ms repeat 2–9 times, like a skipping CD. |
| `freeze` | On a bloom, a 20–140 ms grain from the bloom's first frame loops for exactly as long as the bloom lasts. |
| `decay` | Staleness / (`--audio-decay` × fps), times the amount, sets the rot. That drives sample-and-hold sample-rate reduction (up to 1/24), bit-depth reduction (up to 13 bits lost) and a moving-average low-pass. A kept keyframe resets it. |
| `motion` | tanh overdrive with drive 1 + 12 × amount × motion. With `--mv echo`, the audio from `--mv-delay` frames earlier is also mixed in. |
| `bleed` | Crossfades back to the clean audio in proportion to the frame's bleed (×2, capped at 1). |

The effects apply in that order. `--audio-fx all` turns on all five, `--audio-fx-amount` (0–1.5) sets the strength, and `--audio-fx none` turns them off. The processing needs numpy. It works on every engine and with the looper; `--audio crushed` is applied before it. The uncompressed soundtrack (about 11 MB per minute) is memory-mapped, so a feature film doesn't need to fit in RAM.

### Why some modes are blockier than others

The visible blocks are the codec's motion blocks: 16×16 pixels in MPEG-2 and Xvid, on a picture only 720×480. Scaled up to a big screen, each one becomes a large square. Two things shrink them. The `h264` engine moves the image in much smaller blocks and smooths their edges. `--scale 1080` moshes at 1080p, so each block covers a smaller part of the frame; use `720` for about twice the speed. `native` can't be made truly smooth, because its blocks are fixed in the disc's data; `--smooth` only softens the edges.

**Sync.** H.264 numbers its pictures (`frame_num`). Removing an IDR keyframe restarts that numbering, and repeating or substituting a picture repeats a number. Either way the decoder sees a gap or a duplicate and silently drops frames: about 10% of them on a clip with many cuts. That pulls the picture out of sync with the sound. So every H.264 picture that leaves the mosh engine gets its `frame_num` rewritten into an unbroken sequence (`H264.renumber`, POC type 2 streams). Now no frames are lost.

Audio and video are also aligned by their start times. DVDs often start the sound a few hundred ms after the picture, so the soundtrack is padded or trimmed to line up with the first video frame.

A last-resort stretch of the finished video remains in the code in case a decoder still loses frames. You'd see "resync: N frames lost…" in the log if it ever kicks in.

## Flags

| flag | what it does |
|---|---|
| `--drop-i 0..1` | chance that a keyframe is removed |
| `--i-mode hold/drop` | `hold` replaces it with the previous P-frame, which keeps timing and double-applies motion; `drop` deletes it |
| `--refresh N` | lets one real keyframe through every N seconds, so the image resets and melts again |
| `--bloom-every S` `--bloom-len F` | every ~S seconds, repeats one P-frame for ~F frames; its motion vectors pile up into a bloom |
| `--bloom-mode replace/insert` | `replace` keeps duration and audio sync; `insert` stretches time |
| `--bend P` `--bend-amount A` | with probability P per frame, overwrites A bytes per 1000 of picture data (never with 00/01, so no fake start codes) |
| `--bend-i` | also databends the keyframes it keeps |
| `--gop` `--q` | xvid engine: max keyframe spacing, and quantizer (a higher `--q` gives chunkier blocks) |
| `--seed N` | the same seed on the same disc gives the same mosh |
| `--audio clean/crushed/none` | `crushed` runs the audio through a bitcrusher |

| `--engine h264/xvid/native` | override the preset's engine |
| `--scale source/720/1080/1440/2160` | working resolution (see Modes) |
| `--smooth 0-3` | post-decode smoothing |
| `--loop` / `--no-loop` | randomized frame looper under the mosh (see Looper) |
| `--loop-frames N` `--loop-hold S` | frames per loop (default 30), seconds per position (default 4) |
| `--loop-fresh` / `--no-loop-fresh` | start each new position from a clean keyframe (default on) |
| `--loop-speed X` | loop playback speed: 1 = normal, 0.1 = ten times slower, above 1 = faster (0.01–4) |
| `--loop-slow interpolate/blend/repeat` | how slow motion is made (default interpolate) |
| `--loop-slow-audio tape/stretch` | slowed sound: pitch drops (tape, default) or pitch kept (stretch) |
| `--audio-fx MODES` | corrupt the sound with the picture: stutter, freeze, decay, motion, bleed, or `all` / `none` (needs numpy) |
| `--audio-fx-amount A` `--audio-decay S` | strength of the sound corruption (default 0.5); seconds without a real keyframe until fully rotted (default 8) |
| `--grain P` | fake film grain over the finished video, in % of full brightness (default 3, 0 = off). It's luminance-only, temporal and applied at full resolution. It softens block edges and banding but makes files much larger. |
| `--mv MODES` `--mv-amount A` | motion hacks (see Motion hacking); `--mv none` turns a preset's hacks off |
| `--mv-delay N` `--mv-hold N` `--mv-every S` | parameters for `echo` and `freeze` |
| `--mv-script FILE` | run your own FFglitch script |
| `--bleed MODES` `--bleed-amount A` | let the real frame show through (see Bleed); `--bleed none` turns a preset's bleed off |
| `--flow-leak L` | flow engine: fraction of the real frame blended in each frame (0 = pure mosh); same idea as `--bleed uniform` |
| `--flow-res W` | flow engine: width optical flow is computed at (default 640; higher is finer and slower) |
| `--flow-interp cubic/linear` | flow engine: canvas resampling (cubic stays sharper over long smears) |
| `--cut-threshold T` | flow engine: how different two frames must be to count as a scene cut |
| `--install-ffglitch` | download FFglitch (into `.runtime/` when the installer has set one up) |

You can override any preset value with these flags.

## Output

Every rip gets its own folder inside the output directory (`./renders` from the UI, `-o` on the command line), named after the rip:

```
renders/
  MYDISC_t01_liquid_20260927-193000/
    MYDISC_t01_liquid_20260927-193000.mp4          the baked mosh + audio
    MYDISC_t01_liquid_20260927-193000.log          ffmpeg / FFglitch log
    MYDISC_t01_liquid_20260927-193000.moshed.264   raw corrupted bitstream
    MYDISC_t01_liquid_20260927-193000.clean.mkv    untouched copy (--keep-clean)
```

- `NAME.mp4`: the baked mosh plus audio.
- `NAME.moshed.m2v` / `.m4v` / `.264`: the raw corrupted bitstream. VLC, mpv, QuickTime and ffplay each decode it differently, which is part of the point. Skip it with `--no-raw`. (The flow engine has no bitstream, so it has no raw file.)
- `NAME.clean.mkv`: an untouched stream copy (`--keep-clean`).
- `NAME.log`: ffmpeg's log, including every decoder complaint.

## Encrypted discs

Most commercial DVDs are CSS-encrypted. malfunction checks the PES scrambling flags and refuses to go on if they're set, because it does not decrypt anything. Use home-burned or unencrypted discs, your own camcorder DVDs, or VIDEO_TS folders.

## Other ways to corrupt it

Ideas beyond what's built in. ✅ = in malfunction now.

- ✅ **Motion vector hacking.** Instead of deleting frames, you rewrite the motion data itself: scale it, flip it, freeze it, or swap it between shots. [FFglitch](https://ffglitch.org) (Ramiro Polla) is the main tool for this. Pixels end up flowing somewhere they were never meant to go. *In malfunction:* `--mv` (see Motion hacking), via FFglitch on `xvid`/`native` or on the optical flow in `flow`.
- ✅ **Optical flow.** The per-pixel cousin of motion-vector moshing: measure the motion with computer vision and drag a stale image along it. *In malfunction:* `--engine flow`.
- **Quantizer matrix swap (native MPEG-2).** The DVD's sequence headers can carry custom quantization tables. Scrambling those shifts every block's texture and color across the whole film without breaking the file. It's cheap to add, and it's very close to Nick Briz's *Glitch Codec Tutorial* idea of hacking the codec's number tables.
- **Header lies.** Rewrite the declared width, aspect ratio or frame rate. A wrong width causes stride shear: diagonal tearing and wrapped images.
- ✅ (partly) **Cross-mosh.** Keep the image from one title or chapter (or another disc) and drive it with P-frames from somewhere else. That transfers motion from one film onto another. *In malfunction:* `--mv echo` does this within one film by driving each moment with motion from `--mv-delay` frames earlier. Motion from a second disc isn't supported yet.
- **P-frame shuffle or reverse.** Reorder the delta frames inside a GOP, so the motion plays back in the wrong order.
- **Wrong-decoder decoding.** Feed the raw stream to a decoder or pixel format it wasn't made for. You get raw YUV read as RGB, or a wrong stride.
- **Sonification.** Push the video bytes through audio processes, the classic Audacity databend: echo, reverb and phaser applied to raw frame data.
- **Generational loss.** Re-encode the moshed output back through the mosh engine several times. You can already do this by hand: use a render as `--source`.

## Lineage

- **Takeshi Murata**, *Monster Movie* (2005): keyframe removal as sculpture; the melt. The `melt` preset is the direct descendant.
- **Nick Briz**, *Glitch Codec Tutorial* (2010–11) and *Thoughts on Glitch[Art]*: the codec as material, the tutorial as essay, and glitch as a way to see an otherwise invisible system. The `native` engine follows that idea by breaking the medium's own compression rather than a transcode of it.
- **Rosa Menkman**, *A Vernacular of File Formats* (2010) and *The Glitch Moment(um)* (2011): every format has its own artifacts, and the glitch is the moment the system shows itself. That's why the three engines look different: each is a different format's vernacular.
- **The datamosh toolmakers**: Avidemux 2.5, tomato.py (Kaspar Ravel), AviGlitch (ucnv), FFglitch (Ramiro Polla). Their I-frame removal and P-frame duplication techniques are the ones used here.

## References

**Artists and writing**

- Takeshi Murata, *Monster Movie*, Smithsonian American Art Museum: https://americanart.si.edu/artwork/monster-movie-86385
- Takeshi Murata (Wikipedia): https://en.wikipedia.org/wiki/Takeshi_Murata
- Nick Briz, *Glitch Codec Tutorial v3*: https://nickbriz.com/databending101/gctv3.html
- Nick Briz, *Thoughts on Glitch[Art] v2.0* (PDF): https://nickbriz.com/thoughtsonglitchart/thoughtsonglitchartv2.0.pdf
- Rhizome, "Artist Profile: Nick Briz" (2013): https://rhizome.org/editorial/2013/jul/15/artist-profile-nick-briz/
- Rosa Menkman, *A Vernacular of File Formats*: https://beyondresolution.info/A-Vernacular-of-File-Formats
- Rosa Menkman, *The Glitch Moment(um)*: https://www.furtherfield.org/the-glitch-momentum/
- Rosa Menkman, "From compression artifact to filter" (2009): http://rosa-menkman.blogspot.com/2009/02/from-compression-artifact-to-filter.html
- Glitch art (Wikipedia): https://en.wikipedia.org/wiki/Glitch_art

**Sound**

- Yasunao Tone, *Solo for Wounded CD* and the aesthetics of failure: https://www.academia.edu/8204212/Yasunao_Tones_Solo_for_Wounded_CD_and_the_Aesthetics_of_Failure
- Yasunao Tone, *MP3 Deviations #6+7*: https://yasunaotone.bandcamp.com/album/mp3-deviations-6-7
- Kim Cascone, "The Aesthetics of Failure" (2000): http://subsol.c3.hu/subsol_2/contributors3/casconetext.html
- Glitch music: Oval, Nicolas Collins, Christian Marclay (Wikipedia): https://en.wikipedia.org/wiki/Glitch_(music)
- Antonio Roberts, "Databending using Audacity": https://www.hellocatfood.com/blog/databending-using-audacity/
- Reilly Spitzfaden, "Databending Part 2: Hacking MP3s": https://reillyspitzfaden.com/posts/2025/02/databending-part-2/

**Techniques and tutorials**

- Yohan Chalier, "Datamoshing" (H.264 IDR removal, optical-flow transfer): https://chalier.fr/blog/datamoshing
- Glitchology, "Datamoshing: How to Glitch Video (Avidemux & FFmpeg)": https://glitchology.com/datamoshing/
- Glitchet Forum, "How to Datamosh, in Plain English": https://forum.glitchet.com/t/tutorial-make-video-glitch-art-how-to-datamosh-in-plain-english/36
- datamoshing.com, "How to datamosh videos": http://datamoshing.com/2016/06/26/how-to-datamosh-videos/
- Group of pictures (I/P/B frames) (Wikipedia): https://en.wikipedia.org/wiki/Group_of_pictures

**Tools**

- FFglitch (motion-vector and bitstream editing): https://ffglitch.org
- FFglitch downloads: https://ffglitch.org/download/
- FFglitch, "Average motion vector tutorial (0.10)": https://ffglitch.org/2024/06/mv_avg_010.html
- FFglitch, "Glitching motion vectors in MPEG-2 files": https://ffglitch.org/2020/07/mv.html
- ffglitch-scripts (Ramiro Polla and contributors): https://github.com/ramiropolla/ffglitch-scripts
- OpenCV DIS optical flow: https://docs.opencv.org/4.x/de/d4f/classcv_1_1DISOpticalFlow.html
- tomato.py (Kaspar Ravel): https://github.com/itsKaspar/tomato
- AviGlitch (ucnv): https://github.com/ucnv/aviglitch
- node-aviglitch: https://github.com/fand/node-aviglitch
- tiberiuiancu/datamoshing (Python + FFglitch): https://github.com/tiberiuiancu/datamoshing
- moshpit (CrushedPixel): https://github.com/CrushedPixel/moshpit
- FFmpeg: https://ffmpeg.org

## Test without a disc

```bash
./make_test_dvd.sh            # builds TESTDISC/VIDEO_TS from ffmpeg test patterns
./malfunction.py --source TESTDISC --preview
```
