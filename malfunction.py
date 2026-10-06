#!/usr/bin/env python3
"""
m a l f u n c t i o n
a DVD ripper that datamoshes the disc while it reads it.

Pipeline (everything streams; nothing waits for the rip to finish):

  DVD (VIDEO_TS/*.VOB) ──ffmpeg──▶ raw compressed video bitstream
                                    │   (native: the disc's own MPEG-2,
                                    │    xvid:   re-encoded MPEG-4 ASP)
                                    ▼
                              [ MOSH ENGINE ]  ◀── python, frame by frame:
                                    │              · I-frame removal
                                    │              · P-frame bloom
                                    │              · databending
                                    ├──────────▶ ffplay  (live preview)
                                    ├──────────▶ .m2v/.m4v (raw moshed stream)
                                    ▼
                         ffmpeg decode ─▶ H.264 "bake" ─▶ final .mp4 (+ audio)

Only the Python standard library is used. Requires ffmpeg/ffprobe (ffplay for --preview).
Reads unencrypted discs and VIDEO_TS folders; it does not decrypt CSS.
"""

import argparse
import collections
import glob
import json
import os
import queue
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

VERSION = "0.1.0"

# ────────────────────────────────────────────────────────────────────────────
#  terminal cosmetics
# ────────────────────────────────────────────────────────────────────────────

TTY = sys.stderr.isatty()


def c(code, s):
    return f"\x1b[{code}m{s}\x1b[0m" if TTY else s


RED, GRN, YEL, BLU, MAG, CYN, DIM, INV = "31", "32", "33", "34", "35", "36", "2", "7"

BANNER = r"""
 ███▄ ▄███▓ ▄▄▄       ██▓      █████▒█    ██  ███▄    █  ▄████▄  ▄▄▄█████▓ ██▓ ▒█████   ███▄    █
▓██▒▀█▀ ██▒▒████▄    ▓██▒    ▓██   ▒ ██  ▓██▒ ██ ▀█   █ ▒██▀ ▀█  ▓  ██▒ ▓▒▓██▒▒██▒  ██▒ ██ ▀█   █
▓██    ▓██░▒██  ▀█▄  ▒██░    ▒████ ░▓██  ▒██░▓██  ▀█ ██▒▒▓█    ▄ ▒ ▓██░ ▒░▒██▒▒██░  ██▒▓██  ▀█ ██▒
▒██    ▒██ ░██▄▄▄▄██ ▒██░    ░▓█▒  ░▓▓█  ░██░▓██▒  ▐▌██▒▒▓▓▄ ▄██▒░ ▓██▓ ░ ░██░▒██   ██░▓██▒  ▐▌██▒
▒██▒   ░██▒ ▓█   ▓██▒░██████▒░▒█░   ▒▒█████▓ ▒██░   ▓██░▒ ▓███▀ ░  ▒██▒ ░ ░██░░ ████▓▒░▒██░   ▓██░
"""


def glitch_text(s, amount=0.08, rng=random):
    junk = "▓▒░█▄▀■□▪▫◘◙"
    return "".join(rng.choice(junk) if ch != " " and rng.random() < amount else ch for ch in s)


def log(msg=""):
    print(msg, file=sys.stderr, flush=True)


def die(msg):
    log(c(RED, "✖ " + msg))
    sys.exit(1)


# ────────────────────────────────────────────────────────────────────────────
#  bitstream tokenizer
# ────────────────────────────────────────────────────────────────────────────
#  Both MPEG-2 video and MPEG-4 Part 2 are sequences of "start codes"
#  (00 00 01 xx) followed by payload. We split the stream at start codes,
#  then group tokens into units of exactly one picture (plus any headers
#  that precede it). A unit is the atom the mosh engine operates on.

SC = b"\x00\x00\x01"


class Codec:
    name = ""
    raw_format = ""   # ffmpeg demuxer/muxer name for the raw elementary stream
    ext = ""

    def is_picture(self, code): ...
    def starts_unit(self, code): ...
    def picture_type(self, tok): ...          # 'I' | 'P' | 'B' | 'S'
    def bend_ranges(self, tok): ...           # byte ranges safe-ish to corrupt
    def fix_headers(self, tok): return tok    # patch headers after an I-drop


class MPEG2(Codec):
    """The DVD's own video. Picture start code = 00 00 01 00."""
    name, raw_format, ext = "mpeg2", "mpegvideo", "m2v"

    def is_picture(self, code):
        return code == 0x00

    def starts_unit(self, code):
        # sequence header, GOP header, picture header
        return code in (0xB3, 0xB8, 0x00)

    def picture_type(self, tok):
        # 10 bits temporal_reference, then 3 bits picture_coding_type
        if len(tok) < 6:
            return "?"
        return {1: "I", 2: "P", 3: "B"}.get((tok[5] >> 3) & 7, "?")

    def bend_ranges(self, tok):
        # slices only (01..AF). skip slice header bytes.
        code = tok[3]
        if 0x01 <= code <= 0xAF and len(tok) > 10:
            return (8, len(tok))
        return None

    def fix_headers(self, tok):
        # GOP header: clear closed_gop + broken_link so the decoder keeps
        # B-frames that now point at the wrong reference (that's the point).
        if tok[3] == 0xB8 and len(tok) >= 8:
            t = bytearray(tok)
            t[7] &= ~0x60 & 0xFF
            return bytes(t)
        return tok


class MPEG4(Codec):
    """MPEG-4 ASP ("xvid"). VOP start code = 00 00 01 B6."""
    name, raw_format, ext = "mpeg4", "m4v", "m4v"

    def is_picture(self, code):
        return code == 0xB6

    def starts_unit(self, code):
        # VOS, GOV, VO (00-1F), VOL (20-2F), VOP
        return code in (0xB0, 0xB3, 0xB6) or code <= 0x2F

    def picture_type(self, tok):
        if len(tok) < 5:
            return "?"
        return "IPBS"[tok[4] >> 6]

    def bend_ranges(self, tok):
        if tok[3] == 0xB6 and len(tok) > 24:
            return (16, len(tok))
        return None


def _read_ue(data, bitpos):
    """Exp-Golomb unsigned read (H.264). Returns (value, new_bitpos)."""
    zeros = 0
    while True:
        byte = data[bitpos >> 3] if (bitpos >> 3) < len(data) else 0
        bit = (byte >> (7 - (bitpos & 7))) & 1
        bitpos += 1
        if bit:
            break
        zeros += 1
        if zeros > 31:
            return 0, bitpos
    val = 0
    for _ in range(zeros):
        byte = data[bitpos >> 3] if (bitpos >> 3) < len(data) else 0
        val = (val << 1) | ((byte >> (7 - (bitpos & 7))) & 1)
        bitpos += 1
    return (1 << zeros) - 1 + val, bitpos


class H264(Codec):
    """H.264 Annex B. 4x4 blocks, quarter-pixel motion and an in-loop
    deblocking filter make the mosh flow like liquid instead of tiles.
    Access units are delimited by AUD NALs (x264 aud=1)."""
    name, raw_format, ext = "h264", "h264", "264"

    def is_picture(self, code):
        return (code & 0x1F) in (1, 5)

    def starts_unit(self, code):
        return (code & 0x1F) == 9          # access unit delimiter

    def picture_type(self, tok):
        t = tok[3] & 0x1F
        if t == 5:
            return "I"                     # IDR
        _, bp = _read_ue(tok, 4 * 8)       # first_mb_in_slice
        st, _ = _read_ue(tok, bp)          # slice_type
        return {0: "P", 1: "B", 2: "I", 3: "P", 4: "I"}.get(st % 5, "?")

    def bend_ranges(self, tok):
        if (tok[3] & 0x1F) in (1, 5) and len(tok) > 40:
            return (24, len(tok))
        return None

    # ── frame renumbering ────────────────────────────────────────────────────
    # H.264 numbers every reference picture (frame_num). A removed IDR restarts
    # the numbering, and a repeated or substituted picture repeats a number –
    # either way the decoder sees a gap or a duplicate and silently throws
    # frames away, which pushes the picture out of sync with the sound.
    # So every picture that goes out gets the next number in an unbroken run.
    def __init__(self):
        self.fn_bits = None            # log2_max_frame_num, from the SPS
        self.fn_ok = False             # False → leave the stream alone
        self.fn_next = 0
        self.renumbered = 0

    @staticmethod
    def _unescape(b):
        out, z = bytearray(), 0
        for x in b:
            if z >= 2 and x == 3:
                z = 0
                continue
            out.append(x)
            z = z + 1 if x == 0 else 0
        return out

    @staticmethod
    def _escape(b):
        out, z = bytearray(), 0
        for x in b:
            if z >= 2 and x <= 3:
                out.append(3)
                z = 0
            out.append(x)
            z = z + 1 if x == 0 else 0
        return out

    def _parse_sps(self, tok):
        try:
            r = self._unescape(tok[4:64])
            profile = r[0]
            bp = 24
            _, bp = _read_ue(r, bp)                                # sps id
            if profile in (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135):
                cf, bp = _read_ue(r, bp)
                if cf == 3:
                    return                                         # separate colour planes: not handled
                _, bp = _read_ue(r, bp)
                _, bp = _read_ue(r, bp)
                bp += 1                                            # qpprime_y_zero_transform_bypass
                if (r[bp >> 3] >> (7 - (bp & 7))) & 1:
                    return                                         # scaling matrices: not handled
                bp += 1
            l4, bp = _read_ue(r, bp)
            poc_type, bp = _read_ue(r, bp)
            self.fn_bits = l4 + 4
            # with POC type 2 the display order comes from frame_num alone – safe to renumber
            self.fn_ok = poc_type == 2
        except IndexError:
            self.fn_ok = False

    def _set_frame_num(self, tok, fn):
        """Rewrite the frame_num field of one slice NAL (tok includes the start code)."""
        cut = 20
        while cut < len(tok) and (tok[cut - 1] == 0 or tok[cut - 2] == 0):
            cut += 1                                               # don't split an escape sequence
        head = self._unescape(tok[4:cut])
        _, bp = _read_ue(head, 0)                                  # first_mb_in_slice
        _, bp = _read_ue(head, bp)                                 # slice_type
        _, bp = _read_ue(head, bp)                                 # pps id
        L = self.fn_bits
        if (bp + L) > len(head) * 8:
            return tok
        for i in range(L):
            bit = (fn >> (L - 1 - i)) & 1
            byte, sh = (bp + i) >> 3, 7 - ((bp + i) & 7)
            head[byte] = (head[byte] & ~(1 << sh) & 0xFF) | (bit << sh)
        new = self._escape(head)
        rest = tok[cut:]
        if len(new) >= 2 and new[-1] == 0 and new[-2] == 0 and rest and rest[0] <= 3:
            new.append(3)
        return bytes(tok[:4]) + bytes(new) + rest

    def renumber(self, chunk):
        """Renumber the pictures in one emitted chunk of Annex-B stream."""
        if b"\x00\x00\x01" not in chunk:
            return chunk
        parts = chunk.split(b"\x00\x00\x01")
        out, saw_pic, idr = [parts[0]], False, False
        for p in parts[1:]:
            tok = b"\x00\x00\x01" + p
            t = p[0] & 0x1F if p else 0
            if t == 7:
                self._parse_sps(tok)
            elif t in (1, 5) and self.fn_ok:
                if t == 5:
                    idr = True
                    self.fn_next = 0                               # a kept IDR really does restart at 0
                first_mb, _ = _read_ue(self._unescape(p[1:6]), 0)
                if first_mb == 0 and saw_pic is False:
                    saw_pic = True
                tok = self._set_frame_num(tok, self.fn_next)
                self.renumbered += 1
            out.append(tok[3:])
        if saw_pic and self.fn_ok:
            self.fn_next = (self.fn_next + 1) % (1 << self.fn_bits)
        return b"\x00\x00\x01".join(out)


class Unit:
    __slots__ = ("head", "pic", "ptype")

    def __init__(self, head, pic, ptype):
        self.head = head    # list[bytes]  headers before the picture
        self.pic = pic      # list[bytes]  picture header + slices/data
        self.ptype = ptype

    def data(self):
        return b"".join(self.head) + b"".join(self.pic)


class Tokenizer:
    """Incremental: feed() raw bytes, get complete picture units back."""

    def __init__(self, codec: Codec):
        self.codec = codec
        self.buf = bytearray()
        self.head, self.pic = [], []
        self.ptype = None
        self.preamble = b""  # anything before the first start code

    def _push_token(self, tok, out):
        code = tok[3]
        cd = self.codec
        if self.pic and cd.starts_unit(code):
            out.append(Unit(self.head, self.pic, self.ptype))
            self.head, self.pic, self.ptype = [], [], None
        if cd.is_picture(code):
            self.ptype = cd.picture_type(tok)
            self.pic.append(tok)
        elif self.pic:
            self.pic.append(tok)
        else:
            self.head.append(tok)

    def feed(self, data):
        out = []
        self.buf += data
        b = self.buf
        start = b.find(SC)
        if start < 0:
            return out
        if start > 0 and not (self.head or self.pic):
            self.preamble += bytes(b[:start])
        pos = start
        while True:
            nxt = b.find(SC, pos + 3)
            if nxt < 0:
                break
            self._push_token(bytes(b[pos:nxt]), out)
            pos = nxt
        del b[:pos]
        return out

    def flush(self):
        out = []
        if len(self.buf) >= 4 and self.buf[:3] == SC:
            self._push_token(bytes(self.buf), out)
        self.buf = bytearray()
        if self.pic:
            out.append(Unit(self.head, self.pic, self.ptype))
        elif self.head:
            out.append(Unit(self.head, [], None))
        self.head, self.pic = [], []
        return out


# ────────────────────────────────────────────────────────────────────────────
#  mosh engine
# ────────────────────────────────────────────────────────────────────────────

class Mosher:
    """
    Stateful, frame-by-frame corruption of a compressed picture stream.

    I-frame removal  – after the first keyframe, keyframes are replaced by the
                       previous P-frame. The decoder keeps painting new motion
                       onto stale pixels (the Murata / "Monster Movie" melt).
    P-frame bloom    – one P-frame is repeated for N frames; its motion vectors
                       are re-applied again and again until the image swells.
    databending      – random bytes inside picture data are overwritten
                       (never with 00/01, so no fake start codes appear).
    """

    def __init__(self, codec: Codec, fps: float, args, rng):
        self.codec = codec
        self.fps = fps
        self.a = args
        self.rng = rng
        self.n = 0
        self.seen_i = False
        self.last_kept_i = -10**9
        self.last_p = None
        self.bloom_left = 0
        self.bloom_pic = None
        self.next_bloom_at = self._schedule_bloom(0)
        self.stats = dict(frames=0, i_kept=0, i_dropped=0, blooms=0,
                          bloom_frames=0, bent_frames=0, bent_bytes=0, out_frames=0)
        self.looper = None
        self.slice_bleed = 0.0
        if isinstance(codec, MPEG2) and getattr(args, "bleed", None):
            self.slice_bleed = min(0.95, 0.08 + 0.6 * max(0.0, args.bleed_amount))
        self.strip = []  # recent glyphs for the terminal readout
        self.plain = []  # same, without colour codes (for the UI)
        self.timeline = [] if getattr(args, "audio_fx", None) else None
        self._ema = None

    # -- scheduling -------------------------------------------------------
    def _schedule_bloom(self, now):
        every = self.a.bloom_every
        if every <= 0:
            return None
        jitter = self.rng.uniform(0.5, 1.5)
        return now + max(1, int(every * self.fps * jitter))

    # what each strip glyph means for the sound (see AudioFX)
    EV_NORMAL, EV_KEPT, EV_DROPPED, EV_BLOOM, EV_BLOOM_START, EV_PARTIAL = range(6)
    GLYPH_EVENT = {"█": 1, "▓": 2, "∞": 3, "✺": 4, "▒": 5, "░": 0, "·": 0}

    def _record(self, kind):
        """One entry per output frame: (event, frames since a real keyframe, motion 0-1, bleed 0-1)."""
        tl = getattr(self, "timeline", None)
        if tl is not None:
            rec = (kind, max(0, self.n - self.last_kept_i), getattr(self, "_m", 0.0), getattr(self, "_b", 0.0))
            pos = getattr(self, "_pos", None)
            tl.append(rec if pos is None else rec + (pos,))

    def display_timeline(self):
        """The event log in display order. MPEG-2 stores pictures out of order (B-frames),
        so entries carry a display position and are sorted by it; other engines already
        record in display order."""
        tl = self.timeline or []
        if tl and len(tl[0]) == 5:
            return [r[:4] for r in sorted(tl, key=lambda r: r[4])]
        return tl

    def _glyph(self, color, ch):
        if ch != "╳":                           # ╳ = frame deleted outright: no output frame
            self._record(self.GLYPH_EVENT.get(ch, 0))
        self.strip.append(c(color, ch))
        self.plain.append(ch)
        if len(self.strip) > 64:
            del self.strip[:-64]
        if len(self.plain) > 400:
            del self.plain[:-400]

    # -- corruption primitives -------------------------------------------
    def _bend(self, pic):
        a = self.a
        if a.bend <= 0 or self.rng.random() >= a.bend:
            return pic, 0
        out, hits = [], 0
        for tok in pic:
            rngs = self.codec.bend_ranges(tok)
            if not rngs:
                out.append(tok)
                continue
            lo, hi = rngs
            span = hi - lo
            k = max(1, int(span * a.bend_amount / 1000.0))
            k = min(k, a.bend_max)
            if self.rng.random() > a.bend_tokens:
                out.append(tok)
                continue
            t = bytearray(tok)
            for _ in range(k):
                p = self.rng.randrange(lo, hi)
                t[p] = self.rng.randrange(2, 256)
            hits += k
            out.append(bytes(t))
        return out, hits

    def _fix(self, head):
        return [self.codec.fix_headers(t) for t in head]

    # -- main -------------------------------------------------------------
    def process(self, u: Unit):
        """Return list[bytes] to emit for this incoming unit."""
        a, S = self.a, self.stats
        if u.ptype is None:  # trailing headers / end codes
            return [u.data()]

        self.n += 1
        S["frames"] += 1
        emit = []
        # display position (MPEG-2 only): GOP start + temporal_reference, so the sound's
        # event log can be put back into display order afterwards
        if self.timeline is not None and isinstance(self.codec, MPEG2) and u.pic:
            if any(t[3] == 0xB8 for t in u.head):
                self._gop_base = getattr(self, "_coded", 0)
            tr = (u.pic[0][4] << 2) | (u.pic[0][5] >> 6)
            self._pos = getattr(self, "_gop_base", 0) + tr
            self._coded = getattr(self, "_coded", 0) + 1
        # motion proxy for the sound: how big this picture is compared to recent delta frames
        size = sum(len(t) for t in u.pic)
        if u.ptype == "P" or self._ema is None:
            self._ema = size if self._ema is None else self._ema + (size - self._ema) * 0.02
            self._m = min(1.0, size / (3.0 * self._ema + 1.0))
        self._b = 0.0

        # ongoing bloom swallows incoming frames (keeps duration / audio sync)
        if self.bloom_left > 0:
            self.bloom_left -= 1
            S["bloom_frames"] += 1
            S["out_frames"] += 1
            self._glyph(MAG, "∞")
            if u.ptype == "I":
                S["i_dropped"] += 1
            # keep stream headers (sequence/GOP) so the decoder stays in sync
            return [b"".join(self._fix(u.head)) + self.bloom_pic]

        pic = u.pic
        head = u.head

        if u.ptype == "I":
            refresh = a.refresh > 0 and (self.n - self.last_kept_i) >= a.refresh * self.fps
            fresh = self.looper is not None and a.loop_fresh and self.looper.fresh_keyframe(self.n)
            keep = (not self.seen_i) or refresh or fresh or (self.rng.random() >= a.drop_i)
            if keep:
                self.seen_i = True
                self.last_kept_i = self.n
                S["i_kept"] += 1
                pic, hits = self._bend(pic) if a.bend_i else (pic, 0)
                if hits:
                    S["bent_frames"] += 1
                    S["bent_bytes"] += hits
                self._glyph(GRN, "█")
                S["out_frames"] += 1
                return [b"".join(head) + b"".join(pic)]
            # ── dropped keyframe ──
            S["i_dropped"] += 1
            if self.slice_bleed > 0 and self.last_p is not None:
                # keep only some of the keyframe's slices: bands of the true picture land in
                # the mosh, and the decoder conceals the missing rows from the smeared image
                keep = []
                slices = [t for t in pic if 0x01 <= t[3] <= 0xAF]
                chosen = {id(t) for t in slices if self.rng.random() < self.slice_bleed}
                if slices and not chosen:
                    chosen.add(id(self.rng.choice(slices)))
                for t in pic:
                    if not (0x01 <= t[3] <= 0xAF) or id(t) in chosen:
                        keep.append(t)
                self._b = self.slice_bleed
                self._glyph(CYN, "▒")
                S["out_frames"] += 1
                S.setdefault("i_partial", 0)
                S["i_partial"] += 1
                return [b"".join(self._fix(head)) + b"".join(keep)]
            if a.i_mode == "drop" or self.last_p is None:
                self._glyph(RED, "╳")
                if self.last_p is None:
                    S["out_frames"] += 1
                    return [b"".join(head) + b"".join(pic)]
                return [b"".join(self._fix(head))] if head else []
            # 'hold': substitute the previous P-frame → motion re-applied
            self._glyph(RED, "▓")
            S["out_frames"] += 1
            return [b"".join(self._fix(head)) + self.last_p]

        # P / B / S frames
        if (self.looper is not None and self.looper.is_restart(self.n) and self.last_p is not None
                and self.rng.random() < a.drop_i):
            # a loop restart: this frame snaps the picture back to the loop's first frame.
            # swallow it, so the next repetition's motion lands on the end of the last one
            S["i_dropped"] += 1
            S["out_frames"] += 1
            self._glyph(RED, "▓")
            return [b"".join(self._fix(head)) + self.last_p]
        pic, hits = self._bend(pic)
        if hits:
            S["bent_frames"] += 1
            S["bent_bytes"] += hits
        body = b"".join(pic)

        if u.ptype == "P":
            self.last_p = body
            if self.next_bloom_at is not None and self.n >= self.next_bloom_at and self.seen_i:
                length = max(1, int(self.rng.uniform(0.6, 1.4) * a.bloom_len))
                S["blooms"] += 1
                self.next_bloom_at = self._schedule_bloom(self.n + length)
                if a.bloom_mode == "insert":
                    S["bloom_frames"] += length
                    S["out_frames"] += length + 1
                    self._glyph(MAG, "✺")
                    for _ in range(length):
                        self._record(self.EV_BLOOM)
                    return [b"".join(head) + body] + [body] * length
                self.bloom_left = length
                self.bloom_pic = body
                self._glyph(MAG, "✺")
                S["out_frames"] += 1
                return [b"".join(head) + body]

        self._glyph(YEL, "░") if hits else self._glyph(DIM, "·")
        S["out_frames"] += 1
        return [b"".join(head) + body]


# ────────────────────────────────────────────────────────────────────────────
#  motion hacks (shared vocabulary with mv_hack.js)
# ────────────────────────────────────────────────────────────────────────────

MV_MODES = ["exaggerate", "invert", "sink", "rise", "drift", "zoom-in", "zoom-out", "swirl",
            "mirror", "transpose", "echo", "average", "freeze", "jitter"]


BLEED_MODES = ["motion", "edges", "bright", "blocks", "slices", "uniform"]


def parse_bleed(s):
    modes = [m.strip() for m in (s or "").split(",") if m.strip() and m.strip() != "none"]
    bad = [m for m in modes if m not in BLEED_MODES]
    if bad:
        die(f"unknown bleed mode(s): {', '.join(bad)}. choose from: {', '.join(BLEED_MODES)}")
    return modes


def parse_modes(s):
    modes = [m.strip() for m in (s or "").split(",") if m.strip() and m.strip() != "none"]
    bad = [m for m in modes if m not in MV_MODES]
    if bad:
        die(f"unknown motion mode(s): {', '.join(bad)}. choose from: {', '.join(MV_MODES)}")
    return modes


class FlowHack:
    """The same motion hacks as mv_hack.js, applied to a dense optical-flow
    field instead of codec motion vectors. Flow values are 'sample offsets'
    in pixels (where each pixel copies from in the previous picture) – the
    same meaning as a motion vector."""

    def __init__(self, modes, amount, delay, hold, every, w, h, px_scale, rng):
        import numpy as np
        self.np = np
        self.modes, self.A = modes, amount
        self.delay, self.hold, self.every = delay, hold, every
        self.px = px_scale                      # low-res pixels per output pixel
        self.rng = np.random.default_rng(rng.randrange(1 << 30))
        gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        self.dx, self.dy = gx - (w - 1) / 2, gy - (h - 1) / 2
        self.w, self.h = w, h
        self.history, self.ema, self.frozen, self.frozen_left, self.n = [], None, None, 0, 0

    def __call__(self, f):
        np, A = self.np, self.A
        self.n += 1
        clean = f.copy()
        self.history.append(clean)
        if len(self.history) > self.delay + 1:
            self.history.pop(0)
        for m in self.modes:
            if m == "exaggerate":
                f *= 1 + 4 * A
            elif m == "invert":
                f *= -1
            elif m in ("sink", "rise", "drift"):
                d = (0.5 + 5.5 * A) * self.px
                if m == "sink":
                    f[..., 1] -= d
                elif m == "rise":
                    f[..., 1] += d
                else:
                    f[..., 0] -= d
            elif m in ("zoom-in", "zoom-out"):
                k = 0.016 * A * (1 if m == "zoom-in" else -1)
                f[..., 0] -= self.dx * k
                f[..., 1] -= self.dy * k
            elif m == "swirl":
                k = 0.016 * A
                f[..., 0] += self.dy * k
                f[..., 1] -= self.dx * k
            elif m == "mirror":
                f[:] = f[:, ::-1]
                f[..., 0] *= -1
            elif m == "transpose":
                f[:] = f[..., ::-1]
            elif m == "echo":
                if len(self.history) > self.delay:
                    f[:] = self.history[0]
            elif m == "average":
                a = 1 / (2 + 30 * A)
                self.ema = f.copy() if self.ema is None else self.ema + (f - self.ema) * a
                f[:] = self.ema
            elif m == "freeze":
                if self.frozen_left <= 0 and self.n % self.every == 0:
                    self.frozen, self.frozen_left = f.copy(), self.hold
                if self.frozen_left > 0:
                    f[:] = self.frozen
                    self.frozen_left -= 1
            elif m == "jitter":
                import cv2
                small = self.rng.standard_normal((9, 16, 2)).astype(np.float32)
                f += cv2.resize(small, (self.w, self.h), interpolation=cv2.INTER_CUBIC) * (8 * A * self.px)
        return f


class FlowMosher:
    """
    Optical-flow datamosh. Instead of corrupting a codec, it measures the real
    pixel motion between consecutive source frames (DIS optical flow) and
    drags a never-refreshing 'canvas' along it – the same thing a decoder does
    with P-frames after a missing keyframe, but per pixel instead of per block.
    Scene cuts play the role of keyframes (drop / keep / refresh), and blooms
    repeat one flow field.
    """

    def __init__(self, w, h, fps, args, rng, modes):
        try:
            import numpy as np
            import cv2
        except ImportError:
            die("the flow engine needs numpy + OpenCV:\n"
                "    python3 -m pip install --user numpy opencv-python\n"
                "  (or click 'install flow engine' in the UI)")
        self.np, self.cv2 = np, cv2
        self.w, self.h, self.fps, self.a, self.rng = w, h, fps, args, rng
        fw = min(w, max(64, args.flow_res))
        fw -= fw % 2
        self.fw, self.fh = fw, max(2, int(round(h * fw / w)))
        self.up = w / fw
        self.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        self.gx, self.gy = gx, gy
        self.hack = FlowHack(modes, args.mv_amount, args.mv_delay, args.mv_hold,
                             max(1, int(args.mv_every * fps)), self.fw, self.fh, 1 / self.up, rng) if modes else None
        self.looper = None
        self.bleed = parse_bleed(args.bleed)
        self.brng = np.random.default_rng(rng.randrange(1 << 30))
        self.canvas = None
        self.prev_small = None
        self.prev_thumb = None
        self.n = 0
        self.last_kept_i = -10 ** 9
        self.bloom_left = 0
        self.bloom_flow = None
        self.next_bloom_at = self._schedule_bloom(0)
        self.stats = dict(frames=0, i_kept=0, i_dropped=0, blooms=0,
                          bloom_frames=0, bent_frames=0, bent_bytes=0, out_frames=0)
        self.strip, self.plain = [], []
        self.timeline = [] if args.audio_fx else None
        self._m = self._b = 0.0

    _schedule_bloom = Mosher._schedule_bloom
    _glyph = Mosher._glyph
    _record = Mosher._record
    GLYPH_EVENT = Mosher.GLYPH_EVENT

    def _bleed_mask(self, frame, gray, measured):
        """Where (0..1) the real frame shows through the mosh this frame."""
        np, cv2, A = self.np, self.cv2, self.a.bleed_amount
        w, h = self.w, self.h
        mask = None

        def add(m):
            nonlocal mask
            mask = m if mask is None else np.maximum(mask, m)

        for mode in self.bleed:
            if mode == "uniform":
                add(np.full((h, w), 0.15 * A, np.float32))
            elif mode == "motion" and measured is not None:
                mag = cv2.magnitude(measured[..., 0], measured[..., 1]) * self.up   # px/frame at output size
                thr = max(0.0008, 0.002 + 0.02 * (1 - A)) * h               # px/frame, relative to size
                m = np.clip((mag - thr) / (thr + 1e-3), 0, 1).astype(np.float32) * min(1.0, 0.35 + 0.65 * A)
                m = cv2.GaussianBlur(cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR), (0, 0), 3)
                add(m)
            elif mode == "edges":
                e = cv2.Canny(gray, 60 + 120 * (1 - A), 160 + 120 * (1 - A))
                k = max(1, int(round(h / 540)))
                e = cv2.dilate(e, np.ones((k + 1, k + 1), np.uint8))
                add(cv2.GaussianBlur(e.astype(np.float32) / 255.0, (0, 0), 0.8 * k) * min(1.0, 0.2 + 0.5 * A))
            elif mode == "bright":
                t = 255 * max(0.1, 1 - 0.7 * A)
                add(np.clip((gray.astype(np.float32) - t) / 30.0, 0, 1) * min(1.0, 0.3 + 0.5 * A))
            elif mode in ("blocks", "slices"):
                bs = max(8, int(round(16 * h / 480)))            # a DVD macroblock, scaled to output
                gh, gw = -(-h // bs), -(-w // bs)
                if mode == "blocks":
                    cells = (self.brng.random((gh, gw)) < 0.03 * A).astype(np.float32)
                else:
                    cells = np.repeat((self.brng.random((gh, 1)) < 0.05 * A).astype(np.float32), gw, axis=1)
                add(cv2.resize(cells, (gw * bs, gh * bs), interpolation=cv2.INTER_NEAREST)[:h, :w])
        return None if mask is None else np.clip(mask, 0, 1)

    def process(self, frame):
        np, cv2, a, S = self.np, self.cv2, self.a, self.stats
        self.n += 1
        S["frames"] += 1
        S["out_frames"] += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (self.fw, self.fh), interpolation=cv2.INTER_AREA)
        thumb = cv2.resize(gray, (32, 18), interpolation=cv2.INTER_AREA).astype(np.int16)

        if self.canvas is None:
            self.canvas = frame.astype(np.float32)
            self.last_kept_i = self.n
            S["i_kept"] += 1
            self._glyph(GRN, "█")
        else:
            cut = float(np.mean(np.abs(thumb - self.prev_thumb))) > a.cut_threshold
            refresh = a.refresh > 0 and (self.n - self.last_kept_i) >= a.refresh * self.fps
            fresh = (self.looper is not None and a.loop_fresh
                     and self.looper.fresh_keyframe(self.n, before=0, after=0))
            if self.looper is not None and self.looper.is_restart(self.n):
                cut = True                  # a loop starting over counts as a cut: don't follow the snap-back
            if refresh or fresh or (cut and self.rng.random() >= a.drop_i):
                self.canvas = frame.astype(np.float32)
                self.last_kept_i = self.n
                self.bloom_left = 0
                S["i_kept"] += 1
                self._glyph(GRN, "█")
            else:
                measured = None
                if cut:
                    S["i_dropped"] += 1
                    self._glyph(RED, "▓")
                    flow = None                     # motion across a cut is meaningless
                elif self.bloom_left > 0:
                    self.bloom_left -= 1
                    S["bloom_frames"] += 1
                    flow = self.bloom_flow.copy()
                    self._glyph(MAG, "∞")
                else:
                    # flow from the current frame back to the previous one:
                    # "where does each pixel of this frame come from"
                    flow = self.dis.calc(small, self.prev_small, None)
                    measured = flow.copy()      # hacks below modify flow in place
                    if self.next_bloom_at is not None and self.n >= self.next_bloom_at:
                        length = max(1, int(self.rng.uniform(0.6, 1.4) * a.bloom_len))
                        self.bloom_left, self.bloom_flow = length, flow.copy()
                        self.next_bloom_at = self._schedule_bloom(self.n + length)
                        S["blooms"] += 1
                        self._glyph(MAG, "✺")
                    else:
                        self._glyph(DIM, "·")
                if self.hack is not None:
                    flow = self.hack(flow if flow is not None else np.zeros((self.fh, self.fw, 2), np.float32))
                if flow is not None:
                    big = cv2.resize(flow, (self.w, self.h), interpolation=cv2.INTER_LINEAR) * self.up
                    interp = cv2.INTER_CUBIC if a.flow_interp == "cubic" else cv2.INTER_LINEAR
                    self.canvas = cv2.remap(self.canvas, self.gx + big[..., 0], self.gy + big[..., 1],
                                            interp, borderMode=cv2.BORDER_REPLICATE)
                if a.flow_leak > 0:
                    cv2.addWeighted(self.canvas, 1 - a.flow_leak, frame.astype(np.float32), a.flow_leak, 0,
                                    dst=self.canvas)
                if self.bleed:
                    if "motion" in self.bleed and measured is None:
                        measured = self.dis.calc(small, self.prev_small, None)
                    m = self._bleed_mask(frame, gray, measured)
                    if m is not None:
                        m3 = m[..., None]
                        self.canvas += (frame.astype(np.float32) - self.canvas) * m3
                        self._b = float(m.mean())
                if measured is not None:
                    mag = float(np.mean(cv2.magnitude(measured[..., 0], measured[..., 1]))) * self.up
                    self._m = min(1.0, mag / (0.012 * self.h))
        self.prev_small, self.prev_thumb = small, thumb
        if self.timeline:
            k, st, _, _ = self.timeline[-1]
            self.timeline[-1] = (k, st, self._m, self._b)   # motion/bleed are known only now
            self._b = 0.0
        return cv2.convertScaleAbs(self.canvas).tobytes()   # saturating float→uint8


# ────────────────────────────────────────────────────────────────────────────
#  audio glitch driven by the video mosh
# ────────────────────────────────────────────────────────────────────────────

AUDIO_FX_MODES = ["stutter", "freeze", "decay", "motion", "bleed"]


def parse_audio_fx(s):
    s = (s or "").strip()
    if s in ("", "none"):
        return []
    if s == "all":
        return list(AUDIO_FX_MODES)
    modes = [m.strip() for m in s.split(",") if m.strip()]
    bad = [m for m in modes if m not in AUDIO_FX_MODES]
    if bad:
        die(f"unknown audio effect(s): {', '.join(bad)}. choose from: {', '.join(AUDIO_FX_MODES)} (or all)")
    return modes


class AudioFX:
    """
    Corrupts the soundtrack frame by frame, following the event log the mosh
    engine wrote while it corrupted the picture:

      stutter  a removed keyframe / swallowed loop restart → the sound skips:
               the last few tens of ms repeat, like a skipping CD
      freeze   a bloom → the sound loops one grain for as long as the bloom lasts
      decay    frames since the last real keyframe → bit depth and sample rate
               drop and the sound dulls; a real keyframe snaps it back clean
      motion   motion in the picture → overdrive that tears the sound open
               (and with --mv echo, the sound echoes from the same delay)
      bleed    where the real picture bleeds through, the clean sound does too
    """
    AR = 48000

    def __init__(self, modes, amount, decay_s, fps, echo_frames=None):
        self.modes, self.A, self.decay_s, self.fps = set(modes), max(0.0, amount), max(0.5, decay_s), fps
        self.echo_frames = echo_frames if (echo_frames and "motion" in self.modes) else None
        self.counts = dict(stutters=0, freezes=0)

    def process(self, raw_in, raw_out, timeline):
        import numpy as np
        x = np.memmap(raw_in, dtype=np.int16, mode="r")
        x = x[: len(x) // 2 * 2].reshape(-1, 2)
        total = len(x)
        y = np.memmap(raw_out, dtype=np.int16, mode="w+", shape=x.shape) if total else None
        if not total:
            return
        A, spf, fps = self.A, self.AR / self.fps, self.fps
        full = self.decay_s * fps
        stut_len = int(self.AR * (0.03 + 0.12 * min(A, 1.5)))      # grain that repeats on a skip
        stut_reps = 2 + int(5 * min(A, 1.5))
        stut_grain, stut_left, stut_pos = None, 0, 0
        frz_grain, frz_pos = None, 0
        echo = int(round(self.echo_frames * spf)) if self.echo_frames else 0
        b = 0
        for i, (kind, stale, motion, bleed) in enumerate(timeline):
            a = int(round(i * spf))
            b = min(int(round((i + 1) * spf)), total)
            if a >= total:
                break
            src = x[a:b].astype(np.float32)
            seg = src.copy()
            n = len(seg)

            # 1 · stutter: a removed keyframe skips the sound back and repeats it
            if "stutter" in self.modes and kind == Mosher.EV_DROPPED and a > stut_len:
                stut_grain = x[a - stut_len:a].astype(np.float32)
                stut_left, stut_pos = stut_len * stut_reps, 0
                self.counts["stutters"] += 1
            if stut_left > 0 and stut_grain is not None:
                k = min(n, stut_left)
                idx = (stut_pos + np.arange(k)) % len(stut_grain)
                seg[:k] = stut_grain[idx]
                stut_pos, stut_left = stut_pos + k, stut_left - k

            # 2 · freeze: a bloom holds one grain of sound for as long as it lasts
            if "freeze" in self.modes and kind in (Mosher.EV_BLOOM_START, Mosher.EV_BLOOM):
                if kind == Mosher.EV_BLOOM_START or frz_grain is None:
                    g = max(64, int(self.AR * (0.02 + 0.08 * min(A, 1.5))))
                    frz_grain, frz_pos = x[a:min(total, a + g)].astype(np.float32), 0
                    self.counts["freezes"] += 1
                if len(frz_grain):
                    idx = (frz_pos + np.arange(n)) % len(frz_grain)
                    seg = frz_grain[idx]
                    frz_pos += n
            else:
                frz_grain = None

            # 3 · decay: the longer the picture goes without a real keyframe, the more the sound rots
            if "decay" in self.modes and kind != Mosher.EV_KEPT and stale > 0:
                d = min(1.0, stale / full) * min(A, 1.0)
                if d > 0.01:
                    hold = 1 + int(23 * d)                          # sample-rate reduction
                    if hold > 1:
                        seg = seg[(np.arange(n) // hold) * hold]
                    step = 2.0 ** (13 * d)                          # bit-depth reduction
                    seg = np.round(seg / step) * step
                    w = 1 + int(14 * d)                             # dull the top end
                    if w > 1 and n > w:
                        c_ = np.cumsum(np.vstack([np.zeros((1, 2), np.float32), seg]), axis=0)
                        sm = (c_[w:] - c_[:-w]) / w
                        seg = np.vstack([seg[:w - 1], sm])

            # 4 · motion: movement in the picture tears the sound open (+ echo with --mv echo)
            if "motion" in self.modes:
                drive = 1.0 + 12.0 * A * motion
                if drive > 1.01:
                    seg = np.tanh(seg / 32768.0 * drive) / np.tanh(drive) * 32768.0
                if echo and a - echo >= 0:
                    seg = 0.65 * seg + 0.5 * x[a - echo:b - echo].astype(np.float32)

            # 5 · bleed: clean sound comes back where the real picture does
            if "bleed" in self.modes and bleed > 0:
                mix = min(1.0, bleed * 2.0)
                seg = seg * (1 - mix) + src * mix

            y[a:b] = np.clip(seg, -32768, 32767).astype(np.int16)
        if b < total:
            y[b:] = x[b:]                    # anything past the video stays as it was
        y.flush()


# ────────────────────────────────────────────────────────────────────────────
#  looper: a frame-based randomized video looper in front of the mosh
# ────────────────────────────────────────────────────────────────────────────

class Looper:
    """
    Picks a random point in the source, grabs `loop_frames` frames (plus the
    matching audio), and plays them over and over for `loop_hold` seconds, then
    jumps to another random point, and so on. Its output replaces the straight
    read of the disc, so the mosh engines corrupt the repetition itself: every
    loop restart is a hard cut the mosh can swallow.
    """
    AR = 48000

    def __init__(self, inp, src_start, src_len, total, fps, w, h, pix_fmt, args, rng,
                 video_out, audio_out, clean_out, logf):
        import concurrent.futures
        self.inp, self.src_start, self.src_len = inp, src_start, max(0.0, src_len)
        self.total_frames = max(1, int(round(total * fps)))
        self.fps, self.w, self.h, self.pix_fmt = fps, w, h, pix_fmt
        self.a, self.rng, self.logf = args, rng, logf
        self.video_out, self.audio_out, self.clean_out = video_out, audio_out, clean_out
        self.frame_bytes = w * h * 3 if pix_fmt == "bgr24" else w * h * 3 // 2
        self.jumps = collections.deque()    # output frame numbers (1-based) where a new position starts
        self.restart_frames = collections.deque()   # output frame numbers where a loop starts over
        self.jump_now = False
        self.stop = False
        self.positions = 0
        self.restarts = 0
        self.position = None
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def request_jump(self):
        self.jump_now = True

    def _pick(self):
        span = self.a.loop_frames / self.fps
        hi = max(0.0, self.src_len - span - 0.5)
        return self.src_start + self.rng.uniform(0, hi)

    def _fetch(self, pos):
        n = self.a.loop_frames
        vf = f"scale={self.w}:{self.h}:flags=lanczos,setsar=1"
        v = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{pos:.3f}"] + self.inp +
                           ["-map", "0:v:0", "-frames:v", str(n), "-vf", vf, "-pix_fmt", self.pix_fmt,
                            "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=self.logf).stdout
        frames = [v[i:i + self.frame_bytes] for i in range(0, len(v) - self.frame_bytes + 1, self.frame_bytes)]
        src_frames = len(frames)
        sp = self.a.loop_speed
        if abs(sp - 1) > 0.001 and src_frames >= 2:
            frames = self._slow(frames, sp)
        audio = b""
        if self.audio_out is not None and frames:
            want = int(round(len(frames) * self.AR / self.fps)) * 4
            af = []
            if abs(sp - 1) > 0.001:
                if self.a.loop_slow_audio == "stretch":
                    # time-stretch, pitch kept: chain atempo (each step must be >= 0.5)
                    steps, left = [], sp
                    while left < 0.5:
                        steps.append("atempo=0.5")
                        left /= 0.5
                    steps.append(f"atempo={left:.4f}")
                    af = ["-af", ",".join(steps)]
                else:
                    # tape: play the samples slower, so the pitch drops with the speed
                    af = ["-af", f"asetrate={max(1000, int(round(self.AR * sp)))},aresample={self.AR}"]
            audio = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{pos:.3f}",
                                    "-t", f"{src_frames / self.fps + 0.05:.3f}"] + self.inp +
                                   ["-map", "0:a:0", "-ac", "2", "-ar", str(self.AR)] + af +
                                   ["-f", "s16le", "-"],
                                   stdout=subprocess.PIPE, stderr=self.logf).stdout[:want]
            audio += b"\0" * (want - len(audio))
        return pos, frames, audio

    # ── slow motion ─────────────────────────────────────────────────────────
    def _slow(self, frames, sp):
        n = len(frames)
        out_n = max(1, int(round(n / sp)))
        mode = self.a.loop_slow
        if mode == "repeat" or sp > 1:
            # (faster than normal: just skip frames)
            # hold each frame longer: stepped, like undercranked film
            return [frames[min(n - 1, int(k * sp))] for k in range(out_n)]
        if mode == "interpolate":
            try:
                return self._slow_flow(frames, sp, out_n)
            except ImportError:
                log(c(YEL, "⚠ smooth interpolation works best with numpy + OpenCV – using ffmpeg's (much slower)"))
                self.a.loop_slow = mode = "ffmpeg-mci"
        filt = ("minterpolate=fps={f}:mi_mode=blend" if mode == "blend" else
                "minterpolate=fps={f}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1").format(f=rate_str(self.fps))
        r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "rawvideo", "-pix_fmt", self.pix_fmt,
                            "-s", f"{self.w}x{self.h}", "-framerate", rate_str(self.fps), "-i", "-",
                            "-vf", f"setpts=PTS/{sp:.5f},{filt}", "-pix_fmt", self.pix_fmt,
                            "-f", "rawvideo", "-"], input=b"".join(frames),
                           stdout=subprocess.PIPE, stderr=self.logf).stdout
        out = [r[i:i + self.frame_bytes] for i in range(0, len(r) - self.frame_bytes + 1, self.frame_bytes)]
        return out or frames

    def _slow_flow(self, frames, sp, out_n):
        """Optical-flow in-betweens: for a point t between frames A and B, pull A forward and
        B backward along the measured motion and mix them. Fast, smooth, and it warps and
        tears where the motion is ambiguous – which suits the mosh."""
        import numpy as np
        import cv2
        w, h, yuv = self.w, self.h, self.pix_fmt != "bgr24"
        to_bgr = (lambda f: cv2.cvtColor(np.frombuffer(f, np.uint8).reshape(h * 3 // 2, w), cv2.COLOR_YUV2BGR_I420)) \
            if yuv else (lambda f: np.frombuffer(f, np.uint8).reshape(h, w, 3))
        from_bgr = (lambda im: cv2.cvtColor(im, cv2.COLOR_BGR2YUV_I420).tobytes()) if yuv else (lambda im: im.tobytes())
        imgs = [to_bgr(f) for f in frames]
        fw = min(w, 480)
        fw -= fw % 2
        fh = max(2, int(round(h * fw / w)))
        up = w / fw
        grays = [cv2.resize(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (fw, fh), interpolation=cv2.INTER_AREA) for im in imgs]
        dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        flows = {}
        out = []
        n = len(imgs)
        for k in range(out_n):
            s = k * sp
            i = int(s)
            t = s - i
            if i >= n - 1 or t < 1e-3:
                out.append(frames[min(i, n - 1)])
                continue
            if i not in flows:
                f = dis.calc(grays[i], grays[i + 1], None)          # A(x) ≈ B(x + F(x))
                flows[i] = cv2.resize(f, (w, h), interpolation=cv2.INTER_LINEAR) * up
                flows.pop(i - 2, None)
            F = flows[i]
            a = cv2.remap(imgs[i], gx - t * F[..., 0], gy - t * F[..., 1], cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)
            b = cv2.remap(imgs[i + 1], gx + (1 - t) * F[..., 0], gy + (1 - t) * F[..., 1], cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)
            out.append(from_bgr(cv2.addWeighted(a, 1 - t, b, t, 0)))
        return out

    def _run(self):
        out_n = 0
        nxt = self.pool.submit(self._fetch, self._pick())
        try:
            while out_n < self.total_frames and not self.stop:
                pos, frames, audio = nxt.result()
                nxt = self.pool.submit(self._fetch, self._pick())
                if len(frames) < 2:
                    continue                      # landed past the end / unreadable – try elsewhere
                self.positions += 1
                self.position = pos
                self.jumps.append(out_n + 1)
                self.jump_now = False
                n = len(frames)
                # audio boundaries per frame, so any number of frames stays in sync
                bounds = [int(round(i * self.AR / self.fps)) * 4 for i in range(n + 1)]
                hold = max(1, int(round(self.a.loop_hold * self.fps)))
                k = 0
                for _ in range(hold):
                    if out_n >= self.total_frames or self.stop or self.jump_now:
                        break
                    if k == 0 and _ > 0:
                        self.restarts += 1
                        self.restart_frames.append(out_n + 1)
                    self.video_out.write(frames[k])
                    if self.clean_out is not None:
                        self.clean_out.write(frames[k])
                    if self.audio_out is not None:
                        self.audio_out.write(audio[bounds[k]:bounds[k + 1]])
                    out_n += 1
                    k = (k + 1) % n
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            self.pool.shutdown(wait=False, cancel_futures=True)
            for f in (self.video_out, self.audio_out, self.clean_out):
                try:
                    if f is not None:
                        f.close()
                except OSError:
                    pass

    def fresh_keyframe(self, n, before=2, after=15):
        """A keyframe at output frame n should be kept if it's the first one just after
        a jump to a new position. Each jump grants this once."""
        j = self.jumps
        while j and j[0] < n - after:
            j.popleft()
        if j and -before <= n - j[0] <= after:
            j.popleft()
            return True
        return False

    def is_restart(self, n):
        """True if output frame n is where a loop starts over (jumping back to its first frame)."""
        r = self.restart_frames
        while r and r[0] < n:
            r.popleft()
        if r and r[0] == n:
            r.popleft()
            return True
        return False


# ────────────────────────────────────────────────────────────────────────────
#  FFglitch (motion-vector editing)
# ────────────────────────────────────────────────────────────────────────────

HERE = os.path.dirname(os.path.abspath(__file__))
FFGLITCH_VERSION = "0.10.2"
FFGLITCH_SHA256 = {
    # verified against the official download on 2026-09-27
    "ffglitch-0.10.2-macos-aarch64.zip": "25a5a7d51217919db5a093b211fd8a1e27845284efb0a6f616b8f371f6638eef",
}


def find_ffglitch(tool):
    cands = [os.path.join(HERE, "ffglitch", tool), os.path.join(HERE, "bin", tool)]
    cands += sorted(glob.glob(os.path.join(HERE, "ffglitch", "*", tool)))
    for p in cands:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return shutil.which(tool)


def install_ffglitch():
    import platform
    import urllib.request
    import zipfile
    sysname, mach = platform.system(), platform.machine().lower()
    base = "https://ffglitch.org/pub/bin"
    v = FFGLITCH_VERSION
    if sysname == "Darwin":
        url = (f"{base}/macos-aarch64/ffglitch-{v}-macos-aarch64.zip" if mach in ("arm64", "aarch64")
               else f"{base}/mac64/ffglitch-{v}-macos-x86_64.zip")
    elif sysname == "Linux" and mach in ("x86_64", "amd64"):
        url = f"{base}/linux64/ffglitch-{v}-linux-x86_64.zip"
    elif sysname == "Windows":
        url = f"{base}/win64/ffglitch-{v}-windows-x86_64.zip"
    else:
        die(f"no automatic FFglitch download for {sysname}/{mach} – get it from https://ffglitch.org/download/ "
            f"and put ffedit + ffgac in {os.path.join(HERE, 'ffglitch')}")
    dest = os.path.join(HERE, "ffglitch")
    os.makedirs(dest, exist_ok=True)
    import hashlib
    zname = os.path.basename(url)
    zpath = os.path.join(dest, zname)
    want = FFGLITCH_SHA256.get(zname)

    def sha(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                h.update(blk)
        return h.hexdigest()

    # a copy delivered in pieces (ffglitch/parts/<zip>.part0, .part1 …) is used first
    parts_dir = os.path.join(dest, "parts")
    parts = sorted(glob.glob(os.path.join(parts_dir, glob.escape(zname) + ".part*")))
    got = False
    if parts:
        with open(zpath, "wb") as out:
            for pth in parts:
                with open(pth, "rb") as f:
                    shutil.copyfileobj(f, out)
        got = (want is None) or sha(zpath) == want
        log(("using the local copy in " + parts_dir) if got else "local copy is incomplete – downloading instead")
    for attempt in range(3):
        if got:
            break
        log(f"downloading {url}" + (f"  (retry {attempt})" if attempt else ""))
        tmp = zpath + ".download"
        urllib.request.urlretrieve(url, tmp)
        os.replace(tmp, zpath)
        got = (want is None) or sha(zpath) == want
        if not got:
            log(c(YEL, "  checksum mismatch – the download was damaged"))
    if not got:
        die("couldn't get an intact FFglitch download – try again later")
    with zipfile.ZipFile(zpath) as z:
        # clear any half-finished earlier install before unpacking
        for d in {n.split("/")[0] for n in z.namelist() if "/" in n}:
            shutil.rmtree(os.path.join(dest, d), ignore_errors=True)
        z.extractall(dest)
    os.remove(zpath)
    shutil.rmtree(parts_dir, ignore_errors=True)
    for tool in ("ffedit", "ffgac", "fflive", "qjs"):
        for p in glob.glob(os.path.join(dest, "**", tool), recursive=True):
            os.chmod(p, 0o755)
    if sysname == "Darwin":
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", dest], stderr=subprocess.DEVNULL)
    ok = find_ffglitch("ffedit") and find_ffglitch("ffgac")
    log(c(GRN, f"✔ FFglitch {v} installed in {dest}") if ok else c(RED, "✖ install failed"))
    return bool(ok)


# ────────────────────────────────────────────────────────────────────────────
#  DVD discovery
# ────────────────────────────────────────────────────────────────────────────

VOB_RE = re.compile(r"VTS_(\d\d)_(\d)\.VOB$", re.I)


def find_video_ts_dirs():
    roots = ["/Volumes/*", "/media/*/*", "/media/*", "/run/media/*/*", "/mnt/*"]
    found = []
    for r in roots:
        for d in glob.glob(r):
            for name in ("VIDEO_TS", "video_ts"):
                p = os.path.join(d, name)
                if os.path.isdir(p) and p not in found:
                    found.append(p)
    return found


def resolve_video_ts(src):
    if os.path.isdir(src):
        for name in ("VIDEO_TS", "video_ts"):
            if os.path.isdir(os.path.join(src, name)):
                return os.path.join(src, name)
        if any(VOB_RE.search(f) for f in os.listdir(src)):
            return src
    return None


def list_titles(vts_dir):
    """Group VTS_NN_k.VOB (k>=1, k=0 is the menu) into title sets."""
    sets = {}
    for f in sorted(os.listdir(vts_dir)):
        m = VOB_RE.search(f)
        if not m or m.group(2) == "0":
            continue
        sets.setdefault(int(m.group(1)), []).append(os.path.join(vts_dir, f))
    titles = []
    for n, files in sorted(sets.items()):
        files.sort(key=lambda p: int(VOB_RE.search(p).group(2)))
        size = sum(os.path.getsize(p) for p in files)
        titles.append(dict(n=n, files=files, size=size))
    return titles


def check_scrambled(path, probe_bytes=4 << 20):
    """Look at PES headers: scrambling_control != 00 means CSS-encrypted."""
    try:
        with open(path, "rb") as f:
            data = f.read(probe_bytes)
    except OSError as e:
        return f"read error ({e.strerror}) - encrypted discs often refuse raw reads"
    scrambled = total = 0
    pos = 0
    while total < 200:
        i = data.find(b"\x00\x00\x01\xe0", pos)
        if i < 0 or i + 7 > len(data):
            break
        total += 1
        if data[i + 6] & 0x30:
            scrambled += 1
        pos = i + 4
    if total and scrambled / total > 0.2:
        return "CSS scrambling flags set on the video packets"
    return None


# ────────────────────────────────────────────────────────────────────────────
#  ffmpeg helpers
# ────────────────────────────────────────────────────────────────────────────

def need(tool):
    p = shutil.which(tool)
    if not p:
        die(f"'{tool}' not found. On macOS:  brew install ffmpeg")
    return p


def ffprobe(input_args):
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_streams", "-show_format"] + input_args
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
        return json.loads(out or "{}")
    except Exception:
        return {}


def parse_rate(s, default=30000 / 1001):
    try:
        n, d = s.split("/")
        v = float(n) / float(d)
        return v if 1 < v < 240 else default
    except Exception:
        return default


def rate_str(fps):
    for num, den in ((30000, 1001), (24000, 1001), (60000, 1001)):
        if abs(fps - num / den) < 0.01:
            return f"{num}/{den}"
    return f"{fps:.3f}"


# ────────────────────────────────────────────────────────────────────────────
#  presets
# ────────────────────────────────────────────────────────────────────────────

PRESETS = {
    # H.264 at 1080p: tiny blocks + deblocking = smooth, liquid melt
    "liquid": dict(engine="h264", drop_i=1.0, refresh=0, bloom_every=0, bend=0.0, scale="1080", smooth=1),
    # liquid + slow blooms
    "liquid-bloom": dict(engine="h264", drop_i=1.0, refresh=0, bloom_every=10, bloom_len=45,
                         bend=0.0, scale="1080", smooth=1),
    # optical flow: pixel-accurate melt, no blocks at all
    "flow":   dict(engine="flow", drop_i=1.0, refresh=0, bloom_every=0, bend=0.0, scale="1080"),
    # optical flow + a slow vortex + blooms
    "flow-swirl": dict(engine="flow", drop_i=1.0, refresh=0, bloom_every=12, bloom_len=40, bend=0.0,
                       scale="1080", mv="swirl", mv_amount=0.25),
    # flow melt where moving things and outlines of the real footage break through
    "flow-bleed": dict(engine="flow", drop_i=1.0, refresh=0, bloom_every=0, bend=0.0, scale="1080",
                       bleed="motion,edges", bleed_amount=0.5),
    # native MPEG-2 mosh where bands of each removed keyframe still get through
    "native-bleed": dict(engine="native", drop_i=1.0, refresh=0, bloom_every=0, bend=0.0,
                         bleed="slices", bleed_amount=0.4),
    # randomized frame looper under a liquid mosh: each position starts clean, then melts on repeat
    "looper": dict(engine="h264", drop_i=1.0, refresh=0, bloom_every=0, bend=0.0, scale="1080", smooth=1,
                   loop=True, loop_frames=30, loop_hold=4.0, loop_fresh=True),
    # ultra slow motion: 20 frames stretched ten times, drifting and tearing, under a liquid mosh
    "looper-slow": dict(engine="h264", drop_i=1.0, refresh=0, bloom_every=0, bend=0.0, scale="720", smooth=1,
                        loop=True, loop_frames=20, loop_hold=14.0, loop_fresh=True,
                        loop_speed=0.1, loop_slow="interpolate", loop_slow_audio="tape"),
    # the same with optical flow: every repetition drags the image further
    "looper-flow": dict(engine="flow", drop_i=1.0, refresh=0, bloom_every=0, bend=0.0, scale="1080",
                        loop=True, loop_frames=24, loop_hold=5.0, loop_fresh=True),
    # FFglitch motion-vector hacking on an Xvid re-encode: averaged, sinking motion
    "vector": dict(engine="xvid", drop_i=1.0, refresh=0, bloom_every=0, bend=0.0, scale="720",
                   mv="average,sink", mv_amount=0.4),
    # FFglitch on the disc's own MPEG-2: each moment is driven by the motion from 3 s earlier
    "echo":   dict(engine="native", drop_i=1.0, refresh=30, bloom_every=0, bend=0.0,
                   mv="echo", mv_amount=0.5),
    # pure keyframe removal: every cut melts into the next
    "melt":   dict(engine="xvid",   drop_i=1.0, refresh=0,  bloom_every=0,  bend=0.0),
    # melt + periodic blooms
    "bloom":  dict(engine="xvid",   drop_i=1.0, refresh=0,  bloom_every=8,  bloom_len=40, bend=0.0),
    # the disc's own MPEG-2 GOPs, keyframes removed, occasional image refresh
    "native": dict(engine="native", drop_i=1.0, refresh=45, bloom_every=0,  bend=0.0),
    # databending: byte rot in the slices, colour smear, block tearing
    "rot":    dict(engine="native", drop_i=0.85, refresh=0, bloom_every=20, bloom_len=20,
                   bend=0.35, bend_amount=0.6),
    # everything at once
    "total":  dict(engine="xvid",   drop_i=1.0, refresh=0,  bloom_every=4,  bloom_len=30,
                   bend=0.12, bend_amount=0.4),
}


# ────────────────────────────────────────────────────────────────────────────
#  the rip
# ────────────────────────────────────────────────────────────────────────────

class Preview:
    """Feeds ffplay through a bounded queue. If ffplay falls behind, units are
    dropped from the *preview only* – which glitches the preview further."""

    def __init__(self, in_fmt, fps, title, snapshot=None):
        self.q = queue.Queue(maxsize=240)
        self.dropped = 0
        if snapshot:
            # decode the mosh and keep overwriting one small JPEG (for the web UI)
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "quiet", "-nostdin", "-y",
                   "-err_detect", "ignore_err"] + in_fmt + [
                   "-framerate", rate_str(fps), "-i", "-",
                   "-vf", f"setpts=N/({fps:.6f}*TB),fps=6,scale=640:-2",
                   "-q:v", "5", "-update", "1", "-f", "image2", snapshot]
            self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
            self.t = threading.Thread(target=self._run, daemon=True)
            self.t.start()
            return
        cmd = ["ffplay", "-hide_banner", "-loglevel", "quiet", "-window_title", title] + in_fmt + [
               "-framerate", rate_str(fps),
               "-fflags", "nobuffer", "-err_detect", "ignore_err", "-i", "-",
               "-vf", f"setpts=N/({fps:.6f}*TB)"]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self):
        while True:
            b = self.q.get()
            if b is None:
                break
            try:
                self.p.stdin.write(b)
            except (BrokenPipeError, OSError):
                break
        try:
            self.p.stdin.close()
        except Exception:
            pass

    def put(self, b):
        try:
            self.q.put_nowait(b)
        except queue.Full:
            self.dropped += 1

    def close(self):
        self.put(None)


def build_parser():
    p = argparse.ArgumentParser(
        prog="malfunction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Rip a DVD and datamosh it while it is being read.",
        epilog="""presets:
  liquid        h264 @1080p, keyframes removed – smooth, flowing melt (default)
  liquid-bloom  liquid + slow blooms
  flow          optical flow – per-pixel melt, no blocks (needs numpy + OpenCV)
  flow-swirl    flow + a slow vortex (--mv swirl) + blooms
  flow-bleed    flow where moving things and outlines of the real footage break through
  vector        xvid + FFglitch motion vectors: averaged, sinking motion (needs FFglitch)
  echo          native + FFglitch: each moment moves with the motion from 3 s earlier
  native-bleed  native, with bands of each removed keyframe still getting through
  looper        h264 + randomized frame looper: 30-frame loops, 4 s per random position
  looper-flow   the looper on the flow engine
  looper-slow   the looper in ultra slow motion (×0.1, interpolated, tape-slowed sound)
  melt          xvid, every keyframe removed – cuts melt into each other
  bloom         xvid, melt + P-frame blooms every ~8s
  native        mpeg2, the disc's own GOPs with keyframes removed, refresh every 45s
  rot           mpeg2, databending: byte rot in slice data + blooms
  total         xvid, all of the above

  full guide: MANUAL.md

examples:
  malfunction --list
  malfunction --preset melt --preview
  malfunction --source /Volumes/MY_DISC --title 1 --preset rot --keep-clean
  malfunction --source some_video.mp4 --preset bloom --bloom-len 90
""")
    g = p.add_argument_group("source")
    g.add_argument("--source", help="disc volume, VIDEO_TS folder, .VOB, or any video file "
                                    "(default: first DVD found in /Volumes)")
    g.add_argument("--title", type=int, help="title set number (default: largest)")
    g.add_argument("--list", action="store_true", help="list discs/titles and exit")
    g.add_argument("--start", type=float, default=0, help="start at N seconds")
    g.add_argument("--duration", type=float, help="only rip N seconds")

    g = p.add_argument_group("output")
    g.add_argument("-o", "--out", default=".", help="output directory (each rip gets its own subfolder)")
    g.add_argument("--name", help="base filename")
    g.add_argument("--keep-clean", action="store_true", help="also save an untouched copy (.mkv)")
    g.add_argument("--no-raw", action="store_true", help="don't keep the raw moshed bitstream")
    g.add_argument("--audio", choices=["clean", "crushed", "none"], default="clean")
    g.add_argument("--audio-fx", help="corrupt the sound with the picture, comma-separated: "
                   + ", ".join(AUDIO_FX_MODES) + " (or all). needs numpy")
    g.add_argument("--audio-fx-amount", type=float, default=0.5, help="strength of the sound corruption (0-1.5)")
    g.add_argument("--audio-decay", type=float, default=8.0,
                   help="decay: seconds without a real keyframe until the sound is fully rotted (default 8)")
    g.add_argument("--crf", type=int, default=16, help="quality of the H.264 bake")
    g.add_argument("--grain", type=float, default=3.0,
                   help="fake film grain laid over the finished video, in %% of full brightness "
                        "(default 3 = subtle; 0 = off). Softens block edges and banding.")
    g.add_argument("--preview", action="store_true", help="live ffplay window of the mosh")
    g.add_argument("--snapshot", help="keep writing the latest moshed frame to this JPEG")
    g.add_argument("--ui", action="store_true", help="JSON-lines progress on stdout (for malfunction_ui)")

    g = p.add_argument_group("mosh")
    g.add_argument("--preset", choices=list(PRESETS), default="liquid")
    g.add_argument("--engine", choices=["native", "xvid", "h264", "flow"],
                   help="native = corrupt the disc's MPEG-2; xvid = re-encode to MPEG-4 ASP first; "
                        "h264 = re-encode to H.264 (smallest blocks, smoothest melt); "
                        "flow = optical-flow mosh (per-pixel, no blocks; needs numpy + opencv)")
    g.add_argument("--drop-i", type=float, help="probability a keyframe is removed (0-1)")
    g.add_argument("--i-mode", choices=["hold", "drop"], default="hold",
                   help="hold = replace keyframe with previous P-frame; drop = delete it")
    g.add_argument("--refresh", type=float, help="let one keyframe through every N seconds (0=never)")
    g.add_argument("--bloom-every", type=float, help="seconds between blooms (0=off)")
    g.add_argument("--bloom-len", type=int, help="frames per bloom")
    g.add_argument("--bloom-mode", choices=["replace", "insert"], default="replace",
                   help="replace keeps duration/audio sync; insert stretches time")
    g.add_argument("--bend", type=float, help="probability a frame gets databent (0-1)")
    g.add_argument("--bend-amount", type=float, help="bytes corrupted per 1000 bytes of picture data")
    g.add_argument("--bend-max", type=int, default=64, help="max bytes per token")
    g.add_argument("--bend-tokens", type=float, default=0.5,
                   help="fraction of slices/VOPs touched in a bent frame")
    g.add_argument("--bend-i", action="store_true", help="also databend kept keyframes")
    g.add_argument("--gop", type=int, default=600,
                   help="xvid engine: max frames between keyframes (scene cuts still get one)")
    g.add_argument("--q", type=int, default=3, help="xvid engine: quantizer 2-31 (higher = blockier)")
    g.add_argument("--scale", default=None,
                   help="working/output height: source, 720, 1080, 1440, 2160. Re-encoding engines mosh "
                        "at this size, so blocks get smaller relative to the image (default 1080; "
                        "native engine can only upscale the result)")
    g.add_argument("--smooth", type=int, choices=[0, 1, 2, 3], default=None,
                   help="post-smoothing of block edges in the bake: 0 off, 1 light, 2 medium, 3 heavy")
    g = p.add_argument_group("motion hacking")
    g.add_argument("--mv", help="motion hacks, comma-separated: " + ", ".join(MV_MODES) +
                   ". native/xvid engines rewrite the codec's motion vectors with FFglitch; "
                   "the flow engine applies them to the optical-flow field")
    g.add_argument("--mv-amount", type=float, help="strength of the motion hacks (0-1, can go higher)")
    g.add_argument("--mv-delay", type=int, default=90, help="echo: use motion from N frames ago")
    g.add_argument("--mv-hold", type=int, default=45, help="freeze: hold motion for N frames")
    g.add_argument("--mv-every", type=float, default=5, help="freeze: capture new motion every N seconds")
    g.add_argument("--mv-script", help="custom FFglitch script (.js/.py) instead of the built-in hacks")
    g.add_argument("--install-ffglitch", action="store_true",
                   help=f"download FFglitch {FFGLITCH_VERSION} (ffedit/ffgac) next to malfunction and exit")

    g = p.add_argument_group("bleed – let the real frame back into the mosh")
    g.add_argument("--bleed", help="where the real footage shows through, comma-separated: " + ", ".join(BLEED_MODES) +
                   ". flow engine: all modes. native engine: any mode keeps some slices of each removed keyframe")
    g.add_argument("--bleed-amount", type=float, help="how much comes through (0-2; above 1 = strong)")

    g = p.add_argument_group("looper – randomized frame loops under the mosh")
    g.add_argument("--loop", dest="loop", action="store_const", const=True, default=None,
                   help="loop LOOP_FRAMES frames from a random point for LOOP_HOLD seconds, then jump "
                        "to another random point; the mosh runs on top of the repetition")
    g.add_argument("--no-loop", dest="loop", action="store_const", const=False)
    g.add_argument("--loop-frames", type=int, help="frames per loop (default 30)")
    g.add_argument("--loop-hold", type=float, help="seconds to keep looping one position (default 4)")
    g.add_argument("--loop-fresh", dest="loop_fresh", action="store_const", const=True, default=None,
                   help="start each new position from a clean real frame; the mosh builds up over its "
                        "repetitions (default on)")
    g.add_argument("--no-loop-fresh", dest="loop_fresh", action="store_const", const=False)
    g.add_argument("--loop-speed", type=float,
                   help="playback speed of each loop: 1 = normal, 0.5 = half speed, 0.1 = ten times slower (default 1)")
    g.add_argument("--loop-slow", choices=["interpolate", "blend", "repeat"],
                   help="how slow motion is made: interpolate = invented in-between frames (smoothest; best with "
                        "numpy + OpenCV), blend = cross-dissolves, repeat = held frames, stepped (default interpolate)")
    g.add_argument("--loop-slow-audio", choices=["tape", "stretch"],
                   help="slowed sound: tape = pitch drops with the speed, stretch = pitch kept, grainy (default tape)")

    g = p.add_argument_group("flow engine")
    g.add_argument("--flow-leak", type=float, help="how much of the real frame bleeds into the mosh each frame (0-1)")
    g.add_argument("--flow-res", type=int, default=640, help="width at which optical flow is computed")
    g.add_argument("--flow-interp", choices=["linear", "cubic"], default="cubic",
                   help="resampling of the canvas; cubic stays sharper over long smears")
    g.add_argument("--cut-threshold", type=float, default=28,
                   help="flow engine: frame difference that counts as a scene cut (keyframe)")
    g.add_argument("--seed", type=int, help="random seed (same seed + disc = same mosh)")
    g.add_argument("--version", action="version", version=VERSION)
    return p


def apply_preset(args):
    pr = dict(PRESETS[args.preset])
    defaults = dict(engine="xvid", drop_i=1.0, refresh=0, bloom_every=0, bloom_len=30,
                    bend=0.0, bend_amount=0.5, scale="1080", smooth=0,
                    mv="", mv_amount=0.5, flow_leak=0.0, bleed="", bleed_amount=0.5,
                    loop=False, loop_frames=30, loop_hold=4.0, loop_fresh=True,
                    loop_speed=1.0, loop_slow="interpolate", loop_slow_audio="tape")
    defaults.update(pr)
    for k, v in defaults.items():
        if getattr(args, k, None) is None:
            setattr(args, k, v)


def select_source(args):
    """Return (input_args_for_ffmpeg, label, vob_for_check_or_None)."""
    src = args.source
    if not src:
        dirs = find_video_ts_dirs()
        if not dirs:
            die("no DVD found. insert a disc or pass --source /path/to/VIDEO_TS (or any video file)")
        src = dirs[0]
    vts = resolve_video_ts(src)
    if vts:
        titles = list_titles(vts)
        if not titles:
            die(f"no title VOBs in {vts}")
        if args.list:
            log(c(CYN, f"◉ {vts}"))
            for t in titles:
                log(f"   title {t['n']:02d}  {t['size'] / 1e9:6.2f} GB  {len(t['files'])} vob")
            sys.exit(0)
        t = next((t for t in titles if t["n"] == args.title), None) if args.title else \
            max(titles, key=lambda t: t["size"])
        if not t:
            die(f"title {args.title} not found")
        label = os.path.basename(os.path.dirname(os.path.abspath(vts))) or "DVD"
        inp = ["-i", "concat:" + "|".join(t["files"])]
        return inp, f"{label}_t{t['n']:02d}", t["files"][0]
    if os.path.isfile(src):
        if args.list:
            log(f"{src} is a file; nothing to list")
            sys.exit(0)
        base = os.path.splitext(os.path.basename(src))[0]
        return ["-i", src], base, src if src.upper().endswith(".VOB") else None
    die(f"can't read source: {src}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.install_ffglitch:
        sys.exit(0 if install_ffglitch() else 1)
    apply_preset(args)
    modes = parse_modes(args.mv)
    for t in ("ffmpeg", "ffprobe"):
        need(t)
    if args.preview:
        need("ffplay")
    rng = random.Random(args.seed)
    # a UI "stop" or a closed terminal ends the rip gracefully, like ctrl-c
    def _as_interrupt(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _as_interrupt)
    signal.signal(signal.SIGINT, _as_interrupt)
    # the UI's "jump" button sends SIGUSR1; catch it from the start so an early press can't
    # kill the rip – it only does something once the looper is running
    jump_target = []
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, lambda *_: jump_target and jump_target[0].request_jump())

    inp, label, vob = select_source(args)
    if vob:
        why = check_scrambled(vob)
        if why:
            die(f"this disc looks encrypted ({why}).\n"
                "  malfunction only reads unencrypted discs, home-burned DVDs, and VIDEO_TS folders.")

    seek = []
    if args.start:
        seek += ["-ss", str(args.start)]
    limit = ["-t", str(args.duration)] if args.duration else []

    info = ffprobe(inp)
    vstreams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    # audio and video don't always start at the same moment (DVDs are often a few hundred ms apart);
    # the picture is re-timed from its first frame, so the sound is lined up to that same moment
    try:
        _v0 = next(float(s_["start_time"]) for s_ in info.get("streams", []) if s_.get("codec_type") == "video")
        _a0 = next(float(s_["start_time"]) for s_ in info.get("streams", []) if s_.get("codec_type") == "audio")
        av_offset = _a0 - _v0                  # > 0: sound starts after the picture
    except (StopIteration, KeyError, TypeError, ValueError):
        av_offset = 0.0
    if not vstreams:
        die("no video stream found")
    vs = vstreams[0]
    fps = parse_rate(vs.get("avg_frame_rate") or vs.get("r_frame_rate") or "")
    if vs.get("codec_name") == "mpeg2video":
        # DVD MPEG-2 often reports field rate / soft telecine weirdly; trust r_frame_rate
        fps = parse_rate(vs.get("r_frame_rate", ""), fps)
    dar = vs.get("display_aspect_ratio")
    total = float(info.get("format", {}).get("duration") or 0) - args.start
    src_len = total
    if args.loop:
        # looper: --duration is the length of the *output*; loops are drawn from the whole source
        if src_len <= 0:
            die("the looper needs a source with a known duration")
        total = args.duration or src_len
    elif args.duration:
        total = min(total, args.duration) if total > 0 else args.duration

    engine = args.engine
    if engine == "native" and vs.get("codec_name") != "mpeg2video":
        log(c(YEL, f"⚠ source is {vs.get('codec_name')}, not MPEG-2 – switching to h264 engine"))
        engine = "h264"
    ffedit = ffgac = None
    if (modes or args.mv_script) and engine == "h264":
        log(c(YEL, "⚠ FFglitch can't edit H.264 motion vectors – using the xvid engine for --mv"))
        engine = "xvid"
    if (modes or args.mv_script) and engine in ("native", "xvid"):
        ffedit, ffgac = find_ffglitch("ffedit"), find_ffglitch("ffgac")
        if not ffedit or (engine == "xvid" and not ffgac):
            die("motion-vector hacking needs FFglitch. install it with:\n"
                "    ./malfunction.py --install-ffglitch\n"
                "  (or use --engine flow, which hacks optical flow instead and needs no FFglitch)")
    parse_bleed(args.bleed)
    if args.bleed and args.bleed != "none" and engine in ("xvid", "h264"):
        log(c(YEL, f"⚠ --bleed works on the flow and native engines only – ignored for {engine}"))
    codec = {"native": MPEG2(), "xvid": MPEG4(), "h264": H264(), "flow": None}[engine]

    # working size: fix anamorphic DVD pixels to square, then scale to target height
    src_h = int(vs.get("height") or 480)
    target_h = src_h if str(args.scale).lower() in ("source", "0", "none") else int(args.scale)
    target_h -= target_h % 2
    fit = (f"scale=trunc(dar*{target_h}/2)*2:{target_h}:flags=lanczos,setsar=1")
    if engine == "flow" or args.loop:
        # the flow engine and the looper handle raw pixels, so they need the exact frame size up front
        try:
            sw, sh = int(vs["width"]), int(vs["height"])
            num, den = (vs.get("sample_aspect_ratio") or "1:1").split(":")
            sar = (int(num) / int(den)) if int(num) and int(den) else 1.0
        except (KeyError, ValueError, ZeroDivisionError):
            sw, sh, sar = 720, 480, 1.0
        flow_w = int(sw * sar / sh * target_h / 2) * 2
        fit = f"scale={flow_w}:{target_h}:flags=lanczos,setsar=1"

    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = args.name or f"{label}_{args.preset}_{stamp}"
    # every rip gets its own folder: video, log, raw stream and clean copy together
    job_dir = os.path.join(args.out, base)
    os.makedirs(job_dir, exist_ok=True)
    P = lambda ext: os.path.join(job_dir, f"{base}{ext}")
    raw_path = P(f".moshed.{codec.ext}") if codec else None
    if engine == "flow":
        args.no_raw = True              # the flow engine has no compressed stream to keep
    vid_tmp = P(".video.tmp.mp4")
    aud_tmp = P(".audio.tmp.m4a")
    final = P(".mp4")
    logf = open(P(".log"), "w")

    # ── ffmpeg #1: read disc → compressed stream on stdout (+ clean copy, + audio)
    encoder = ffgac if (engine == "xvid" and ffgac and (modes or args.mv_script)) else "ffmpeg"
    rip_in = seek + limit + inp
    if args.loop:
        # the looper feeds raw frames; the engines encode those instead of reading the disc
        rip_in = ["-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{flow_w}x{target_h}",
                  "-framerate", rate_str(fps), "-i", "pipe:0"]
    rip = [encoder, "-hide_banner", "-nostdin", "-y", "-fflags", "+genpts+discardcorrupt"] + rip_in
    if engine == "flow":
        rip += ["-map", "0:v:0", "-vf", fit, "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"]
    elif engine == "xvid" and encoder != "ffmpeg":
        # FFglitch's encoder: forcemv writes a vector for every block (so every
        # block can be moved), nopimb forbids intra blocks in P-frames (so the
        # image never repairs itself), plain 16x16 vectors for ffedit.
        rip += ["-map", "0:v:0", "-vf", fit, "-vcodec", "mpeg4", "-q:v", str(args.q),
                "-mpv_flags", "+nopimb+forcemv", "-fcode", "6",
                "-bf", "0", "-g", str(args.gop), "-sc_threshold", "0", "-f", "rawvideo", "pipe:1"]
    elif engine == "native" and args.loop:
        # looped frames aren't the disc's bitstream any more: re-encode DVD-style MPEG-2
        # (15-frame GOPs; no B-frames so loop restarts line up with frame numbers), then mosh it
        rip += ["-map", "0:v:0", "-c:v", "mpeg2video", "-q:v", "3", "-g", "15", "-bf", "0",
                "-f", "mpeg2video", "pipe:1"]
    elif engine == "native":
        rip += ["-map", "0:v:0", "-c:v", "copy", "-f", "mpeg2video", "pipe:1"]
    elif engine == "xvid":
        # mv4 = 8x8 motion blocks, qpel = quarter-pixel motion: finer, smoother drift
        rip += ["-map", "0:v:0", "-vf", fit, "-c:v", "mpeg4", "-vtag", "xvid", "-q:v", str(args.q),
                "-bf", "0", "-g", str(args.gop), "-sc_threshold", "0",
                "-flags", "+mv4+qpel", "-mbd", "rd", "-trellis", "1",
                "-f", "m4v", "pipe:1"]
    else:
        # H.264: IDR only at scene cuts, no B-frames, one reference frame
        # (P-frames always predict from "whatever came before" – the mosh),
        # AUD NALs so the tokenizer can find frame boundaries.
        rip += ["-map", "0:v:0", "-vf", fit, "-c:v", "libx264", "-preset", "fast",
                "-crf", str(max(8, args.crf - 4)), "-pix_fmt", "yuv420p",
                "-x264-params", f"keyint={args.gop if args.gop > 600 else 'infinite'}:scenecut=40:"
                                "bframes=0:ref=1:weightp=0:aud=1:partitions=all:8x8dct=1",
                "-f", "h264", "pipe:1"]
    if args.keep_clean and not args.loop:
        rip += ["-map", "0:v:0", "-map", "0:a?", "-c", "copy", P(".clean.mkv")]
    use_audio = has_audio and args.audio != "none"
    audio_fx = parse_audio_fx(args.audio_fx) if use_audio else []
    if audio_fx:
        try:
            import numpy  # noqa: F401
        except ImportError:
            log(c(YEL, "⚠ --audio-fx needs numpy (python3 -m pip install --user numpy) – sound left as is"))
            audio_fx = []
    args.audio_fx = ",".join(audio_fx)          # the mosh engines only keep an event log when this is set
    aud_raw, aud_fx_raw = P(".audio.tmp.raw"), P(".audio.fx.tmp.raw")
    # with sound effects the soundtrack is kept uncompressed until the picture is done
    aud_out = (["-c:a", "pcm_s16le", "-ar", str(AudioFX.AR), "-ac", "2", "-f", "s16le", aud_raw] if audio_fx
               else ["-c:a", "aac", "-b:a", "192k", aud_tmp])
    if use_audio and not args.loop:
        chain = [f"aresample={AudioFX.AR}"]
        if av_offset > 0.001:
            chain.append(f"adelay={int(round(av_offset * 1000))}:all=1")          # pad the late sound
        elif av_offset < -0.001:
            chain.append(f"atrim=start_sample={int(round(-av_offset * AudioFX.AR))}")  # drop sound before the picture
        chain.append(f"asetpts=N/{AudioFX.AR}/TB")
        if args.audio == "crushed":
            chain.append("acrusher=bits=6:mix=0.8:samples=4:mode=log")
        rip += ["-map", "0:a:0", "-vn", "-af", ",".join(chain)] + aud_out

    # ── ffmpeg #2: decode the moshed stream → bake to H.264 (freezes the glitch
    #    so it looks the same in every player)
    bake_filters = [f"setpts=N/({fps:.6f}*TB)"]
    smooth = [None,
              "deblock=filter=weak:block=8",
              "deblock=filter=strong:block=8,deblock=filter=weak:block=4",
              "deblock=filter=strong:block=16,deblock=filter=strong:block=8,gblur=sigma=0.6"][args.smooth]
    if smooth:
        bake_filters.append(smooth)          # smooth at mosh resolution, before upscaling
    if engine == "native" and target_h != src_h and not args.loop:
        bake_filters.append(fit)
    if engine == "flow":
        in_fmt = ["-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{flow_w}x{target_h}"]
        bake_filters = [f for f in bake_filters if not f.startswith("deblock")]
    else:
        in_fmt = ["-f", codec.raw_format]
    if args.grain > 0:
        # luma-only, changes every frame (temporal), applied last so it is full-resolution grain
        strength = max(1, min(100, int(round(args.grain * 2.55))))
        bake_filters += ["format=yuv420p", f"noise=c0s={strength}:c0f=t"]
    bake = ["ffmpeg", "-hide_banner", "-nostdin", "-y",
            "-err_detect", "ignore_err"] + in_fmt + ["-framerate", rate_str(fps),
            "-i", "pipe:0",
            # re-stamp every frame: moshed streams carry lying timestamps
            # (a recycled P-frame still claims its old time) – ignore them all
            "-vf", ",".join(bake_filters), "-r", rate_str(fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", str(args.crf),
            "-pix_fmt", "yuv420p"]
    if engine == "native" and target_h == src_h and not args.loop and dar and dar not in ("0:1", "N/A"):
        bake += ["-aspect", dar]
    bake += ["-movflags", "+faststart", vid_tmp]

    log(c(MAG, glitch_text(BANNER, 0.06, rng)))
    log(c(CYN, f"  source   {' '.join(inp[1:])[:100]}"))
    log(c(CYN, f"  engine   {engine} ({codec.name if codec else 'optical flow'})   preset {args.preset}   {fps:.3f} fps"
               f"   seed {args.seed if args.seed is not None else '∅'}"))
    log(c(CYN, f"  size     {target_h}p   smooth {args.smooth}   grain {args.grain:g}%"))
    log(c(CYN, f"  mosh     drop_i={args.drop_i} refresh={args.refresh}s bloom_every={args.bloom_every}s "
               f"bloom_len={args.bloom_len} bend={args.bend}"))
    if modes or args.mv_script:
        via = "optical flow" if engine == "flow" else "FFglitch"
        log(c(CYN, f"  motion   {args.mv_script or ','.join(modes)}  amount {args.mv_amount}  via {via}"))
    if args.bleed and args.bleed != "none" and engine in ("flow", "native"):
        log(c(CYN, f"  bleed    {args.bleed if engine == 'flow' else 'slices of removed keyframes'}"
                   f"  amount {args.bleed_amount}"))
    if args.loop:
        if not 0.01 <= args.loop_speed <= 4:
            die("--loop-speed must be between 0.01 and 4")
        slow = (f"   speed ×{args.loop_speed:g} ({args.loop_slow if args.loop_speed < 1 else 'frames skipped'}, "
                f"audio {args.loop_slow_audio})" if abs(args.loop_speed - 1) > 0.001 else "")
        log(c(CYN, f"  looper   {args.loop_frames} frames × {args.loop_hold:g}s per position"
                   f"{', each position starts clean' if args.loop_fresh else ''}{slow}   output {total:.0f}s"))
    if audio_fx:
        log(c(CYN, f"  sound    {', '.join(audio_fx)}  amount {args.audio_fx_amount}"
                   + (f"  decay {args.audio_decay:g}s" if "decay" in audio_fx else "")))
    log(c(CYN, f"  out      {final}"))
    log()

    looper = None
    if args.loop:
        af = ["-af", "acrusher=bits=6:mix=0.8:samples=4:mode=log"] if args.audio == "crushed" else []
        p_aud = subprocess.Popen(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-f", "s16le", "-ar", str(Looper.AR),
                                  "-ac", "2", "-i", "pipe:0"] + af + aud_out,
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=logf) if use_audio else None
        p_clean = subprocess.Popen(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-f", "rawvideo",
                                    "-pix_fmt", "bgr24" if engine == "flow" else "yuv420p",
                                    "-s", f"{flow_w}x{target_h}", "-framerate", rate_str(fps), "-i", "pipe:0",
                                    "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                                    P(".clean.mkv")],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=logf) if args.keep_clean else None
    if args.loop and engine == "flow":
        # no encoder in between: the looper writes pixels straight into the flow engine
        rfd, wfd = os.pipe()
        p_rip = None
        src = os.fdopen(rfd, "rb", buffering=1 << 20)
        loop_video_out = os.fdopen(wfd, "wb", buffering=0)
    else:
        p_rip = subprocess.Popen(rip, stdout=subprocess.PIPE, stderr=logf,
                                 stdin=subprocess.PIPE if args.loop else None)
        src = p_rip.stdout
        loop_video_out = p_rip.stdin if args.loop else None
    if args.loop:
        looper = Looper(inp, args.start, src_len, total, fps, flow_w, target_h,
                        "bgr24" if engine == "flow" else "yuv420p", args, rng,
                        loop_video_out, p_aud.stdin if p_aud else None, p_clean.stdin if p_clean else None, logf)
        # a UI "jump" (or kill -USR1 <pid>) moves the looper to a new random position right away
        jump_target.append(looper)
    p_edit = None
    if ffedit and engine in ("native", "xvid"):
        script = args.mv_script or os.path.join(HERE, "mv_hack.js")
        sp = dict(modes=modes, amount=int(round(args.mv_amount * 100)), delay=args.mv_delay,
                  hold=args.mv_hold, every=max(1, int(args.mv_every * fps)),
                  seed=(args.seed if args.seed is not None else rng.randrange(1, 1 << 30)))
        edit = [ffedit, "-hide_banner", "-loglevel", "error", "-y", "-i", "pipe:", "-s", script]
        if not args.mv_script:
            edit += ["-sp", json.dumps(sp)]
        edit += ["-o", "pipe:"]
        p_edit = subprocess.Popen(edit, stdin=p_rip.stdout, stdout=subprocess.PIPE, stderr=logf)
        p_rip.stdout.close()            # ffedit owns the pipe now
        src = p_edit.stdout
    p_bake = subprocess.Popen(bake, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=logf)
    raw = None if args.no_raw else open(raw_path, "wb")
    prev = Preview(in_fmt, fps, f"malfunction · {label}") if args.preview else None
    snap = Preview(in_fmt, fps, "", snapshot=args.snapshot) if args.snapshot else None
    emit_json = lambda **kw: (print(json.dumps(kw), flush=True) if args.ui else None)
    emit_json(type="start", source=" ".join(inp[1:]), engine=engine, fps=fps, total=total,
              final=final, folder=job_dir, preset=args.preset, loop=bool(args.loop))

    if engine == "flow":
        mosh = FlowMosher(flow_w, target_h, fps, args, rng, modes)
        frame_bytes = flow_w * target_h * 3
        np = mosh.np
    else:
        tok = Tokenizer(codec)
        mosh = Mosher(codec, fps, args, rng)
    mosh.looper = looper
    renumber = isinstance(codec, H264)
    if looper:
        looper.start()
    t0 = time.time()
    last_draw = 0
    first = True

    def write(b):
        p_bake.stdin.write(b)
        if raw:
            raw.write(b)
        if prev:
            prev.put(b)
        if snap:
            snap.put(b)

    def draw(final_=False):
        S = mosh.stats
        secs = S["frames"] / fps
        el = time.time() - t0
        if args.ui:
            emit_json(type="progress", secs=secs, total=total, elapsed=el,
                      speed=(secs / el if el > 0 else 0), stats=S, strip="".join(mosh.plain[-200:]),
                      loops=(looper.positions if looper else None),
                      position=(looper.position if looper else None))
            return
        pct = f"{100 * secs / total:5.1f}%" if total > 0 else "  ?  "
        speed = secs / el if el > 0 else 0
        strip = "".join(mosh.strip[-48:])
        line = (f"\r{c(INV, ' RIP ')} {pct} {secs:7.1f}s  ×{speed:4.1f}  "
                f"{c(GRN, 'I')}{S['i_kept']:<4}{c(RED, '╳')}{S['i_dropped']:<5}"
                f"{c(MAG, '✺')}{S['blooms']:<4}{c(YEL, '░')}{S['bent_bytes']:<7} "
                + (f"{c(CYN, '⟳')}{looper.positions:<4}" if looper else "") + strip)
        sys.stderr.write(line + ("\n" if final_ else ""))
        sys.stderr.flush()

    try:
        while engine == "flow":
            buf = src.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            write(mosh.process(np.frombuffer(buf, np.uint8).reshape(target_h, flow_w, 3)))
            now = time.time()
            if now - last_draw > 0.2:
                draw()
                last_draw = now
        while engine != "flow":
            chunk = src.read(1 << 16)
            if not chunk:
                break
            units = tok.feed(chunk)
            if first and tok.preamble:
                write(tok.preamble)
            first = False
            for u in units:
                for b in mosh.process(u):
                    write(codec.renumber(b) if renumber else b)
            now = time.time()
            if now - last_draw > 0.2:
                draw()
                last_draw = now
        if engine != "flow":
            for u in tok.flush():
                for b in mosh.process(u):
                    write(codec.renumber(b) if renumber else b)
        draw(True)
    except KeyboardInterrupt:
        log(c(YEL, "\n⏹  interrupted – finishing what we have"))
        if looper:
            looper.stop = True
        if p_rip:
            p_rip.terminate()
        if p_edit:
            p_edit.terminate()
        # a second stop shouldn't kill the finishing steps
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    except BrokenPipeError:
        log(c(RED, "\n✖ bake encoder died – see log"))
    finally:
        try:
            p_bake.stdin.close()
        except Exception:
            pass
        if raw:
            raw.close()
        if prev:
            prev.close()
        if snap:
            snap.close()

    # close our end of the pipe first: a reader that stopped reading would
    # otherwise leave the disc ffmpeg blocked on write() forever
    try:
        src.close()
    except Exception:
        pass
    if looper:
        looper.stop = True
        looper.thread.join(timeout=15)
    for p in (p_rip, p_edit, p_bake) + ((p_aud, p_clean) if args.loop else ()):
        if p is None:
            continue
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()

    # ── corrupt the sound, following what happened to the picture
    if audio_fx and os.path.exists(aud_raw) and os.path.getsize(aud_raw) > 0 and mosh.timeline:
        echo_frames = args.mv_delay if "echo" in modes else None
        fx = AudioFX(audio_fx, args.audio_fx_amount, args.audio_decay, fps, echo_frames)
        try:
            fx.process(aud_raw, aud_fx_raw, mosh.display_timeline() if hasattr(mosh, "display_timeline") else mosh.timeline)
            subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-f", "s16le", "-ar", str(AudioFX.AR),
                            "-ac", "2", "-i", aud_fx_raw, "-c:a", "aac", "-b:a", "192k", aud_tmp],
                           stdout=subprocess.DEVNULL, stderr=logf, check=False)
            log(c(DIM, f"  sound: {fx.counts['stutters']} stutters, {fx.counts['freezes']} freezes"))
        except Exception as e:                     # never lose the render over the sound
            log(c(YEL, f"⚠ sound effects failed ({e}) – using the clean soundtrack"))
            subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-f", "s16le", "-ar", str(AudioFX.AR),
                            "-ac", "2", "-i", aud_raw, "-c:a", "aac", "-b:a", "192k", aud_tmp],
                           stdout=subprocess.DEVNULL, stderr=logf, check=False)
    elif audio_fx and os.path.exists(aud_raw) and os.path.getsize(aud_raw) > 0:
        subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-f", "s16le", "-ar", str(AudioFX.AR),
                        "-ac", "2", "-i", aud_raw, "-c:a", "aac", "-b:a", "192k", aud_tmp],
                       stdout=subprocess.DEVNULL, stderr=logf, check=False)
    for f in (aud_raw, aud_fx_raw):
        if os.path.exists(f):
            os.remove(f)

    # ── mux baked video + audio
    if os.path.exists(vid_tmp) and os.path.getsize(vid_tmp) > 0:
        if use_audio and os.path.exists(aud_tmp) and os.path.getsize(aud_tmp) > 0:
            # decoders sometimes swallow a few moshed frames; stretch the video's
            # timestamps (no re-encode) so it matches the audio length again
            scale = []
            try:
                got = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                                          "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", vid_tmp],
                                         capture_output=True, text=True).stdout.strip())
                want = mosh.stats["out_frames"]
                if got and want and got != want and args.bloom_mode == "replace":
                    scale = ["-itsscale", f"{want / got:.6f}"]
                    log(c(DIM, f"  resync: {want - got} frames lost in decoding – stretched video ×{want / got:.4f}"))
            except (ValueError, OSError):
                pass
            subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y"] + scale + ["-i", vid_tmp, "-i", aud_tmp,
                            "-map", "0:v", "-map", "1:a", "-c", "copy", "-movflags", "+faststart", final],
                           stdout=subprocess.DEVNULL, stderr=logf, check=False)
        else:
            os.replace(vid_tmp, final)
    for f in (vid_tmp, aud_tmp):
        if os.path.exists(f) and os.path.exists(final):
            os.remove(f)
    logf.close()

    S = mosh.stats
    emit_json(type="done", ok=os.path.exists(final), final=final, folder=job_dir,
              loops=(looper.positions if looper else None),
              raw=None if not raw else raw_path,
              clean=P(".clean.mkv") if args.keep_clean else None, log=P(".log"), stats=S)
    log()
    if os.path.exists(final):
        log(c(GRN, f"✔ {final}"))
    else:
        log(c(RED, f"✖ no output – check {P('.log')}"))
    if raw:
        log(c(DIM, f"  raw moshed stream: {raw_path}  (plays differently in every player – try VLC / mpv)"))
    if args.keep_clean:
        log(c(DIM, f"  clean copy: {P('.clean.mkv')}"))
    log(c(DIM, f"  frames {S['frames']}  keyframes kept {S['i_kept']} / removed {S['i_dropped']}  "
               f"blooms {S['blooms']} ({S['bloom_frames']} fr)  bent {S['bent_frames']} fr / {S['bent_bytes']} B"))
    if prev and prev.dropped:
        log(c(DIM, f"  preview skipped {prev.dropped} units (preview-only glitches)"))


if __name__ == "__main__":
    main()
