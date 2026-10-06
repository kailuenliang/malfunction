// malfunction · motion vector hacks for FFglitch (ffedit, feature "mv")
//
// ffedit -i in.m2v -s mv_hack.js -sp '{"modes":["sink","swirl"],"amount":50}' -o out.m2v
// (FFglitch's JSON parser takes integers only: amount is a percentage)
//
// Motion vectors say, for each 16x16 block, "copy your pixels from over there
// in the previous picture". Rewriting them makes pixels flow somewhere they
// were never meant to go. Units are half-pixels.
//
// modes (combinable, applied in order):
//   exaggerate  scale every vector up          invert     reverse all motion
//   sink / rise constant downward / upward pull drift      constant sideways pull
//   zoom-in / zoom-out   radial field          swirl      rotational field
//   mirror      left/right mirror of the field transpose  swap x and y
//   echo        use the motion from `delay` frames ago (motion from another shot)
//   average     temporal smoothing of motion (slow, syrupy drift)
//   freeze      every `every` frames, lock the current motion for `hold` frames
//   jitter      random per-block noise

let P = { modes: ["sink"], amount: 50, delay: 90, hold: 45, every: 150, seed: 1 };
let n = 0;
let history = [];
let emaX = null, emaY = null;
let frozen = null, frozenLeft = 0;
let rnd = null;

function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function setup(args) {
  args.features = ["mv"];
  if (args.params) Object.assign(P, args.params);
  rnd = mulberry32((P.seed | 0) || 1);
}

function each(f, fn) {
  for (let i = 0; i < f.length; i++) {
    const row = f[i];
    for (let j = 0; j < row.length; j++) {
      const mv = row[j];
      if (mv) fn(mv, i, j);
    }
  }
}

function copyFrom(f, src, map) {
  // map(i, j) -> [si, sj, sx, sy] : take src[si][sj], multiply components by sx, sy
  each(f, (mv, i, j) => {
    const m = map(i, j);
    const s = src[m[0]] && src[m[0]][m[1]];
    if (!s) return;
    mv[0] = s[0] * m[2];
    mv[1] = s[1] * m[3];
  });
}

export function glitch_frame(frame) {
  const f = frame.mv?.forward;
  if (!f) return;
  frame.mv.overflow = "truncate";
  n++;

  const A = P.amount / 100;
  const H = f.length;
  const W = H ? f[0].length : 0;
  const cy = (H - 1) / 2, cx = (W - 1) / 2;
  const clean = f.dup();
  history.push(clean);
  if (history.length > P.delay + 1) history.shift();

  for (const m of P.modes) {
    switch (m) {
      case "exaggerate": {
        const k = 1 + 4 * A;
        each(f, mv => { mv[0] = Math.round(mv[0] * k); mv[1] = Math.round(mv[1] * k); });
        break;
      }
      case "invert":
        each(f, mv => { mv[0] = -mv[0]; mv[1] = -mv[1]; });
        break;
      case "sink": case "rise": case "drift": {
        const d = Math.round(1 + 11 * A);
        if (m === "sink") each(f, mv => { mv[1] -= d; });
        if (m === "rise") each(f, mv => { mv[1] += d; });
        if (m === "drift") each(f, mv => { mv[0] -= d; });
        break;
      }
      case "zoom-in": case "zoom-out": {
        const k = 0.5 * A * (m === "zoom-in" ? 1 : -1);
        each(f, (mv, i, j) => { mv[0] += Math.round((cx - j) * k); mv[1] += Math.round((cy - i) * k); });
        break;
      }
      case "swirl": {
        const k = 0.5 * A;
        each(f, (mv, i, j) => { mv[0] += Math.round((i - cy) * k); mv[1] -= Math.round((j - cx) * k); });
        break;
      }
      case "mirror": {
        const src = f.dup();
        copyFrom(f, src, (i, j) => [i, W - 1 - j, -1, 1]);
        break;
      }
      case "transpose":
        each(f, mv => { const t = mv[0]; mv[0] = mv[1]; mv[1] = t; });
        break;
      case "echo":
        if (history.length > P.delay) copyFrom(f, history[0], (i, j) => [i, j, 1, 1]);
        break;
      case "average": {
        const a = 1 / (2 + 30 * A);
        if (!emaX || emaX.length !== H * W) { emaX = new Float32Array(H * W); emaY = new Float32Array(H * W); }
        each(f, (mv, i, j) => {
          const k = i * W + j;
          emaX[k] += (mv[0] - emaX[k]) * a;
          emaY[k] += (mv[1] - emaY[k]) * a;
          mv[0] = Math.round(emaX[k]);
          mv[1] = Math.round(emaY[k]);
        });
        break;
      }
      case "freeze":
        if (frozenLeft <= 0 && n % P.every === 0) { frozen = f.dup(); frozenLeft = P.hold; }
        if (frozenLeft > 0 && frozen) { copyFrom(f, frozen, (i, j) => [i, j, 1, 1]); frozenLeft--; }
        break;
      case "jitter": {
        const r = 16 * A;
        each(f, mv => { mv[0] += Math.round((rnd() - 0.5) * r); mv[1] += Math.round((rnd() - 0.5) * r); });
        break;
      }
    }
  }
}
