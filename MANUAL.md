# malfunction: user manual

This is the hands-on guide: how to get set up, how to make your first rip, what every control does, recipes for particular looks, and what to do when something goes wrong. For how it works inside, the full flag list and references, see [README.md](README.md).

**Contents**

1. [Setup (once)](#1-setup-once)
2. [Your first rip in five steps](#2-your-first-rip-in-five-steps)
3. [A tour of the UI](#3-a-tour-of-the-ui)
4. [Sources: discs, folders and video files](#4-sources-discs-folders-and-video-files)
5. [Choosing a look](#5-choosing-a-look)
6. [Every control, in plain words](#6-every-control-in-plain-words)
7. [Recipes](#7-recipes)
8. [Your renders](#8-your-renders)
9. [Speed and quality](#9-speed-and-quality)
10. [Troubleshooting](#10-troubleshooting)
11. [Command-line quick reference](#11-command-line-quick-reference)
12. [Glossary](#12-glossary)

---

## 1. Setup (once)

**You need:**

- a Mac with Homebrew
- ffmpeg: `brew install ffmpeg`
- Python 3, which Homebrew's ffmpeg usually brings along. If not, run `xcode-select --install`.
- for DVDs, an external DVD drive

**Then double-click `malfunction.command`.** The first time, it checks for the two optional extras, installs any that are missing, then opens the UI in your browser:

- numpy + OpenCV (listed in `requirements.txt`), for the `flow` engine
- FFglitch, for motion-vector hacking. It's downloaded into the `ffglitch` folder.

Once both extras are working, the launcher writes a small hidden file called `.installed`, and every later launch skips the check and opens the UI straight away. To make it check again (after moving the folder or updating Python, say), delete `.installed`: in Terminal, `rm ~/Desktop/Software/malfunction/.installed`.

Leave the Terminal window open while you work. Closing it quits malfunction.

In the UI's **motion hacking** section, check that both extras say **ready**. If one says **missing**, click its install button, or see [Troubleshooting](#10-troubleshooting).

> The first time you double-click, macOS may say the file "can't be opened because it is from an unidentified developer". Right-click `malfunction.command` → **Open** → **Open**. You only need to do this once.

---

## 2. Your first rip in five steps

1. **Insert a DVD** (or skip to step 2 and pick a video file).
2. **Pick the source.** Discs appear at the top of the source list marked `◉`. Click one.
3. **Pick a preset.** Leave it on `liquid` for a first try.
4. **Set a length** of `30` (seconds) so the test is quick. Leave it blank later to rip the whole title.
5. **Click RIP + MOSH.** The screen shows the mosh live. When it finishes, the result plays in the page and appears under **renders**.

Then change one thing at a time (preset, keyframe removal, a motion hack, a bleed mode) and rip the same 30 seconds again. The same **seed** gives the same result, so you can compare fairly (see [seed](#more)).

---

## 3. A tour of the UI

The left column holds the settings, top to bottom. The right side shows the result.

| area | what it's for |
|---|---|
| **source** | what to rip: a disc, a folder or a video file |
| **mosh** | preset, engine, resolution, smoothing, film grain, and the core corruption sliders |
| **looper** | loop a few frames from random points in the source, with the mosh on top |
| **motion hacking** | rewrite where the image moves (the mode chips), plus install status for the extras |
| **bleed** | let the real footage show through the mosh |
| **sound** | corrupt the soundtrack along with the picture |
| **more** | fine controls: keyframe handling, bloom mode, Xvid quality, seed, audio |
| **output** | where renders go, the render name, and extra files to keep |
| **RIP + MOSH** | start |
| **screen** | a live view of the mosh while ripping; the player afterwards |
| **progress line** | percent done, time, speed (×1.0 = real time), and counts of keyframes kept or removed, blooms and bent bytes |
| **stop + keep / stop + discard** | end early and save what's done, or end early and delete everything this rip wrote |
| **jump to a new position** | (looper only, while ripping) move the looper to a new random spot right now |
| **frame strip** | one character per frame (the legend is below it) |
| **renders** | past rips: **play**, **reveal** (in Finder), **delete** |

**Reading the frame strip**

| glyph | meaning |
|---|---|
| █ green | a keyframe was let through: the image resets to the real picture |
| ▓ red | a keyframe was removed: the old image keeps being pushed around by new motion |
| ▒ blue | a keyframe was partly kept (native bleed): bands of real picture |
| ✺ ∞ magenta | a bloom started, then repeated frames |
| ░ yellow | a databent frame |
| · grey | an ordinary frame |

The live view on the screen is a low-resolution preview at a few frames per second. The finished render is full quality. For a smooth full-speed preview, tick **also open ffplay window** under output.

---

## 4. Sources: discs, folders and video files

**The source list** shows inserted discs first, then recent videos from the malfunction folder, ~/Movies, ~/Desktop and ~/Downloads. Click **rescan** after inserting a disc, and **choose file…** to use the Mac file picker. You can also type or paste a path into the **path** box.

**DVDs**

- **title**: a DVD holds several title sets (main film, extras, trailers). Blank means the largest one, usually the main feature. To see them all, run `./malfunction.py --list` in Terminal.
- **start / length** (seconds): rip a section instead of the whole title.
- **Encrypted discs:** most commercial DVDs use CSS copy protection. malfunction detects this and stops with a message. It does not decrypt. Home-burned discs, your own camcorder DVDs and `VIDEO_TS` folders work.

**Video files:** any format ffmpeg can read, including `.mp4`, `.mov`, `.mkv` and `.avi`. The `native` engine needs MPEG-2 (DVD video), so with a normal video file it automatically switches to `h264`.

**Folders:** a copied DVD folder (one containing `VIDEO_TS`) works like a disc.

**Test disc:** `./make_test_dvd.sh` builds `TESTDISC`, 16 seconds of test patterns with hard cuts. It's handy for trying settings without a drive.

---

## 5. Choosing a look

**Start from what you want to see:**

| you want… | start with | then try |
|---|---|---|
| a smooth, liquid melt | `liquid` | raise **resolution**, add **smoothing** |
| no blocks at all, like paint dragged on glass | `flow` | `flow-swirl`, or a motion hack |
| the classic 2000s datamosh: hard shards, cuts melting into each other | `melt` | `bloom` |
| the moving footage visibly breaking through the smear | `flow-bleed` | add **blocks** or **bright** bleed |
| to corrupt the disc itself, with no re-encode | `native` | `native-bleed`, `echo`, `rot` |
| pixels dripping, swirling, exploding outward | `vector` (blocky) or `flow-swirl` (smooth) | motion hacking chips: sink, zoom-in, swirl |
| motion from one moment driving another | `echo` | change **echo delay** |
| colour smear, block tearing, broken data | `rot` | raise **databend** |
| everything at once | `total` | |

**The four engines in one line each:**

- **flow**: measures the real motion and drags a frozen image along it. No blocks, and the slowest.
- **h264**: a smooth melt with small blocks.
- **xvid**: the classic blocky melt. Motion hacks work here.
- **native**: breaks the DVD's own video data. Blocky, fast, and motion hacks work here too.


### The presets explained

There are 16 presets in five families. Each one is just a starting point: after picking one, you can change any control.

**Liquid (`h264` engine: smooth, small blocks)**

| preset | what it does | looks like |
|---|---|---|
| `liquid` (default) | Removes every keyframe; moshes at 1080p with light smoothing. | A smooth, flowing melt: each new shot's motion pushes the old image around in soft gradients. |
| `liquid-bloom` | `liquid`, plus every ~10 s one frame's motion is repeated for ~45 frames. | The same melt, but it periodically swells and streaks. |

**Flow (`flow` engine: optical flow, no blocks at all; needs numpy + OpenCV)**

| preset | what it does | looks like |
|---|---|---|
| `flow` | Measures real pixel motion and drags a frozen image along it; every cut is removed. | Paint dragged across glass: marbling, folds, streaks. |
| `flow-swirl` | `flow`, plus a gentle vortex (the `swirl` motion hack at 0.25) and blooms every ~12 s. | The same marbling, slowly turning around the centre. |
| `flow-bleed` | `flow`, with moving things and outlines of the real footage showing through (bleed `motion` + `edges` at 0.5). | A mosh with the real film visibly breaking through. This is the best start if you want the source recognizable. |

**Classic (`xvid` engine: the 2000s datamosh look)**

| preset | what it does | looks like |
|---|---|---|
| `melt` | Removes every keyframe. | Hard-edged shards; each scene cut melts into the next. The Takeshi Murata look. |
| `bloom` | `melt`, plus blooms every ~8 s (~40 frames). | Shards that periodically balloon and smear. |
| `vector` | `melt` at 720p, with the motion itself rewritten: averaged over time and pulled downward (`average` + `sink` at 0.4; needs FFglitch). | The image slowly drips down the screen, syrupy and heavy. |
| `total` | Everything at once: keyframe removal, blooms every ~4 s, and byte corruption in about 12% of frames. | Maximum chaos. |

**Native (`native` engine: breaks the DVD's own video data, no re-encode)**

| preset | what it does | looks like |
|---|---|---|
| `native` | Removes the disc's keyframes, but lets a real one through every 45 s. | A constant blocky smear that resets and melts again. The disc partly repairs the image by itself, so it's less extreme. |
| `native-bleed` | `native` without the refresh, keeping bands of each removed keyframe (bleed `slices` at 0.4). | Strips of true picture landing in the smear. This can be subtle, since the disc already lets a lot through. |
| `echo` | `native` with the motion replaced by the motion from 3 s earlier (`echo`, needs FFglitch); resets every 30 s. | Each moment moves the way the film moved three seconds ago, so one shot's movement drives another's image. |
| `rot` | `native` with byte corruption in 35% of frames, 85% of keyframes removed, and blooms every ~20 s. | Colour smears, block tearing, broken-data texture. |

**Looper (randomized frame loops under the mosh)**

| preset | what it does | looks like |
|---|---|---|
| `looper` | `h264` engine. Loops 30 frames (1 s) from a random point for 4 s, then jumps to another random point. Each new position starts clean. | A stuttering, repeating fragment that smears a little more with every repetition, then cuts to a fresh fragment elsewhere in the film. |
| `looper-flow` | The same with the `flow` engine: 24-frame loops, 5 s per position. | Each repetition drags the image further along its own motion, like paint being pushed over and over. |
| `looper-slow` | `h264` at 720p. 20 frames played ten times slower (×0.1) with smooth interpolated in-between frames and tape-slowed sound; 14 s per position. | Ultra slow motion: a fraction of a second stretched into a long, drifting, slightly warping moment, with the sound dropped into a deep rumble. The mosh builds up slowly over each pass. |

**Which to try first:**

- For smooth and beautiful: `liquid` or `flow`.
- To keep the film recognizable: `flow-bleed`.
- For the iconic datamosh: `melt`.
- For rhythm and repetition: `looper`.
- For ultra slow motion: `looper-slow`.
- For conceptual pieces about the disc itself: `native`, `echo` or `rot`.

---

## 6. Every control, in plain words

### mosh

- **preset**: loads a starting point into all the controls below it. After choosing a preset you can change anything.
- **engine**: what gets corrupted (see above).
- **resolution**: the size the mosh is made at. Higher means smaller blocks and a sharper result, but slower. `source (480)` is DVD size.
- **smoothing**: softens block edges after the mosh (off / light / medium / heavy). It helps `native` and `xvid` most; it isn't used by `flow`.
- **film grain** (%, default 3): a fine, fake film grain laid over the finished video, on every engine. It's luminance only (no coloured speckle), changes every frame like real grain, and is added at full resolution after any upscaling. At 3% it's subtle: it breaks up flat areas, banding and the stepped edges of blocks. 5–6% reads as visible film grain; 0 turns it off. This setting isn't part of the presets, so switching presets keeps your value. Grain makes files bigger (see [Speed and quality](#9-speed-and-quality)).
- **keyframe removal** (0–1): the chance that each keyframe (a full real picture, usually at a scene cut) is thrown away. 1 is a full mosh: the first image is pushed around for the whole film. At 0.5, about half the cuts melt and half reset.
- **refresh every** (seconds): lets one real keyframe through on a schedule, so the image resets and melts again. 0 means never.
- **bloom every** (seconds) / **bloom length** (frames): every so often, one moment's motion is repeated for a while, so the image swells, streaks and blooms. Timing is randomised a little around these values.
- **databend chance / databend amount**: randomly overwrites bytes inside the compressed picture data. Chance is how many frames get hit; amount is how many bytes per thousand. This gives colour smears, tearing and block garbage. It doesn't apply to `flow`.

### looper

The looper replaces reading the film straight through. It picks a random point in the source, takes a short run of frames and the matching sound, and plays that loop over and over for a few seconds. Then it jumps to another random point and does the same. The mosh runs on top of the repetition: every time a loop starts over, the frame that would snap the picture back to the loop's start is swallowed, so each repetition's motion is painted onto the end of the previous one and the smear builds up.

- **loop random positions**: turns the looper on. The `looper` and `looper-flow` presets turn it on for you.
- **loop length (frames)**: how many frames each loop has. 30 frames is about one second; 2–6 frames gives a fast stutter, and 60 or more gives longer phrases.
- **stay on each position (s)**: how long to keep looping one spot before jumping.
- **start each new position clean**: when ticked (the default), each new position begins with a real, clean frame and the mosh builds up over its repetitions. When unticked, even the jumps are moshed: each new position's motion is painted onto whatever was left from the last one, and the image is never clean.
- **loop speed**: how fast each loop plays. 1 is normal, 0.5 is half speed, 0.1 is ten times slower (ultra slow motion), and 0.02 is fifty times slower. Values above 1 speed the loop up by skipping frames.
- **slow motion**: how the extra frames for slow motion are made.
  - **interpolate** (default): invents in-between frames by following the measured motion. This is the smoothest, true slow-motion feel. Where the motion is ambiguous it warps and tears slightly, which suits the mosh. It uses numpy + OpenCV; without them it falls back to ffmpeg's interpolation, which works but is very slow.
  - **blend**: cross-dissolves between frames. It's smooth and dreamy, with ghosting.
  - **repeat**: holds each frame longer, for a stepped, jerky, undercranked look.
- **slowed sound**: **tape** plays the audio slower so its pitch drops with the speed. At 0.1 voices and music become a deep rumble. **stretch** keeps the pitch and stretches the sound out, which turns it grainy and smeared.
- **The line under these controls** shows how long one pass of the loop lasts at the current settings, and how many passes fit in "stay on each position". Slow motion makes one pass much longer: 30 frames at 0.1 is 10 seconds. If "stay" is shorter than one pass, the loop never repeats, so raise it.
- **jump to a new position**: appears next to the stop buttons while a looper rip is running. It moves to a new random spot immediately; the live preview shows the jump a second or so later, once the encoder catches up.
- **With the looper on, length means the length of the result.** Loops are drawn from anywhere in the title (after **start**, if set). Blank length makes a result as long as the source.
- **Sound:** the audio loops along with the frames, so it stutters in sync.
- **seed:** the same seed gives the same sequence of positions, unless you press jump.
- **Every engine works with the looper.** With `native`, the looped frames are re-encoded as DVD-style MPEG-2 first, since they're no longer the disc's own data.

### motion hacking

Click the chips to turn modes on. You can combine several, and they're applied in order.

| chip | effect |
|---|---|
| exaggerate | all motion scaled up: things overshoot and smear |
| invert | all motion reversed |
| sink / rise | a steady pull down / up: the image drips or floats |
| drift | a steady sideways pull |
| zoom-in / zoom-out | the image explodes outward / collapses inward |
| swirl | a vortex around the centre |
| mirror | the left side's motion drives the right side, mirrored |
| transpose | horizontal motion becomes vertical and vice versa |
| echo | uses the motion from **echo delay** frames ago (90 ≈ 3 seconds), so one shot's movement drives another's image |
| average | motion smoothed over time: slow, syrupy |
| freeze | periodically locks the current motion for a while |
| jitter | random shaking |

- **motion amount**: the strength, from subtle at 0.2 to violent at 1 and above.
- **Which engines:** `flow` works directly. `xvid` and `native` need FFglitch. `h264` switches to `xvid` automatically.

### bleed

Bleed decides where the **real** footage shows through the mosh.

| chip | the real frame shows through… |
|---|---|
| motion | wherever something moves: the most visible and the most "datamosh" |
| edges | as outlines drawn over the smear |
| bright | in the highlights |
| blocks | as random squares |
| slices | as horizontal bands |
| uniform | everywhere, evenly (a fade) |

- **bleed amount** (0–2): how much comes through. The useful range is narrow. Around 0.5 is a real mix. Around 0.7 the real footage dominates, with ghosts of the mosh. Around 1 it's close to the real footage wherever that mode applies. Values above 1 are for footage with little movement, where motion bleed finds less to work with. Blocks and slices build up over time, so high values bring most of the image back within a few seconds.
- **Which engines:** `flow` uses all modes. On `native`, any bleed chip keeps bands of each removed keyframe. `xvid` and `h264` ignore bleed.

### sound

These chips corrupt the soundtrack **in sync with what's happening to the picture**. While it moshes, malfunction logs what happens to every frame: a keyframe removed or kept, a bloom, how long since the last real picture, how much movement, how much bleed. When the picture is finished, that log drives the sound effects frame by frame. Turn on any combination:

| chip | what the sound does | when |
|---|---|---|
| stutter | skips: the last fraction of a second repeats a few times, like a skipping CD | whenever a keyframe (a cut) or a loop restart is moshed away |
| freeze | one grain of sound loops and hangs as a steady buzz | for exactly as long as each bloom lasts |
| decay | the sound rots: bit depth and sample rate drop and it dulls and crackles, getting worse the longer the picture goes without a real keyframe. When a real picture returns, the sound snaps back clean. | continuously, following the picture's staleness |
| motion | overdrive tears the sound open when there's movement in the picture. With the `echo` motion hack on, the sound also echoes from the same **echo delay**. | continuously, following the motion |
| bleed | clean sound returns wherever the real picture bleeds through | with the **bleed** section |

- **sound corruption amount** (0–1.5): the overall strength. It sets how long each skip is and how many times it repeats, how big the frozen grain is, how deep the rot can go, and how hard the motion drives.
- **decay: seconds until fully rotted**: how quickly decay reaches its worst. With keyframe removal at 1 and no refresh, the picture never gets a real frame again, so the sound rots once and stays rotted. Use **refresh every** or the looper's **start each new position clean** to get the rot-and-recover cycle.
- **Every engine works.** How much each effect does depends on the picture: stutter needs cuts (or loop restarts), freeze needs blooms, and bleed needs the **bleed** section (on `flow` or `native`).
- **These settings aren't part of the presets**, so switching presets keeps them. They work together with the **audio** choice under **more**: with `crushed`, the bitcrusher is applied first.
- Sound corruption needs numpy (already installed if the flow engine says **ready**). While ripping, the soundtrack is kept uncompressed, about 11 MB per minute, and is deleted once the render is done.

### more

- **keyframe**: `hold` swaps a removed keyframe for a copy of the previous frame, which keeps timing exact and gives a little push at every cut. `drop` deletes it outright.
- **bloom**: `replace` keeps the video the same length as the audio. `insert` stretches time, so the video ends up longer.
- **xvid quantizer** (2–31): Xvid picture quality. Higher is blockier.
- **xvid max gop**: the most frames allowed between keyframes.
- **seed**: any number. The same seed with the same source and settings gives exactly the same mosh; blank is random every time. Use it to compare settings fairly or to re-render a result you liked.
- **audio**: `clean` is the original soundtrack, `crushed` runs it through a bitcrusher, `none` is silent.

### output

- **folder**: where renders go (default: `renders` inside the malfunction folder). Every rip gets its own subfolder.
- **name**: blank gives an automatic name (source, title, preset, date/time).
- **also save a clean copy**: keeps an untouched copy of the ripped video beside the mosh. With the looper on, the clean copy is the looped edit without the mosh (video only).
- **skip raw moshed bitstream**: doesn't keep the raw corrupted stream (see [Your renders](#8-your-renders)).
- **also open ffplay window**: a separate full-speed live preview window.

---

## 7. Recipes

Each recipe gives UI settings (change only what's listed, after choosing the preset) and the matching command line. Add `--source …` to the command, and `--duration 30` while testing.

**1. Cuts melting into each other (the classic)**

- UI: preset `melt`.
- `./malfunction.py --preset melt`

**2. The same, but smooth and liquid**

- UI: preset `liquid`, resolution 1080p, smoothing light.
- `./malfunction.py --preset liquid`

**3. Paint on glass, with no blocks at all**

- UI: preset `flow`.
- `./malfunction.py --preset flow`

**4. Moving figures breaking through the smear**

- UI: preset `flow-bleed`, bleed chips `motion` + `edges`, bleed amount 0.6.
- `./malfunction.py --preset flow-bleed --bleed-amount 0.6`

**4b. The real footage clearly winning, with the mosh as a ghost**

- UI: preset `flow`, bleed chips `motion` + `edges` + `blocks`, bleed amount 0.7, refresh every 10.
- `./malfunction.py --preset flow --bleed motion,edges,blocks --bleed-amount 0.7 --refresh 10`

**5. Truth arriving in fragments**

- UI: preset `flow`, bleed chips `blocks`, bleed amount 0.4.
- `./malfunction.py --preset flow --bleed blocks --bleed-amount 0.4`

**6. A slow vortex**

- UI: preset `flow-swirl`, motion amount 0.25–0.4.
- `./malfunction.py --preset flow-swirl --mv-amount 0.35`

**7. The film dripping down the screen**

- UI: preset `vector`, chips `sink` (+ `average` for a syrupy feel), motion amount 0.4.
- `./malfunction.py --preset vector`

**8. Exploding outward from the centre**

- UI: engine `xvid`, keyframe removal 1, chips `zoom-in`, motion amount 0.5.
- `./malfunction.py --preset melt --mv zoom-in --mv-amount 0.5`

**9. Each moment moving with the motion from three seconds ago**

- UI: preset `echo` (native engine), echo delay 90.
- `./malfunction.py --preset echo --mv-delay 90`

**10. Breaking the disc's own video, with bands of truth**

- UI: preset `native-bleed`, bleed amount 0.4–0.6.
- `./malfunction.py --preset native-bleed --bleed-amount 0.5`

**11. Rot: colour smear and tearing**

- UI: preset `rot`, databend chance 0.35, databend amount 0.6. Raise both for more.
- `./malfunction.py --preset rot --bend 0.5 --bend-amount 1.0`

**12. Blooming every few seconds**

- UI: preset `liquid-bloom` or `bloom`, bloom every 6, bloom length 60.
- `./malfunction.py --preset bloom --bloom-every 6 --bloom-len 60`

**13. Melt and reset, over and over**

- UI: any preset, refresh every 10.
- `./malfunction.py --preset liquid --refresh 10`

**14. Moshing a mosh (generational loss)**

- UI: rip once, then pick that render as the new **source** and rip it again with another preset.
- `./malfunction.py --source renders/NAME/NAME.mp4 --preset flow-swirl`

**15. A stuttering loop that decays, then cuts elsewhere**

- UI: preset `looper`. Try loop length 12 and stay 6 s for a tighter stutter with more build-up per position.
- `./malfunction.py --preset looper --loop-frames 12 --loop-hold 6`

**16. Ultra slow motion**

- UI: preset `looper-slow`. For even slower, set loop speed 0.05 and raise **stay** so at least one full pass fits (the line under the controls tells you).
- `./malfunction.py --preset looper-slow --loop-speed 0.05 --loop-hold 30`

**17. Slow, stepped and grainy**

- UI: preset `looper`, loop speed 0.2, slow motion **repeat**, slowed sound **stretch**.
- `./malfunction.py --preset looper --loop-speed 0.2 --loop-slow repeat --loop-slow-audio stretch --loop-hold 8`

**18. Endless decay: never starting clean**

- UI: preset `looper-flow`, untick **start each new position clean**.
- `./malfunction.py --preset looper-flow --no-loop-fresh`

**19. Sound that breaks with the picture**

- UI: preset `bloom`, sound chips `stutter` + `freeze` + `decay`, refresh every 15. The cuts skip, the blooms hang, and the sound rots and recovers with the image.
- `./malfunction.py --preset bloom --refresh 15 --audio-fx stutter,freeze,decay`

**20. A looper that sounds like a skipping CD**

- UI: preset `looper`, sound chips `stutter` + `decay`, sound corruption amount 0.8.
- `./malfunction.py --preset looper --audio-fx stutter,decay --audio-fx-amount 0.8`

**21. Everything, picture and sound**

- UI: preset `flow-bleed`, bleed chip `motion`, all five sound chips.
- `./malfunction.py --preset flow-bleed --audio-fx all`

**22. Re-rendering one you liked, at higher quality**

- UI: note the seed you used (or set one before ripping), then rip again with the same seed at a higher resolution. Results with `flow` or `blocks` bleed can shift slightly at a different resolution.
- `./malfunction.py --preset melt --seed 1234 --scale 1440`

---

## 8. Your renders

Every rip gets its own folder inside `renders/`:

```
renders/
  MYDISC_t01_liquid_20260927-193000/
    MYDISC_t01_liquid_20260927-193000.mp4          ← the result: mosh + audio
    MYDISC_t01_liquid_20260927-193000.log          ← what ffmpeg / FFglitch said
    MYDISC_t01_liquid_20260927-193000.moshed.264   ← raw corrupted stream
    MYDISC_t01_liquid_20260927-193000.clean.mkv    ← untouched copy (if ticked)
```

- **The `.mp4`** is "baked": the glitch is frozen into ordinary H.264, so it looks the same everywhere (QuickTime, browsers, editing software, projectors).
- **The raw stream** (`.m2v`, `.m4v` or `.264`) is the broken data itself, before baking. Different players decode it differently, so open it in VLC, mpv and ffplay for three different results. The `flow` engine has no raw stream.
- **In the UI:** **play** shows a render in the page, **reveal** opens its folder in Finder, and **delete** removes the whole folder after asking.
- **Stop + keep** saves a shorter render of what was done. **Stop + discard** leaves nothing behind.

---

## 9. Speed and quality

The progress line shows speed: ×1.0 means real time, and ×0.5 means a 10-minute title takes 20 minutes.

**From fastest to slowest:** `native` → `xvid` → `h264` → `flow`. Motion hacking adds a little; bleed adds a little to `flow`.

**To go faster:**

- lower **resolution** (720p is about twice as fast as 1080p)
- with slow motion, **interpolate** takes the most work; **blend** and **repeat** cost almost nothing
- test on 30 seconds with **length** before ripping a whole film
- use `native` or `xvid`

**To look better:**

- raise **resolution**
- use `h264` or `flow` for smoothness
- add **smoothing** on `native` / `xvid`

**Disk space:** the baked `.mp4` of a feature film at 1080p is often several GB. Heavily moshed video compresses badly, and film grain makes it much bigger again: random grain is the hardest thing for an encoder to compress. On a test clip, 3% grain made the file about five times larger. To save space, lower the grain, or raise the bake quality number slightly with `--crf 18` on the command line (about 25% smaller, and the grain survives). Around `--crf 22` the encoder smooths the grain away entirely. The raw stream and the clean copy add more; turn them off under output if you don't need them.

---

## 10. Troubleshooting

| problem | fix |
|---|---|
| Double-clicking `malfunction.command` does nothing / "unidentified developer" | Right-click → **Open** → **Open** (once). |
| The Terminal window flashes and closes | Run it by hand to see the error: `cd ~/Desktop/Software/malfunction && python3 malfunction_ui.py` |
| "port 8765 is busy" | malfunction is already running in another Terminal window. Use that one, or close it and relaunch. |
| "ffmpeg not found" | `brew install ffmpeg` |
| "externally-managed-environment" during install | This is normal on Homebrew Python. The launcher retries automatically, and the lines after it should say "Successfully installed". |
| flow engine **missing** | Click **install numpy + OpenCV**, or run `python3 -m pip install --user --break-system-packages -r requirements.txt` |
| FFglitch **missing** / "motion-vector hacking needs FFglitch" | Click **install FFglitch**, or run `./malfunction.py --install-ffglitch` |
| "this disc looks encrypted" | A commercial CSS-protected disc. malfunction can't read it; use an unencrypted disc or a video file. |
| No disc in the source list | Click **rescan**. Check that the disc shows up in Finder. Or type its path, like `/Volumes/DISC_NAME`. |
| Sound out of sync with the picture | This was a bug in earlier versions on the `h264` engine (the default `liquid` look and the looper) and is fixed; re-render with the current version. If it still happens, send me the rip's `.log`. |
| "resync: N frames lost…" in the log | A safety net: the decoder lost some frames and the video was stretched to keep the length right. It shouldn't happen any more; if it does, sync may be slightly off, so send me the log. |
| Very slow | Lower **resolution**, use a faster engine, test with **length**. |
| The sound isn't corrupted | Check that a **sound** chip is on and **audio** isn't `none`. It needs numpy ("⚠ --audio-fx needs numpy" in the log). Stutter only happens at moshed cuts and freeze only during blooms, so a short test without cuts may sound clean. |
| The result looks almost clean | Keyframe removal is below 1, **refresh** is on, or bleed is high. On `native`, the disc itself refreshes a lot; try `xvid`, `h264` or `flow`. |
| The image goes to mush and never recovers | That's a full mosh. Add **refresh every** or a **bleed** mode. |
| Something else | Open the rip's `.log` file in its render folder, and check the Terminal window. |

---

## 11. Command-line quick reference

Everything in the UI is also available from Terminal, in the malfunction folder:

```bash
./malfunction.py --list                                  # discs and titles
./malfunction.py --preset liquid --preview               # rip the main title, live preview window
./malfunction.py --source /Volumes/DISC --title 2 --start 60 --duration 30 --preset flow-bleed
./malfunction.py --source clip.mp4 --preset vector --mv sink,zoom-in --mv-amount 0.6
./malfunction.py --source clip.mp4 --preset flow --bleed motion,blocks --bleed-amount 0.5 --seed 7
./malfunction.py -o ~/Movies/mosh --name test1 --keep-clean --audio crushed
./malfunction.py --install-ffglitch
./malfunction.py -h                                      # every flag
```

Press `Ctrl-C` to stop and keep what's done.

---

## 12. Glossary

- **Keyframe (I-frame):** a complete picture stored in the video. Everything between keyframes is stored as changes.
- **P-frame (delta frame):** "take the previous picture and move these blocks like this." Datamoshing works by applying P-frames to the *wrong* previous picture.
- **B-frame:** like a P-frame, but it can also borrow from a *future* picture. DVDs use them; malfunction's re-encodes don't.
- **GOP:** a group of pictures, one keyframe plus the changes after it. DVDs use short GOPs (about half a second).
- **Macroblock:** the 16×16-pixel square that MPEG-2 and Xvid move around. This is why moshes look blocky.
- **Motion vector:** the "move this block from over there" instruction inside a P-frame. Motion hacking rewrites these.
- **Optical flow:** motion measured by computer vision for every pixel instead of every block. The `flow` engine uses it.
- **Bloom:** one frame's motion repeated many times, so the image swells and streaks.
- **Databending:** corrupting bytes of a file directly.
- **Bake:** re-encoding the corrupted stream into a normal video so the glitch looks the same in every player.
- **Bleed:** letting parts of the real picture back into the mosh.
- **Seed:** a number that fixes all the random choices, so a result can be reproduced.
