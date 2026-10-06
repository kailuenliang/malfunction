# malfunction: audio glitch ideas

Ideas for corrupting the soundtrack. **Option A (all five) is now built in** as `--audio-fx` (the **sound** section of the UI; see the README and MANUAL). Options B and C are still parked. The core idea: the video mosh already knows, frame by frame, when a keyframe is removed, when a bloom starts, when bytes are bent and how much things move. Each of those events can trigger a matching audio corruption at the same moment, so sound and image break together.

The audio currently has only `--audio clean | crushed | none`, where `crushed` is a static bitcrusher.

## What's been tested

**AC-3 (Dolby Digital, the usual DVD audio) survives byte corruption.** AC-3 is compressed in fixed frames of 1536 samples (32 ms at 48 kHz), each starting with the sync word `0x0B77`. I overwrote random bytes inside each frame, leaving the first 8 bytes and the last 2 alone, and decoded with ffmpeg (2026-09-30, a test tone of 220 + 660 Hz at 192 kbps):

| corruption | result |
|---|---|
| 1 byte per frame | Still plays at exactly the right length. The tones survive, with scattered clicks and short bursts of broadband noise. |
| 4 bytes per frame | Dense crackle and noise bursts across the whole spectrum, with pitched artifacts. The signal differs from the original by about 130%. |
| 20 bytes per frame | Mostly noise, but the length is still exact. |

The decoder reports errors ("exponent out of range", "invalid coupling range", "error decoding the audio block") but keeps going, and nothing goes silent. So the audio can be databent at the codec level, in the same spirit as the `native` video engine.

## The options

### A. Driven by the video mosh (in sync, conceptually tied): ✅ built (`--audio-fx`)

1. **Stutter on removed keyframes.** When a cut is moshed away, the audio repeats its last fraction of a second, like a skipping CD (the Yasunao Tone / Oval move), triggered by the image's own failure.
2. **Freeze on blooms.** While a bloom repeats one frame's motion, the audio loops the matching slice of sound for the same length, so image and sound hang together.
3. **Decay with staleness.** The longer the image goes without a real keyframe, the more the audio degrades: bit depth and sample rate drop, and the sound dulls. When a real keyframe returns, the audio snaps back clean. The sound rots exactly as far as the picture has.
4. **Motion drives sound.** Measured motion (from the flow engine or the motion vectors) controls a filter or distortion, so fast movement tears the sound open. The motion hacks could map too: `echo` would also echo the audio from the same number of frames back.
5. **Bleed for audio.** When the real picture bleeds through (`--bleed`), the clean soundtrack bleeds through in proportion.

### B. Corrupting the audio's own data (the parallel to the `native` engine)

6. **AC-3 databending.** The byte corruption tested above, triggered whenever video frames are databent, or at its own rate.
7. **AC-3 frame repeat/drop.** Repeat or skip whole 32 ms audio frames at the codec level. It's a harsher, more mechanical stutter than option 1.

### C. Sonification (hearing the data itself)

8. **The sound of the corruption.** The moshed video bitstream's raw bytes played as audio and mixed under the soundtrack. This is the classic Audacity databend trick, but live from the rip: you literally hear the broken data.
9. **Wrong-format reading.** Audio samples reinterpreted at the wrong sample rate, bit depth or byte order, for pitched, torn, time-smeared textures.

### Suggested first set

Options 1–3 (stutter, freeze, decay), 6 (AC-3 databend) and 8 (the sound of the corruption):

- The first three make the sound behave like the image.
- Option 6 corrupts the disc's own audio data, in the spirit of the `native` engine.
- Option 8 is the most direct "hear the glitch" idea.

Each would get its own on/off chip and amount in the UI, like motion hacking and bleed, and work on every engine.

## Implementation notes

- DVD audio is usually AC-3; some discs use MPEG-1 Layer 2 or LPCM. Byte-level bending (option 6) needs a per-format frame parser. AC-3 frames are easy to find by their `0x0B77` sync word.
- Option A is implemented as a per-frame event log written by the mosh engines, plus `AudioFX`, which rewrites the uncompressed soundtrack after the picture is done. Options B and C could use the same log. B would need the raw AC-3 frames kept too; C would need the moshed bitstream bytes, which are already available in the raw moshed stream file.
- The looper's audio follows the looped video, and the option A effects work on top of it.

## Lineage and references

- **Yasunao Tone** stuck tape on CDs to make the laser misread them, starting in the mid-1980s (*Music for 2 CD Players*, 1986; *Solo for Wounded CD*). Later, in *MP3 Deviations*, he turned the error messages from corrupted MP3 processing into material. [Solo for Wounded CD and the Aesthetics of Failure](https://www.academia.edu/8204212/Yasunao_Tones_Solo_for_Wounded_CD_and_the_Aesthetics_of_Failure) · [Review of MP3 Deviations #6+7](https://jpburnett.wordpress.com/2012/12/10/a-liminal-review-mp3-deviations-6-7-by-yasunao-tone-november-7th-2011/) · [MP3 Deviations #6+7 (Bandcamp)](https://yasunaotone.bandcamp.com/album/mp3-deviations-6-7)
- **Oval**: albums built from damaged CDs (*Systemisch*, 1994; *94 Diskont*, 1995). **Nicolas Collins**: CD skipping in *It Was a Dark and Stormy Night* (1992). **Christian Marclay**: broken vinyl since 1979. [Glitch (music), Wikipedia](https://en.wikipedia.org/wiki/Glitch_(music))
- **Kim Cascone**, "The Aesthetics of Failure: Post-Digital Tendencies in Contemporary Computer Music" (2000): the essay that named the practice. [Text](http://subsol.c3.hu/subsol_2/contributors3/casconetext.html)
- **MP3 hex-editing**: protect the frame headers and change the data between them, for "watery burbling" and "bursts of white noise". [Databending Part 2: Hacking MP3s](https://reillyspitzfaden.com/posts/2025/02/databending-part-2/)
- **Sonification / databending with Audacity** (Antonio Roberts): [Databending using Audacity](https://www.hellocatfood.com/blog/databending-using-audacity/)
- **AC-3 specification**: [ATSC A/52:2018](https://www.atsc.org/wp-content/uploads/2021/04/A52-2018.pdf)
