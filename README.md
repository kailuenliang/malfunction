# malfunction

A DVD ripper that **datamoshes the video while it rips**. Put in a disc or pick any video file, choose a look, and watch the picture melt live. You get a finished `.mp4` with sound.

It follows the glitch-art tradition of Takeshi Murata, Nick Briz and Rosa Menkman: the codec itself is the material.

## Install

Download **[malfunction.zip](https://github.com/kailuenliang/malfunction/releases/latest/download/malfunction.zip)** and unzip it. Then:

| | first time | after that |
|---|---|---|
| **Mac** | Open Terminal, type `bash ` (with a space), drag `malfunction.command` into the window, press Enter | double-click `malfunction.command` |
| **Windows** | Double-click `malfunction.bat`. If a blue box appears: **More info → Run anyway** | double-click `malfunction.bat` |

The first run downloads about 600 MB (its own Python, ffmpeg and FFglitch) into a hidden `.runtime` folder **inside** malfunction. Nothing else on the computer is changed, and no admin password is needed. **To uninstall, delete the folder.**

Step-by-step for students: [START HERE.txt](START%20HERE.txt).

## Use it

malfunction opens in your web browser.

1. **Source:** pick a disc, or any video file (mp4, mov, mkv…).
2. **Preset:** pick a look. `liquid` is a good start.
3. **RIP + MOSH:** watch it melt live. **Stop + keep** saves what's done; **stop + discard** throws it away.
4. **Renders:** each rip gets its own folder in `renders/` with the video and its log.

Commercial DVDs are copy-protected and won't work. Use home-burned or camcorder DVDs, VIDEO_TS folders, or any video file.

## Presets

| family | presets | look |
|---|---|---|
| Smooth melt | **`liquid`** (default), `liquid-bloom` | soft, flowing smears; the bloom version swells now and then |
| Classic datamosh | `melt`, `bloom`, `total` | hard-edged blocks, every cut melts into the next |
| The disc itself | `native`, `rot`, `native-bleed` | corrupts the DVD's own MPEG-2 frames; `rot` adds byte damage |
| No blocks at all | `flow`, `flow-swirl`, `flow-bleed` | per-pixel melt, like paint dragged across glass |
| Motion hacking | `vector`, `echo` | rewrites the motion itself: dripping, swirling, borrowed movement |
| Looper | `looper`, `looper-flow`, `looper-slow` | random short loops jump around the film and mosh as they repeat; `looper-slow` is ultra slow motion |

## What you can change

| control | what it does |
|---|---|
| keyframe removal | removes the fresh pictures, so old images get dragged by new motion (the core datamosh) |
| refresh | lets a clean picture through every N seconds |
| bloom | repeats one movement until it smears outward |
| databend | overwrites random bytes: color tears and block noise |
| motion hacking | sink, swirl, zoom, invert, echo… applied to the motion |
| bleed | lets the real footage break back through the smear |
| looper | loop length, time per spot, speed and slow motion, plus a **jump** button |
| sound | the audio stutters, freezes, decays and distorts with the picture |
| film grain | subtle grain over the result (3% by default) |

The [MANUAL](MANUAL.md) explains every control and has recipes for specific looks.

## Command line

```bash
.runtime/venv/bin/python malfunction.py --source video.mp4 --preset melt --preview
.runtime/venv/bin/python malfunction.py --list        # show discs
```

On Windows use `.runtime\venv\Scripts\python.exe`. Every flag is listed in [REFERENCE.md](REFERENCE.md).

## Docs

- [START HERE.txt](START%20HERE.txt): install, for students
- [MANUAL.md](MANUAL.md): the full guide, with controls, recipes and troubleshooting
- [REFERENCE.md](REFERENCE.md): how it works inside, every flag, more corruption ideas and the full reading list

## Sources and inspirations

### Artists and writing

- **Takeshi Murata**, *Monster Movie* (2005): keyframe removal as sculpture. The `melt` preset descends from it. [Smithsonian American Art Museum](https://americanart.si.edu/artwork/monster-movie-86385) · [Wikipedia](https://en.wikipedia.org/wiki/Takeshi_Murata)
- **Nick Briz**: the codec as material, and glitch as a way to see an invisible system. The `native` engine breaks the disc's own compression in that spirit. [*Glitch Codec Tutorial v3*](https://nickbriz.com/databending101/gctv3.html) · [*Thoughts on Glitch[Art] v2.0*](https://nickbriz.com/thoughtsonglitchart/thoughtsonglitchartv2.0.pdf) · [Rhizome profile](https://rhizome.org/editorial/2013/jul/15/artist-profile-nick-briz/)
- **Rosa Menkman**: every format has its own artifacts, which is why each engine looks different. [*A Vernacular of File Formats*](https://beyondresolution.info/A-Vernacular-of-File-Formats) · [*The Glitch Moment(um)*](https://www.furtherfield.org/the-glitch-momentum/) · ["From compression artifact to filter"](http://rosa-menkman.blogspot.com/2009/02/from-compression-artifact-to-filter.html)
- **Sound:** Yasunao Tone ([*Solo for Wounded CD*](https://www.academia.edu/8204212/Yasunao_Tones_Solo_for_Wounded_CD_and_the_Aesthetics_of_Failure), [*MP3 Deviations*](https://yasunaotone.bandcamp.com/album/mp3-deviations-6-7)), Oval, Nicolas Collins and Christian Marclay ([glitch music](https://en.wikipedia.org/wiki/Glitch_(music))), and Kim Cascone, ["The Aesthetics of Failure"](http://subsol.c3.hu/subsol_2/contributors3/casconetext.html) (2000). The stutter, freeze and decay effects come from this lineage.
- [Glitch art (Wikipedia)](https://en.wikipedia.org/wiki/Glitch_art)

### Techniques and tutorials

- Yohan Chalier, ["Datamoshing"](https://chalier.fr/blog/datamoshing): H.264 keyframe removal and optical-flow transfer, the techniques behind the `h264` and `flow` engines
- FFglitch, ["Glitching motion vectors in MPEG-2 files"](https://ffglitch.org/2020/07/mv.html) and ["Average motion vector tutorial"](https://ffglitch.org/2024/06/mv_avg_010.html): the basis of motion hacking (`mv_hack.js`)
- [Glitchology: Datamoshing with Avidemux & FFmpeg](https://glitchology.com/datamoshing/) · [Glitchet: How to Datamosh, in Plain English](https://forum.glitchet.com/t/tutorial-make-video-glitch-art-how-to-datamosh-in-plain-english/36) · [datamoshing.com](http://datamoshing.com/2016/06/26/how-to-datamosh-videos/)
- Antonio Roberts, [Databending using Audacity](https://www.hellocatfood.com/blog/databending-using-audacity/) · Reilly Spitzfaden, [Databending Part 2: Hacking MP3s](https://reillyspitzfaden.com/posts/2025/02/databending-part-2/)
- [Group of pictures: I, P and B frames (Wikipedia)](https://en.wikipedia.org/wiki/Group_of_pictures)

### Earlier datamosh tools

The keyframe removal and P-frame repetition here follow these tools:
[tomato.py](https://github.com/itsKaspar/tomato) (Kaspar Ravel) · [AviGlitch](https://github.com/ucnv/aviglitch) (ucnv) · [node-aviglitch](https://github.com/fand/node-aviglitch) · [tiberiuiancu/datamoshing](https://github.com/tiberiuiancu/datamoshing) · [moshpit](https://github.com/CrushedPixel/moshpit) (CrushedPixel) · Avidemux 2.5 · [ffglitch-scripts](https://github.com/ramiropolla/ffglitch-scripts)

### Built with

malfunction itself is plain Python. It runs on these projects, which the installer downloads; none of them are included in this repository.

| project | used for |
|---|---|
| [FFmpeg](https://ffmpeg.org) | reading discs and videos, encoding, preview; builds from [martin-riedl.de](https://ffmpeg.martin-riedl.de) (Mac, Linux) and [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) (Windows) |
| [FFglitch](https://ffglitch.org) (Ramiro Polla) | motion-vector editing |
| [OpenCV](https://opencv.org) | optical flow ([DIS](https://docs.opencv.org/4.x/de/d4f/classcv_1_1DISOpticalFlow.html)) for the flow engine and slow motion |
| [NumPy](https://numpy.org) | image and sound processing |
| [uv](https://github.com/astral-sh/uv) and [python-build-standalone](https://github.com/astral-sh/python-build-standalone) | the private Python install |
| [truststore](https://github.com/sethmlarson/truststore), [certifi](https://github.com/certifi/python-certifi) | secure downloads on school networks |
