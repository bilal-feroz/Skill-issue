#!/usr/bin/env python3
"""SKILL ISSUE: fully procedural soundtrack generator.

Every sound in the film (music, foley, ambience, UI sounds) is synthesised here
from oscillators, noise and filters with numpy only: no samples, no downloads.
The single external source is Windows' built-in *offline* speech synthesiser
(System.Speech / SAPI 5), used for the two short voice lines.  Its raw output is
cached in audio/source/ so the mix can be rebuilt on a machine without it.

    python scripts/generate_audio.py                 # build audio/ (uses the TTS cache)
    python scripts/generate_audio.py --retts         # re-synthesise the two voice lines
    python scripts/generate_audio.py --overview x.png  # also draw a waveform/spectrogram

Timing comes from scripts/skill_issue/timeline.py (named beats, SFX sync points)
and scripts/skill_issue/speed.py (speed curve, beat grid, key presses, spawns),
so picture and sound stay in sync when the timeline changes.  Frame f starts at
(f-1)/24 s, i.e. sample (f-1)*2000 at 48 kHz.  Everything is seeded.
"""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import wave
import zlib

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
from skill_issue import timeline as T, speed as S  # noqa: E402

SR = 48_000
FPS = T.FPS
SPF = SR // FPS                                   # 2000 samples per frame
N = (T.FRAME_END - T.FRAME_START + 1) * SPF       # 1,440,000 samples = 30.000 s
assert N == 1_440_000
TAU = 2.0 * np.pi
E = T.E
AUDIO = os.path.join(REPO, "audio")
STEMS = os.path.join(AUDIO, "stems")
SOURCE = os.path.join(AUDIO, "source")
MASTER_SEED = 20241031
TARGET_LUFS = -15.0
CEILING_DB = -1.0
_T0 = time.time()


def log(msg):
    print(f"[{time.time() - _T0:6.1f}s] {msg}", flush=True)


def F(f):
    """Start time (s) of frame f (1-based, may be fractional)."""
    return (f - T.FRAME_START) / FPS


def db(x):
    return 10.0 ** (x / 20.0)


def mtof(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def rng_for(name):
    """Independent deterministic RNG per sound (crc32, not Python's salted hash)."""
    return np.random.default_rng([MASTER_SEED, zlib.crc32(name.encode("utf-8"))])


# =============================================================================
# 1. Shared timing model (speed.py)
# =============================================================================
SPD = S.compute()
CH = SPD["ch"]
EV = SPD["events"]
# beat_phase after frame k's increment is the phase at time k/24, so every beat
# event lands *inside* its event frame and the tempo glides continuously.
_PH = np.concatenate([[0.0], np.asarray(CH["beat_phase"], float)])
_TK = np.arange(len(_PH)) / FPS


def bt(x):
    """Beat position (float, beat n == the n-th `beats` event) -> seconds."""
    return float(np.interp(x, _PH, _TK))


def beat_at(t):
    """Seconds -> beat phase (inverse of bt)."""
    return float(np.interp(t, _TK, _PH))


def chan(name):
    """Per-sample version of a per-frame channel (value anchored at frame start)."""
    v = np.asarray(CH[name], float)
    return np.interp(np.arange(N) / SR, np.arange(len(v)) / FPS, v)


def chan_at(name, t):
    v = CH[name]
    return v[int(np.clip(int(t * FPS), 0, len(v) - 1))]


def key_times():
    """Every hero key press: the `keys` event (primary) plus any extra half-step
    crossings of typing_phase inside the same frame (ghost strokes), with the
    exact sub-frame crossing time."""
    tp = np.concatenate([[0.0], np.asarray(CH["typing_phase"], float)])
    out = []
    for e in EV["keys"]:
        f = e["frame"]
        p0, p1 = tp[f - 1], tp[f]
        for j, k in enumerate(range(int(p0 * 2) + 1, int(p1 * 2) + 1)):
            frac = (k / 2.0 - p0) / max(1e-9, p1 - p0)
            out.append(dict(frame=f, t=(f - 1 + frac) / FPS, primary=(j == 0), rate=e["rate"]))
    return out


# =============================================================================
# 2. DSP primitives
# =============================================================================
def tsec(n):
    return np.arange(n) / SR


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def fades(x, fin=0.001, fout=0.003):
    """Raised-cosine fade in/out so nothing ever starts or stops with a click."""
    y = np.array(x, dtype=float, copy=True)
    n = len(y)
    a, b = min(n // 2, int(fin * SR)), min(n // 2, int(fout * SR))
    if a > 1:
        r = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, a))
        y[:a] *= r if y.ndim == 1 else r[:, None]
    if b > 1:
        r = 0.5 + 0.5 * np.cos(np.linspace(0.0, np.pi, b))
        y[-b:] *= r if y.ndim == 1 else r[:, None]
    return y


def env_perc(n, attack=0.002, tau=0.2, hold=0.0):
    t = tsec(n)
    a = smoothstep(t / attack) if attack > 0 else np.ones(n)
    return a * np.exp(-np.maximum(t - attack - hold, 0.0) / tau)


def env_pts(n, pts):
    return np.interp(tsec(n), [p[0] for p in pts], [p[1] for p in pts])


def release_env(n, dur, rel):
    return 0.5 + 0.5 * np.cos(np.pi * np.clip((tsec(n) - dur) / rel, 0.0, 1.0))


def norm(x, peak=1.0):
    m = np.max(np.abs(x)) if len(x) else 0.0
    return x * (peak / m) if m > 0 else x


def white(n, rng):
    return rng.standard_normal(n)


def colored(n, rng, alpha=1.0, fmin=12.0):
    """1/f^alpha noise (alpha 1 = pink, 2 = brown), unit RMS, via FFT shaping."""
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1.0 / SR)
    X *= np.maximum(f, fmin) ** (-alpha / 2.0)
    X[0] = 0.0
    y = np.fft.irfft(X, n)
    return y / (np.sqrt(np.mean(y * y)) + 1e-12)


# --- biquads (RBJ cookbook) ---------------------------------------------------
def rbj(kind, f0, q=0.7071, gain_db=0.0):
    f0 = float(np.clip(f0, 5.0, 0.49 * SR))
    A = 10.0 ** (gain_db / 40.0)
    w0 = TAU * f0 / SR
    cw, sw = np.cos(w0), np.sin(w0)
    al = sw / (2.0 * q)
    if kind == "lp":
        b, a = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2], [1 + al, -2 * cw, 1 - al]
    elif kind == "hp":
        b, a = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2], [1 + al, -2 * cw, 1 - al]
    elif kind == "bp":
        b, a = [al, 0.0, -al], [1 + al, -2 * cw, 1 - al]
    elif kind == "notch":
        b, a = [1.0, -2 * cw, 1.0], [1 + al, -2 * cw, 1 - al]
    elif kind == "peak":
        b, a = [1 + al * A, -2 * cw, 1 - al * A], [1 + al / A, -2 * cw, 1 - al / A]
    elif kind in ("ls", "hs"):
        sq = 2.0 * np.sqrt(A) * al
        if kind == "ls":
            b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
            a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
        else:
            b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)]
            a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    else:
        raise ValueError(kind)
    a = np.asarray(a, float)
    return np.asarray(b, float) / a[0], a / a[0]


def _resp(b, a, nfft):
    z = np.exp(-1j * np.pi * np.arange(nfft // 2 + 1) / (nfft // 2))
    return np.polyval(np.asarray(b)[::-1], z) / np.polyval(np.asarray(a)[::-1], z)


def filt(x, *stages, pad=0.25):
    """Static IIR filtering.  Each stage is (kind, f0[, q[, gain_db]]) or
    ('ba', b, a).  The cascade's exact frequency response (magnitude *and*
    phase of the causal biquads) is applied in the FFT domain, with enough
    zero padding that the IIR tail does not wrap around."""
    x = np.asarray(x, float)
    n = len(x)
    if n == 0:
        return x
    nfft = 1 << int(np.ceil(np.log2(n + int(pad * SR))))
    H = np.ones(nfft // 2 + 1, complex)
    for st in stages:
        if st[0] == "ba":
            b, a = st[1], st[2]
        else:
            b, a = rbj(st[0], st[1], st[2] if len(st) > 2 else 0.7071, st[3] if len(st) > 3 else 0.0)
        H *= _resp(b, a, nfft)
    X = np.fft.rfft(x, nfft, axis=0)
    return np.fft.irfft(X * (H if x.ndim == 1 else H[:, None]), nfft, axis=0)[:n]


def svf(x, fc, q=0.7071, mode="lp"):
    """Time-varying TPT state-variable filter (Zavalishin/Simper), per-sample
    cutoff.  Used for filter sweeps: whooshes, formants, the opening filter."""
    x = np.asarray(x, float)
    if x.ndim == 2:
        return np.stack([svf(x[:, c], fc, q, mode) for c in range(x.shape[1])], 1)
    n = len(x)
    fcv = np.clip(np.broadcast_to(np.asarray(fc, float), (n,)), 5.0, 0.45 * SR)
    k = 1.0 / np.broadcast_to(np.asarray(q, float), (n,))
    g = np.tan(np.pi * fcv / SR)
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    xs, A1, A2, A3 = x.tolist(), a1.tolist(), a2.tolist(), a3.tolist()
    lp = [0.0] * n
    bp = [0.0] * n
    ic1 = ic2 = 0.0
    for i in range(n):
        v3 = xs[i] - ic2
        v1 = A1[i] * ic1 + A2[i] * v3
        v2 = ic2 + A2[i] * ic1 + A3[i] * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        lp[i] = v2
        bp[i] = v1
    lp = np.array(lp)
    bp = np.array(bp)
    if mode == "lp":
        return lp
    if mode == "bp":
        return bp * k                      # unity gain at the centre frequency
    if mode == "hp":
        return x - k * bp - lp
    raise ValueError(mode)


def fftconv(x, k):
    n = len(x) + len(k) - 1
    nfft = 1 << int(np.ceil(np.log2(n)))
    return np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(k, nfft), nfft)[:n]


def resample_len(x, n_out):
    """Band-limited FFT resampling of a whole (zero-edged) signal to n_out samples."""
    X = np.fft.rfft(x)
    m = n_out // 2 + 1
    Y = np.zeros(m, complex)
    k = min(len(X), m)
    Y[:k] = X[:k]
    return np.fft.irfft(Y, n_out) * (n_out / len(x))


def vdelay(x, d):
    """Variable fractional delay (samples, array) by linear interpolation: tape wow."""
    n = len(x)
    idx = np.arange(n) - d
    if x.ndim == 1:
        return np.interp(idx, np.arange(n), x, left=0.0, right=0.0)
    return np.stack([np.interp(idx, np.arange(n), x[:, c], left=0.0, right=0.0) for c in range(x.shape[1])], 1)


def comb_fb(x, D, g):
    """Feedback comb y[n] = x[n] + g*y[n-D], vectorised in blocks of D."""
    y = np.array(x, float, copy=True)
    for c0 in range(D, len(y), D):
        c1 = min(len(y), c0 + D)
        y[c0:c1] += g * y[c0 - D:c1 - D]
    return y


def allpass(x, D, g):
    """Schroeder allpass y[n] = -g x[n] + x[n-D] + g y[n-D], vectorised in blocks of D."""
    n = len(x)
    y = np.zeros(n)
    y[:min(D, n)] = -g * x[:min(D, n)]
    for c0 in range(D, n, D):
        c1 = min(n, c0 + D)
        y[c0:c1] = -g * x[c0:c1] + x[c0 - D:c1 - D] + g * y[c0 - D:c1 - D]
    return y


# --- oscillators ----------------------------------------------------------------
def phase(freq, n, ph0=0.0):
    f = np.broadcast_to(np.asarray(freq, float), (n,))
    return ph0 + np.concatenate([[0.0], np.cumsum(f[:-1])]) / SR


def osc_sin(freq, n, ph0=0.0):
    return np.sin(TAU * phase(freq, n, ph0))


def osc_saw(freq, n, ph0=0.0):
    """PolyBLEP band-limited sawtooth (vectorised)."""
    f = np.broadcast_to(np.asarray(freq, float), (n,))
    dt = np.minimum(np.abs(f) / SR, 0.5)
    p = phase(f, n, ph0) % 1.0
    y = 2.0 * p - 1.0
    m = p < dt
    tt = p[m] / dt[m]
    y[m] -= tt + tt - tt * tt - 1.0
    m = p > 1.0 - dt
    tt = (p[m] - 1.0) / dt[m]
    y[m] -= tt * tt + tt + tt + 1.0
    return y


def osc_pulse(freq, n, width=0.5, ph0=0.0):
    return 0.5 * (osc_saw(freq, n, ph0) - osc_saw(freq, n, ph0 + width))


def pan2(x, pan=0.0):
    """Equal-power pan for mono (pan may be an array); balance for stereo."""
    x = np.asarray(x, float)
    th = (np.asarray(pan, float) + 1.0) * np.pi / 4.0
    if x.ndim == 2:
        if np.ndim(pan) == 0 and pan == 0.0:
            return x
        gl = np.minimum(1.0, np.cos(th) * np.sqrt(2.0))
        gr = np.minimum(1.0, np.sin(th) * np.sqrt(2.0))
        return np.stack([x[:, 0] * gl, x[:, 1] * gr], 1)
    return np.stack([x * np.cos(th), x * np.sin(th)], 1)


# --- reverb: 16-line feedback delay network -----------------------------------
_REV_CAL = {}


def _fdn(x, t60, size, damp, predelay, seed):
    n = len(x)
    pd = int(predelay * SR)
    if pd:
        x = np.concatenate([np.zeros((pd, 2)), x])[:n]
    # input diffusion: two allpass chains, decorrelated L/R
    for dl, dr, g in ((142, 151, 0.62), (107, 113, 0.62), (379, 367, 0.55), (277, 263, 0.55)):
        s = max(1.0, size) ** 0.5
        x = np.stack([allpass(x[:, 0], int(dl * s), g), allpass(x[:, 1], int(dr * s), g)], 1)
    base = np.array([1009, 1097, 1181, 1277, 1361, 1453, 1549, 1627,
                     1709, 1801, 1889, 1979, 2063, 2153, 2251, 2339], float)
    D = np.maximum(97, (base * size).astype(np.int64))
    M = len(D)
    g = 10.0 ** (-3.0 * D / (SR * t60))
    r = np.random.default_rng(seed)
    sg = r.choice([-1.0, 1.0], M)
    even = (np.arange(M) % 2 == 0)
    in_l, in_r = np.where(even, sg, 0.0), np.where(~even, sg, 0.0)
    cl = r.choice([-1.0, 1.0], M) / np.sqrt(M)
    cr = r.choice([-1.0, 1.0], M) / np.sqrt(M)
    L = int(D.min())
    B = 1 << int(np.ceil(np.log2(D.max() + L + 4)))
    buf = np.zeros((M, B))
    out = np.zeros((n, 2))
    rows = np.arange(M)[:, None]
    for c0 in range(0, n, L):
        c1 = min(n, c0 + L)
        tt = np.arange(c0, c1)[None, :]
        r0 = buf[rows, (tt - D[:, None]) & (B - 1)]
        r1 = buf[rows, (tt - D[:, None] - 1) & (B - 1)]
        fb = g[:, None] * ((1.0 - damp) * r0 + damp * r1)      # lossy, HF-damped
        fb -= (2.0 / M) * fb.sum(0, keepdims=True)              # Householder mix
        xi = x[c0:c1]
        buf[rows, tt & (B - 1)] = fb + in_l[:, None] * xi[:, 0] + in_r[:, None] * xi[:, 1]
        out[c0:c1, 0] = cl @ r0
        out[c0:c1, 1] = cr @ r0
    return out


def reverb(x, t60=2.0, size=1.0, damp=0.3, predelay=0.015, seed=11):
    """FDN reverb (16 lines, Householder feedback, allpass pre-diffusion),
    calibrated to unit energy gain so send levels mean something."""
    key = (t60, size, damp, predelay, seed)
    if key not in _REV_CAL:
        m = int(min(4.0, t60 * 1.1) * SR)
        imp = np.zeros((m, 2))
        imp[0] = 1.0
        ir = _fdn(imp, t60, size, damp, predelay, seed)
        _REV_CAL[key] = 1.0 / np.sqrt(np.sum(ir ** 2) / 2.0)
    x = np.asarray(x, float)
    if x.ndim == 1:
        x = np.stack([x, x], 1) * 0.7071
    return _fdn(x, t60, size, damp, predelay, seed) * _REV_CAL[key]


# =============================================================================
# 3. Mixer, cue sheet
# =============================================================================
class Mix:
    def __init__(self):
        self.b = {}

    def get(self, name):
        if name not in self.b:
            self.b[name] = np.zeros((N, 2))
        return self.b[name]

    def add(self, name, sig, t, gain_db=0.0, pan=0.0, sends=None, fade=True):
        s = np.asarray(sig, float)
        if len(s) == 0:
            return
        if fade:
            s = fades(s, 0.0004, 0.002)
        st = pan2(s, pan) * db(gain_db)
        i0 = int(round(t * SR))
        a, b = max(0, i0), min(N, i0 + len(st))
        if b <= a:
            return
        seg = st[a - i0:b - i0]
        self.get(name)[a:b] += seg
        for nm, g in (sends or {}).items():
            self.get(nm)[a:b] += seg * db(g)


CUES = []


def cue(frame, stem, sound, how):
    CUES.append((float(frame), stem, sound, how))


# =============================================================================
# 4. Instruments
# =============================================================================
_HAT_F = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)


def kick(rng, f_hi=160.0, f_lo=46.0, decay=0.30, click=0.5, drive=1.6):
    n = int(decay * 5 * SR)
    t = tsec(n)
    f = f_lo + (f_hi - f_lo) * np.exp(-t / 0.032)
    body = osc_sin(f, n) * env_perc(n, 0.0008, decay)
    ck = filt(white(n, rng) * np.exp(-t / 0.0018), ("bp", 3800, 0.9)) * click
    return fades(np.tanh(drive * (body + ck)) / np.tanh(drive), 0.0003, 0.01)


def snare(rng, tone=185.0, decay=0.15, noise=1.0):
    n = int(0.7 * SR)
    t = tsec(n)
    tonal = (osc_sin(tone * (1 + 0.3 * np.exp(-t / 0.01)), n) + 0.45 * osc_sin(tone * 1.73, n)) * env_perc(n, 0.0008, 0.045)
    nz = filt(white(n, rng), ("hp", 1400), ("peak", 4200, 0.9, 5.0), ("lp", 11000)) * env_perc(n, 0.0006, decay)
    return fades(np.tanh(1.3 * (0.55 * tonal + 0.8 * noise * nz)), 0.0003, 0.02)


def clap(rng, decay=0.11):
    n = int(0.6 * SR)
    t = tsec(n)
    e = np.zeros(n)
    for d in (0.0, 0.0085, 0.017, 0.0265):
        i = int(d * SR)
        e[i:] += 0.8 * np.exp(-t[:n - i] / 0.0035)
    i = int(0.0265 * SR)
    e[i:] += 0.55 * np.exp(-t[:n - i] / decay)
    nz = filt(white(n, rng), ("bp", 1250, 1.1)) + 0.6 * filt(white(n, rng), ("bp", 2400, 1.4))
    return fades(nz * e, 0.0002, 0.02)


def hat(rng, open_=False, decay=None, tone=1.0):
    n = int((0.6 if open_ else 0.15) * SR)
    metal = sum(osc_pulse(f * tone * 1.5, n, 0.5, rng.uniform()) for f in _HAT_F)
    y = filt(0.6 * metal + 0.5 * white(n, rng), ("hp", 7000), ("peak", 10500, 1.0, 4.0))
    d = decay or (0.22 if open_ else 0.032)
    return fades(y * env_perc(n, 0.0004, d), 0.0002, 0.01)


def tom(rng, f0=95.0, decay=0.35, skin=0.5):
    n = int(decay * 5 * SR)
    t = tsec(n)
    f = f0 * (1 + 0.55 * np.exp(-t / 0.04))
    body = osc_sin(f, n) * env_perc(n, 0.001, decay) + 0.3 * osc_sin(f * 1.6, n) * env_perc(n, 0.001, decay * 0.4)
    sk = filt(white(n, rng), ("bp", 900, 0.8)) * env_perc(n, 0.0005, 0.03) * skin
    return fades(np.tanh(1.4 * (body + sk)), 0.0003, 0.02)


def crash(rng, decay=1.6, bright=1.0, length=None):
    n = int((length or decay * 3.5) * SR)
    t = tsec(n)
    out = np.zeros((n, 2))
    for c in range(2):
        metal = sum(osc_pulse(f * rng.uniform(2.9, 3.3), n, 0.5, rng.uniform()) for f in _HAT_F)
        y = filt(0.7 * white(n, rng) + 0.35 * metal, ("hp", 2800 * bright), ("peak", 6500, 0.7, 3.0), ("lp", 15000))
        out[:, c] = y * env_perc(n, 0.0015, decay) * (0.65 + 0.35 * np.exp(-t / 0.09))
    return fades(out, 0.0003, 0.05)


def bell(freq, decay=0.5, partials=((1.0, 1.0, 1.0), (2.0, 0.22, 0.55), (3.0, 0.1, 0.35), (4.17, 0.05, 0.2)), attack=0.0015):
    n = int(decay * 6 * SR)
    t = tsec(n)
    y = np.zeros(n)
    for r, a, d in partials:
        if freq * r < 0.45 * SR:
            y += a * np.sin(TAU * freq * r * t) * np.exp(-t / (decay * d))
    return fades(y * smoothstep(t / attack), 0.0, 0.01)


def ep_note(m, dur, vel=0.8):
    """FM electric piano: 1:1 modulator with decaying index (bark), 14:1 tine."""
    f = mtof(m)
    n = int((dur + 1.0) * SR)
    t = tsec(n)
    idx = (0.35 + 1.4 * vel) * np.exp(-t / 0.18) + 0.22
    car = np.sin(TAU * f * t + idx * np.sin(TAU * f * t))
    tine = np.sin(TAU * min(f * 14.0, 14000.0) * t) * np.exp(-t / 0.012) * 0.10 * vel
    amp = env_perc(n, 0.003, 1.5 * (261.6 / f) ** 0.45)
    y = (car * amp + tine) * release_env(n, dur, 0.35)
    return np.tanh(y * (1.0 + vel)) / np.tanh(1.0 + vel) * vel


def saw_pad(midis, dur, rng, voices=5, detune=9.0, cutoff=1300.0, attack=0.6, release=0.9):
    n = int((dur + release + 0.05) * SR)
    t = tsec(n)
    out = np.zeros((n, 2))
    for m in midis:
        f = mtof(m)
        for v in range(voices):
            c = (v - (voices - 1) / 2) / ((voices - 1) / 2) * detune
            drift = 1.0 + 0.0015 * np.sin(TAU * rng.uniform(0.1, 0.3) * t + rng.uniform(0, TAU))
            out += pan2(osc_saw(f * 2 ** (c / 1200) * drift, n, rng.uniform()), (v / (voices - 1)) * 1.2 - 0.6)
    out /= np.sqrt(len(midis) * voices)
    out = filt(out, ("lp", cutoff, 0.6), ("lp", cutoff * 1.4, 0.6), ("hp", 80))
    env = smoothstep(t / attack) * release_env(n, dur, release)
    return out * env[:, None]


def bass_note(m, dur, rng, sub=0.75, saw=0.55):
    f = mtof(m)
    n = int((dur + 0.06) * SR)
    t = tsec(n)
    y = sub * osc_sin(f, n) + saw * osc_saw(f, n, rng.uniform()) + 0.22 * osc_pulse(2 * f, n, 0.25)
    env = smoothstep(t / 0.003) * (0.55 + 0.45 * np.exp(-t / 0.07)) * release_env(n, dur, 0.035)
    return y * env


def pluck_note(m, dur, rng):
    f = mtof(m)
    n = int((dur + 0.15) * SR)
    t = tsec(n)
    y = osc_pulse(f, n, 0.3, rng.uniform()) + 0.45 * osc_saw(2 * f, n, rng.uniform())
    return y * smoothstep(t / 0.002) * np.exp(-t / 0.09) * release_env(n, dur, 0.03)


def brass_chord(midis, dur, rng, bright=1.0, attack=0.025, voices=4, detune=11.0, release=0.25):
    """'Brass' saw stack: detuned saws with pitch scoop, delayed vibrato and a
    time-varying low-pass envelope (the brass 'blat')."""
    n = int((dur + release + 0.05) * SR)
    t = tsec(n)
    out = np.zeros((n, 2))
    for i, m in enumerate(midis):
        f = mtof(m)
        scoop = 1.0 - 0.022 * np.exp(-t / 0.035)
        vib = 1.0 + 0.004 * np.sin(TAU * 5.3 * t + rng.uniform(0, TAU)) * smoothstep((t - 0.12) / 0.3)
        for v in range(voices):
            c = (v - (voices - 1) / 2) / ((voices - 1) / 2) * detune
            pan = np.clip(((i + 0.5) / len(midis)) * 1.4 - 0.7 + (v - 1.5) * 0.12, -0.9, 0.9)
            out += pan2(osc_saw(f * 2 ** (c / 1200) * scoop * vib, n, rng.uniform()), pan)
    out /= np.sqrt(len(midis) * voices)
    fc = 300.0 + bright * (5200.0 * env_perc(n, attack * 1.5, 0.22) + 1500.0)
    out = svf(out, fc, 0.9, "lp")
    env = smoothstep(t / attack) * release_env(n, dur, release)
    return out * env[:, None]


def strings_trem(midis, dur, rng, rate_hz=14.0, cutoff=4200.0):
    n = int((dur + 0.15) * SR)
    t = tsec(n)
    out = np.zeros((n, 2))
    for i, m in enumerate(midis):
        for v in range(3):
            f = mtof(m) * 2 ** ((v - 1) * 7 / 1200) * (1 + 0.003 * np.sin(TAU * 5.8 * t + rng.uniform(0, TAU)))
            out += pan2(osc_saw(f, n, rng.uniform()), (i / max(1, len(midis) - 1)) * 1.2 - 0.6)
    out = filt(out / np.sqrt(3 * len(midis)), ("lp", cutoff, 0.7), ("hp", 250))
    trem = 0.35 + 0.65 * np.abs(np.sin(np.pi * rate_hz * t)) ** 1.5
    return out * (trem * smoothstep(t / 0.02) * release_env(n, dur, 0.1))[:, None]


def choir(midis, dur, rng, vowel=((800, 80, 1.0), (1150, 90, 0.55), (2900, 120, 0.3), (3300, 140, 0.18))):
    """Choir-like 'aah': vibrato saws through parallel formant band-passes."""
    n = int(dur * SR)
    t = tsec(n)
    out = np.zeros((n, 2))
    for i, m in enumerate(midis):
        for v in range(3):
            vib = 1 + 0.006 * np.sin(TAU * rng.uniform(4.8, 5.8) * t + rng.uniform(0, TAU))
            drift = 1 + 0.002 * np.sin(TAU * rng.uniform(0.2, 0.5) * t + rng.uniform(0, TAU))
            s = osc_saw(mtof(m) * 2 ** ((v - 1) * 9 / 1200) * vib * drift, n, rng.uniform())
            out += pan2(s, rng.uniform(-0.8, 0.8))
    y = sum(g * filt(out, ("bp", f, f / bw)) for f, bw, g in vowel)
    return filt(y, ("hp", 220)) / np.sqrt(3 * len(midis))


# =============================================================================
# 5. Sound effects (each returns a mono or stereo array starting at t=0)
# =============================================================================
def sfx_pen(strokes, rng):
    """Pen on paper: band-passed friction noise whose centre frequency follows
    stroke speed, rough 'tooth' modulation, a paper-body band and pen-down ticks."""
    end = max(s[0] + s[1] for s in strokes) + 0.05
    n = int(end * SR)
    amp = np.zeros(n)
    fc = np.full(n, 2600.0)
    taps = np.zeros(n)
    for t0, d, p, v in strokes:
        i0, m = int(t0 * SR), int(d * SR)
        if m < 16 or i0 >= n:
            continue
        tt = np.arange(m) / SR
        e = smoothstep(tt / 0.007) * smoothstep((d - tt) / 0.012) * (0.75 + 0.25 * np.sin(np.pi * tt / d)) * p
        L = min(m, n - i0)
        amp[i0:i0 + L] = np.maximum(amp[i0:i0 + L], e[:L])
        fc[i0:i0 + L] = ((2100 + 1700 * v) * (1 + 0.18 * np.sin(TAU * tt / d * rng.uniform(0.8, 2.2))))[:L]
        taps[i0] += 0.5 * p
    grain = np.abs(filt(white(n, rng), ("lp", 140)))
    grain = 0.5 + 0.5 * grain / (grain.max() + 1e-9)
    nz = white(n, rng)
    hiss = svf(nz, fc, 0.9, "bp") + 0.35 * filt(nz, ("hp", 5500))
    body = 0.22 * filt(nz, ("bp", 850, 0.9))
    k = filt(white(400, rng) * np.exp(-np.arange(400) / SR / 0.0007), ("bp", 3200, 1.0))
    y = (hiss + body) * amp * grain + 0.6 * fftconv(taps, k)[:n]
    return fades(y, 0.001, 0.01)


def pen_strokes(text, dur, rng, pressure=1.0, frantic=False):
    counts = dict(L=2, E=4, A=3, R=3, N=3, I=1, F=3, S=1, T=2)
    items = []
    for ch in text:
        if ch == " ":
            items.append(("gap", 0.12))
            continue
        for _ in range(1 if ch == "." else counts.get(ch, 2)):
            items.append(("st", 0.03 if ch == "." else rng.uniform(0.055, 0.11)))
            items.append(("gap", rng.uniform(0.015, 0.035)))
        items.append(("gap", rng.uniform(0.04, 0.07)))
    scale = dur / sum(d for _, d in items)
    out, tt = [], 0.0
    for kind, d in items:
        d *= scale
        if kind == "st":
            out.append((tt, d, pressure * rng.uniform(0.75, 1.0), rng.uniform(0.2, 1.0) + (0.5 if frantic else 0.0)))
        tt += d
    return out


def sfx_sip(rng):
    n = int(0.8 * SR)
    t = tsec(n)
    lift = filt(white(n, rng), ("bp", 2600, 2.0)) * env_pts(n, [(0, 0), (0.01, 0.12), (0.05, 0)])
    sl_env = smoothstep((t - 0.12) / 0.07) * smoothstep((0.5 - t) / 0.06)
    am = np.abs(filt(white(n, rng), ("bp", 24, 1.5)))
    am = 0.35 + 0.65 * am / (am.max() + 1e-9)
    slurp = svf(white(n, rng), 1300 + 1500 * smoothstep((t - 0.12) / 0.38), 1.6, "bp") * sl_env * am
    gt = np.clip(t - 0.58, 0, None)
    gulp = np.sin(TAU * np.cumsum(170 + 170 * np.minimum(gt / 0.06, 1)) / SR) * env_pts(n, [(0, 0), (0.58, 0), (0.585, 0.5), (0.65, 0)])
    gulp += filt(white(n, rng), ("bp", 420, 3.0)) * env_pts(n, [(0, 0), (0.58, 0), (0.585, 0.25), (0.62, 0)])
    return fades(0.7 * slurp + 0.45 * gulp + lift, 0.002, 0.02)


def sfx_mug_down(rng):
    n = int(0.45 * SR)
    t = tsec(n)
    thunk = osc_sin(150 * (1 + 0.3 * np.exp(-t / 0.01)), n) * env_perc(n, 0.0005, 0.035)
    knock = filt(white(n, rng), ("bp", 620, 1.0)) * env_perc(n, 0.0003, 0.012)
    ring = sum(a * np.sin(TAU * f * t) * np.exp(-t / d) for f, a, d in ((1870, 0.25, 0.09), (3140, 0.15, 0.06), (4410, 0.08, 0.04)))
    return fades(0.9 * thunk + 0.6 * knock + 0.35 * ring * smoothstep(t / 0.0005), 0.0002, 0.02)


def notif_ding(f1, f2, soft=False):
    p = ((1.0, 1.0, 1.0), (2.0, 0.16, 0.5), (3.0, 0.05, 0.3))
    a = bell(f1, 0.42 if soft else 0.30, p)
    b = bell(f2, 0.62 if soft else 0.48, p)
    gap = int(0.078 * SR)
    y = np.zeros(max(len(a), gap + len(b)))
    y[:len(a)] += 0.75 * a
    y[gap:gap + len(b)] += b
    return y


def notif_alert(rng):
    n = int(0.6 * SR)
    t = tsec(n)
    y = np.zeros(n)
    for k in range(3):
        i0, m = int(k * 0.1 * SR), int(0.066 * SR)
        tone = osc_pulse(988.0, m) + osc_pulse(1397.0, m) + 0.5 * osc_pulse(1480.0, m)
        y[i0:i0 + m] += fades(filt(tone, ("lp", 5000), ("hp", 400)), 0.002, 0.006)
    thump = osc_sin(110 * (1 + 0.5 * np.exp(-t / 0.02)), n) * env_perc(n, 0.001, 0.12)
    return fades(0.5 * y + 0.6 * thump, 0.0005, 0.02)


def sfx_key(rng, hard=1.0):
    n = int(0.07 * SR)
    t = tsec(n)
    click = filt(white(n, rng) * np.exp(-t / 0.0011), ("bp", rng.uniform(2300, 5200), 1.3))
    fb = rng.uniform(170, 430)
    body = osc_sin(fb * (1 + 0.15 * np.exp(-t / 0.004)), n) * env_perc(n, 0.0004, rng.uniform(0.008, 0.016))
    d = int(rng.uniform(0.005, 0.013) * SR)
    m = n - d
    bot = np.zeros(n)
    bot[d:] = filt(white(m, rng) * np.exp(-np.arange(m) / SR / 0.0016), ("bp", rng.uniform(1100, 2400), 1.2))
    return fades(0.9 * click + 0.55 * rng.uniform(0.6, 1.2) * body + 0.6 * hard * bot, 0.0002, 0.005)


def sfx_tick(rng, tock=False):
    n = int(0.05 * SR)
    t = tsec(n)
    f = 2100.0 if tock else 3000.0
    y = filt(white(n, rng) * np.exp(-t / 0.0007), ("bp", f * 1.4, 2.0)) + 0.5 * np.sin(TAU * f * t) * np.exp(-t / 0.008)
    return fades(y, 0.0002, 0.005)


def sfx_whoosh(rng, dur=0.24, peak=0.62, f_lo=280.0, f_hi=2600.0, q=1.1, pan_from=-0.7, pan_to=0.7, low=0.25):
    n = int(dur * SR)
    t = tsec(n)
    u = t / dur
    shape = np.where(u < peak, (u / peak) ** 2.2, np.clip((1 - u) / (1 - peak), 0, 1) ** 1.6)
    expo = np.where(u < peak, u / peak, 1 - 0.6 * (u - peak) / (1 - peak))
    fc = f_lo * (f_hi / f_lo) ** expo
    nz = colored(n, rng, 0.6)
    y = (svf(nz, fc, q, "bp") + low * filt(nz, ("lp", 400))) * shape
    return pan2(fades(y, 0.002, 0.01), pan_from + (pan_to - pan_from) * smoothstep(u))


def sfx_book(rng, r1, r2, r3):
    n = int(0.45 * SR)
    t = tsec(n)
    thud = osc_sin((70 + 40 * r1) * (1 + 0.8 * np.exp(-t / 0.012)), n) * env_perc(n, 0.0006, 0.07 + 0.05 * r2)
    slap = filt(white(n, rng), ("bp", 500 + 700 * r3, 0.9)) * env_perc(n, 0.0004, 0.02)
    pages = filt(white(n, rng), ("hp", 3000)) * env_perc(n, 0.002, 0.03) * 0.25
    return fades(np.tanh(1.5 * (thud + 0.7 * slap + pages)), 0.0002, 0.02)


def sfx_cup(rng, r1, r2):
    n = int(0.6 * SR)
    t = tsec(n)
    f0 = 1700 + 900 * r1
    ring = sum(a * np.sin(TAU * f0 * r * t + rng.uniform(0, TAU)) * np.exp(-t / d)
               for r, a, d in ((1.0, 1.0, 0.22), (1.58, 0.6, 0.15), (2.31, 0.4, 0.1), (3.17, 0.25, 0.06)))
    tick = filt(white(n, rng) * np.exp(-t / 0.0006), ("hp", 2500))
    thud = osc_sin(220 + 60 * r2, n) * env_perc(n, 0.0005, 0.02)
    return fades(0.45 * ring * smoothstep(t / 0.0004) + 0.6 * tick + 0.5 * thud, 0.0002, 0.03)


def sfx_paper(rng, dur=0.27):
    n = int(dur * SR)
    t = tsec(n)
    u = t / dur
    shape = np.sin(np.pi * np.clip(u, 0, 1)) ** 1.5
    nz = white(n, rng)
    y = svf(nz, 1800 * 2.6 ** u, 0.8, "bp") + 0.35 * filt(nz, ("bp", 700, 0.8)) * (0.6 + 0.4 * np.abs(np.sin(TAU * 9 * t)))
    return fades(y * shape, 0.002, 0.01)


def sfx_toast(rng):
    n = int(0.08 * SR)
    t = tsec(n)
    pop = np.sin(TAU * np.cumsum(700 + 900 * np.minimum(t / 0.025, 1)) / SR) * env_perc(n, 0.001, 0.018)
    tik = np.sin(TAU * 3300 * t) * env_perc(n, 0.0005, 0.006)
    return fades(0.7 * pop + 0.4 * tik, 0.0003, 0.005)


_VOWELS = [(800, 1200, 2500), (500, 1800, 2550), (300, 2250, 3000), (500, 900, 2400),
           (350, 800, 2300), (600, 1400, 2500), (650, 1700, 2600)]


def sfx_chatter(segments, rng):
    """Fast-forwarded tutorial voice from laptop speakers, without any real
    speech: a glottal saw with intonation, syllable envelopes, fricative bursts
    and three time-varying formant resonators.  Speed-up raises syllable rate,
    pitch and formants together (the chipmunk effect)."""
    t0, t1 = segments[0][0], segments[-1][1]
    n = int((t1 - t0) * SR)
    tt = tsec(n) + t0
    sp = np.ones(n)
    lvl = np.zeros(n)
    for a, b, s, l in segments:
        m = (tt >= a) & (tt < b)
        sp[m], lvl[m] = s, l
    knots_t, f1k, f2k, f3k = [], [], [], []
    amp = np.zeros(n)
    fric = np.zeros(n)
    f0 = np.zeros(n)
    pos, syl, phrase_len = 0.0, 0, rng.integers(5, 10)
    while pos < n / SR:
        s = sp[min(n - 1, int(pos * SR))]
        d = 0.17 / s ** 0.85 * rng.uniform(0.7, 1.3)
        i0, m = int(pos * SR), int(d * SR)
        if syl >= phrase_len:          # breath pause between phrases
            pos += d * 1.3
            syl, phrase_len = 0, rng.integers(5, 10)
            continue
        v = _VOWELS[rng.integers(len(_VOWELS))]
        sc = s ** 0.3
        knots_t.append(pos + d * 0.5)
        f1k.append(v[0] * sc)
        f2k.append(v[1] * sc)
        f3k.append(v[2] * sc)
        u = np.arange(m) / max(1, m)
        e = smoothstep(u / 0.18) * smoothstep((1 - u) / 0.3)
        L = min(m, n - i0)
        amp[i0:i0 + L] = np.maximum(amp[i0:i0 + L], e[:L] * rng.uniform(0.6, 1.0))
        if rng.random() < 0.55:
            cm = int(m * 0.28)
            ce = np.sin(np.pi * np.arange(cm) / max(1, cm))
            fric[i0:i0 + min(cm, n - i0)] += ce[:min(cm, n - i0)] * rng.uniform(0.3, 0.7)
        decl = 1.15 - 0.3 * syl / phrase_len
        f0[i0:i0 + L] = 112.0 * s ** 0.75 * decl * rng.uniform(0.9, 1.12)
        pos += d
        syl += 1
    f0[f0 == 0] = 112.0
    lvl = np.convolve(lvl, np.ones(480) / 480, "same")    # 10 ms ramps between speed-up segments
    f0 = filt(f0, ("lp", 25))
    f1 = np.interp(tt - t0, knots_t, f1k)
    f2 = np.interp(tt - t0, knots_t, f2k)
    f3 = np.interp(tt - t0, knots_t, f3k)
    src = osc_saw(f0, n) * amp
    nz = white(n, rng)
    y = svf(src, f1, 7.0, "bp") + 0.6 * svf(src, f2, 9.0, "bp") + 0.3 * svf(src, f3, 11.0, "bp")
    y += 0.5 * svf(nz, np.clip(4200 * sp ** 0.3, 0, 15000), 2.0, "bp") * fric
    y = filt(y, ("hp", 480), ("hp", 480), ("peak", 2500, 1.0, 4.0), ("lp", 6800))
    y = np.tanh(2.2 * norm(y)) * lvl
    return fades(y, 0.004, 0.01)


def music_stab(rng):
    """Harsh orchestral stab: D/Eb/Ab cluster brass+strings, timpani boom, cymbal."""
    br = brass_chord([50, 51, 56, 62, 63, 68, 74], 0.42, rng, bright=1.25, attack=0.006, voices=4, detune=16, release=0.5)
    st = strings_trem([62, 63, 68, 75, 80], 0.6, rng, rate_hz=0.0001, cutoff=6500)
    n = int(2.8 * SR)
    t = tsec(n)
    boom = osc_sin(62 * (1 + 0.6 * np.exp(-t / 0.05)), n) * env_perc(n, 0.001, 0.55)
    boom += filt(white(n, rng), ("lp", 300)) * env_perc(n, 0.0005, 0.06)
    out = np.zeros((n, 2))
    out[:len(br)] += 1.0 * br
    out[:len(st)] += 0.45 * st
    out += pan2(np.tanh(1.8 * boom), 0.0) * 0.9
    cr = crash(rng, 1.3)
    out[:min(n, len(cr))] += 0.35 * cr[:n]
    return fades(out, 0.0005, 0.3)


def sfx_scream_roar(rng, dur):
    """Silent-scream whoosh-roar: resonant swept noise, rumble, saturation, flanger."""
    n = int(dur * SR)
    t = tsec(n)
    u = t / dur
    out = np.zeros((n, 2))
    for c in range(2):
        nz = colored(n, rng, 0.7)
        fc = 380 * (1 + 6.5 * u ** 0.6)
        roar = svf(nz, fc, 3.0, "bp") + 0.6 * svf(nz, fc * 1.55, 4.0, "bp") + 0.5 * filt(colored(n, rng, 2.0), ("lp", 140))
        roar = np.tanh(2.4 * roar / (np.max(np.abs(roar)) + 1e-9))
        d = (1.5 + 3.5 * (0.5 + 0.5 * np.sin(TAU * (1.7 + c * 0.3) * t))) * SR / 1000
        out[:, c] = roar + 0.7 * vdelay(roar, d)
    env = smoothstep(u / 0.45) * (0.7 + 0.3 * u) * smoothstep((1 - u) / 0.03)
    return fades(out * env[:, None], 0.003, 0.02)


def sfx_sparkle(rng):
    """'Idea!' sparkle: fast rising bell arpeggio + airy shimmer."""
    n = int(1.4 * SR)
    y = np.zeros(n)
    for i, m in enumerate((84, 88, 91, 96, 100)):
        b = bell(mtof(m), 0.35, ((1, 1, 1), (2.76, 0.25, 0.4), (5.4, 0.1, 0.2)))
        i0 = int(i * 0.028 * SR)
        L = min(len(b), n - i0)
        y[i0:i0 + L] += b[:L] * (0.6 + 0.1 * i)
    sh = filt(white(n, rng), ("hp", 7000)) * env_pts(n, [(0, 0), (0.05, 0.12), (0.6, 0)])
    return fades(y + sh, 0.0005, 0.05)


def sfx_servo(rng, dur, f0, f1):
    n = int(dur * SR)
    t = tsec(n)
    u = t / dur
    f = f0 * (f1 / f0) ** smoothstep(u)
    y = filt(0.6 * osc_saw(f, n) + 0.4 * osc_pulse(2.01 * f, n, 0.3), ("bp", 1400, 0.7), ("lp", 5000))
    grind = filt(white(n, rng), ("bp", 3000, 2.0)) * 0.15 * (1 + np.sin(TAU * phase(0.5 * f, n)))
    return fades((y + grind) * smoothstep(u / 0.15) * smoothstep((1 - u) / 0.2), 0.001, 0.005)


def sfx_ratchet_lock(rng, span, size):
    """Ratchet clicks accelerating into a metallic lock that lands at `span` s."""
    n = int((span + 0.6) * SR)
    y = np.zeros(n)
    ck = filt(white(240, rng) * np.exp(-np.arange(240) / SR / 0.0006), ("bp", 4200, 1.5))
    k = rng.integers(3, 6)
    for i in range(k):
        ti = span * (1 - (1 - i / k) ** 1.4) * 0.92
        i0 = int(ti * SR)
        y[i0:i0 + 240] += ck * (0.5 + 0.1 * i)
    m = n - int(span * SR)
    tt = np.arange(m) / SR
    base = 520.0 / size
    lock = osc_sin(base * 0.5 * (1 + 0.5 * np.exp(-tt / 0.006)), m) * env_perc(m, 0.0004, 0.05)
    for r, a, d in ((1.0, 0.5, 0.12), (2.41, 0.35, 0.08), (3.93, 0.22, 0.05), (5.6, 0.12, 0.035)):
        lock += a * np.sin(TAU * base * r * tt + rng.uniform(0, TAU)) * np.exp(-tt / d)
    lock += filt(white(m, rng), ("bp", 2500, 0.8)) * env_perc(m, 0.0002, 0.006)
    y[int(span * SR):] += np.tanh(1.5 * lock)
    return fades(y, 0.0005, 0.02)


def sfx_relay(rng):
    n = int(0.06 * SR)
    t = tsec(n)
    y = filt(white(n, rng) * np.exp(-t / 0.0005), ("hp", 1500)) + 0.3 * np.sin(TAU * 4200 * t) * np.exp(-t / 0.004)
    y += 0.4 * osc_sin(300, n) * env_perc(n, 0.0003, 0.01)
    return fades(y, 0.0001, 0.005)


def sfx_whine(rng, dur):
    n = int(dur * SR)
    t = tsec(n)
    u = t / dur
    f = 180 * 9.0 ** (u ** 1.3)
    trem = 1 + 0.35 * np.sin(TAU * phase(6 + 26 * u, n))
    y = (osc_sin(f, n) + 0.25 * filt(osc_saw(f, n), ("lp", 3000))) * trem
    return fades(y * smoothstep(u / 0.3) * (0.4 + 0.6 * u), 0.003, 0.01)


def sfx_bubble(rng):
    n = int(0.07 * SR)
    t = tsec(n)
    f = rng.uniform(500, 1500) * (1 + 1.2 * (t / 0.07) ** 1.5)
    return fades(osc_sin(f, n) * env_perc(n, 0.003, 0.022), 0.001, 0.005)


def sfx_button(rng):
    """Deeply satisfying chunky button: click, resonant thock, latch, sub."""
    n = int(0.7 * SR)
    t = tsec(n)
    press = filt(white(n, rng) * np.exp(-t / 0.0012), ("bp", 2800, 1.1))
    body = osc_sin(115 * (1 - 0.4 * (1 - np.exp(-t / 0.05))), n) * env_perc(n, 0.0005, 0.14)
    thock = filt(white(n, rng), ("bp", 620, 3.0)) * env_perc(n, 0.0004, 0.05) * 2.0
    d = int(0.028 * SR)
    latch = np.zeros(n)
    tl = tsec(n - d)
    latch[d:] = filt(white(n - d, rng) * np.exp(-tl / 0.001), ("bp", 1500, 2.0)) + 0.4 * np.sin(TAU * 980 * tl) * np.exp(-tl / 0.02)
    sub = osc_sin(48, n) * env_perc(n, 0.002, 0.18)
    return fades(np.tanh(1.8 * (0.7 * press + body + thock + 0.6 * latch + 0.8 * sub)), 0.0002, 0.03)


def sfx_powerup(rng, dur=1.1):
    n = int(dur * SR)
    t = tsec(n)
    f = 40 + 70 * (1 - np.exp(-t / 0.22))
    y = filt(osc_saw(f, n) + 0.8 * osc_sin(f, n), ("lp", 1800)) * 0.6 + 0.4 * osc_sin(2 * f, n)
    sweep = svf(white(n, rng), 200 + 3000 * smoothstep(t / 0.4), 4.0, "bp") * env_pts(n, [(0, 0), (0.05, 0.3), (0.45, 0.05), (dur, 0)])
    return fades((y + sweep) * env_pts(n, [(0, 0), (0.04, 1.0), (0.35, 0.8), (dur, 0.0)]), 0.002, 0.05)


def machine_hum(n, rng):
    t = tsec(n)
    hum = (0.6 * np.sin(TAU * 55 * t) + 0.35 * np.sin(TAU * 110 * t + 0.4) + 0.18 * np.sin(TAU * 165 * t + 1.1)
           + 0.1 * np.sin(TAU * 220 * t + 2.0)) * (1 + 0.05 * np.sin(TAU * 0.7 * t))
    fan = filt(colored(n, rng, 1.0), ("lp", 520), ("hp", 80)) * 0.22
    whine = 0.035 * np.sin(TAU * 2130 * t) * (1 + 0.3 * np.sin(TAU * 3.1 * t))
    return 0.5 * hum + fan + whine


def sfx_scroll(rng):
    n = int(0.02 * SR)
    t = tsec(n)
    y = filt(white(n, rng) * np.exp(-t / 0.0004), ("bp", 2700, 2.5)) + 0.3 * np.sin(TAU * 1900 * t) * np.exp(-t / 0.003)
    return fades(y, 0.0001, 0.003)


def sfx_dot_matrix(rng, dur):
    """Dot-matrix printer: needle impulse bursts (~1.3 kHz, random dot dropouts)
    convolved with a tiny resonant click, line-feed motor buzz, paper rustle."""
    n = int(dur * SR)
    imp = np.zeros(n)
    lf = np.zeros(n)
    pos = 0.0
    while pos < dur:
        seg = rng.uniform(0.15, 0.23)
        rate = rng.uniform(1150, 1450)
        k = np.arange(int(seg * rate))
        times = pos + k / rate + rng.normal(0, 0.00005, len(k))
        keep = rng.random(len(k)) > 0.35
        carriage = np.sin(np.pi * k / max(1, len(k))) ** 0.3
        idx = (times[keep] * SR).astype(int)
        ok = idx < n
        np.add.at(imp, idx[ok], (carriage[keep] * rng.uniform(0.6, 1.0, keep.sum()))[ok])
        pos += seg
        i0, m = int(pos * SR), int(0.055 * SR)
        L = max(0, min(m, n - i0))
        lf[i0:i0 + L] = np.sin(np.pi * np.arange(L) / m)
        pos += 0.06
    kt = np.arange(int(0.004 * SR)) / SR
    kern = (np.sin(TAU * 2400 * kt) + 0.6 * np.sin(TAU * 4100 * kt)) * np.exp(-kt / 0.0007)
    y = fftconv(imp, kern)[:n]
    t = tsec(n)
    motor = filt(osc_saw(95, n) * (1 + 0.3 * white(n, rng)), ("bp", 700, 0.8)) * lf * 0.5
    rustle = filt(white(n, rng), ("bp", 1800, 0.7)) * (0.08 + 0.12 * lf)
    return fades(norm(y) + motor + rustle, 0.003, 0.02)


def sfx_clack(rng):
    n = int(0.5 * SR)
    t = tsec(n)
    puff = filt(white(n, rng), ("lp", 700)) * env_pts(n, [(0, 0), (0.035, 0.25), (0.045, 0.0)])
    tc = np.clip(t - 0.04, 0, None)
    on = (t >= 0.04).astype(float)
    clack = filt(white(n, rng), ("bp", 2600, 0.9)) * np.exp(-tc / 0.007) * on
    body = osc_sin(300, n) * np.exp(-tc / 0.025) * on
    rat = filt(white(n, rng), ("bp", 1800, 2.0)) * np.exp(-np.clip(t - 0.052, 0, None) / 0.004) * (t >= 0.052)
    return fades(puff + clack + 0.6 * body + 0.4 * rat, 0.003, 0.03)


def sfx_chair_roll(rng, dur=0.75):
    n = int(dur * SR)
    t = tsec(n)
    u = t / dur
    bumps = np.abs(filt(white(n, rng), ("bp", 38, 1.0)))
    bumps = 0.4 + 0.6 * bumps / (bumps.max() + 1e-9)
    y = filt(colored(n, rng, 1.0), ("bp", 420, 0.6)) * bumps + 0.6 * filt(colored(n, rng, 2.0), ("lp", 160))
    creak_t = np.clip(t, 0, 0.18)
    creak = filt(osc_saw(140 + 60 * np.sin(TAU * 3 * creak_t), n), ("bp", 900, 3.0)) * env_pts(n, [(0, 0), (0.02, 0.25), (0.18, 0)])
    return fades(y * np.sin(np.pi * u) ** 0.8 + creak, 0.005, 0.03)


def sfx_cloth(rng, dur, intensity=1.0):
    n = int(dur * SR)
    t = tsec(n)
    u = t / dur
    grains = (rng.random(n) < 0.004).astype(float) * rng.uniform(0.3, 1.0, n)
    crackle = fftconv(grains, np.exp(-np.arange(200) / 40.0))[:n]
    swell = np.abs(filt(white(n, rng), ("lp", 6)))
    swell = 0.3 + 0.7 * swell / (swell.max() + 1e-9)
    nz = white(n, rng)
    y = filt(nz, ("bp", 2200, 0.6)) * swell * 0.6 + filt(nz * crackle, ("hp", 1500)) * 0.8
    return fades(y * np.sin(np.pi * u) ** 0.7 * intensity, 0.01, 0.03)


def sfx_step(rng, creak=False):
    n = int(0.35 * SR)
    t = tsec(n)
    heel = osc_sin(88 * (1 + 0.5 * np.exp(-t / 0.01)), n) * env_perc(n, 0.0008, 0.045)
    heel += filt(white(n, rng), ("bp", 380, 1.0)) * env_perc(n, 0.0005, 0.03)
    ts = np.clip(t - 0.028, 0, None)
    scuff = filt(white(n, rng), ("bp", 2400, 0.8)) * np.exp(-ts / 0.03) * (t >= 0.028) * smoothstep(ts / 0.005)
    y = heel + 0.35 * scuff
    if creak:
        y += filt(osc_saw(90 + 25 * np.sin(TAU * 5 * t), n), ("bp", 700, 4.0)) * env_pts(n, [(0, 0), (0.05, 0.12), (0.3, 0)])
    return fades(y, 0.0005, 0.02)


def sfx_breath(rng, dur):
    n = int(dur * SR)
    u = tsec(n) / dur
    shape = smoothstep(u / 0.75) * smoothstep((1 - u) / 0.12)
    nz = colored(n, rng, 0.4)
    y = svf(nz, 900 + 900 * u, 0.8, "bp") + 0.3 * filt(nz, ("bp", 3200, 1.0))
    return fades(filt(y, ("hp", 300)) * shape, 0.01, 0.02)


def sfx_handle(rng):
    n = int(0.4 * SR)
    t = tsec(n)

    def metal(t0, f, a):
        tt = np.clip(t - t0, 0, None)
        on = t >= t0
        y = filt(white(n, rng), ("bp", f, 5.0)) * np.exp(-tt / 0.003) * on
        for r, g, d in ((1.0, 0.4, 0.04), (1.76, 0.25, 0.03)):
            y += g * np.sin(TAU * f * 0.7 * r * tt) * np.exp(-tt / d) * on
        return a * y

    squeak = filt(osc_saw(1700 + 300 * np.sin(TAU * 7 * t), n), ("bp", 2400, 6.0)) * env_pts(n, [(0, 0), (0.03, 0), (0.05, 0.06), (0.09, 0)])
    return fades(metal(0.0, 3000, 1.0) + metal(0.075, 1400, 0.8) + squeak, 0.0003, 0.03)


def sfx_creak(rng, dur):
    """Wooden stick-slip creak: jittery impulse train through wood resonances."""
    n = int(dur * SR)
    t = tsec(n)
    u = t / dur
    rate = 45 + 90 * smoothstep(u) + 25 * np.sin(TAU * 2.3 * t)
    rate *= 1 + 0.25 * filt(white(n, rng), ("lp", 12)) / 0.1
    ph = np.cumsum(np.clip(rate, 10, 400)) / SR
    imp = np.diff(np.floor(ph), prepend=0.0) * rng.uniform(0.5, 1.0, n)
    y = sum(g * filt(imp, ("bp", f, q)) for f, q, g in ((310, 6, 1.0), (760, 8, 0.7), (1450, 9, 0.4), (2600, 10, 0.15)))
    env = smoothstep(u / 0.4) * (0.5 + 0.5 * u) * smoothstep((1 - u) / 0.05)
    return fades(norm(y) * env, 0.01, 0.02)


def sfx_slam(rng):
    """Massive wall slam: flam of four wall impacts, sub boom, wood slap, debris."""
    n = int(2.5 * SR)
    t = tsec(n)
    out = np.zeros((n, 2))
    for k, (dt, pan, a) in enumerate(((0.0, -0.5, 1.0), (0.018, 0.6, 0.8), (0.041, -0.2, 0.7), (0.063, 0.3, 0.6))):
        i0 = int(dt * SR)
        m = n - i0
        tt = tsec(m)
        slap = filt(white(m, rng), ("bp", 1100, 0.7)) * np.exp(-tt / 0.03)
        thud = filt(white(m, rng), ("lp", 380)) * np.exp(-tt / 0.11)
        out[i0:] += pan2(a * (0.9 * slap + 1.4 * thud), pan)
    boom = osc_sin(50 * (1 + 0.8 * np.exp(-t / 0.05)) * (1 - 0.3 * (1 - np.exp(-t / 0.5))), n) * env_perc(n, 0.002, 0.32)
    debris = filt(white(n, rng) * (rng.random(n) < 0.01), ("bp", 3000, 0.8)) * env_pts(n, [(0, 0), (0.08, 0.5), (0.8, 0)])
    out += pan2(np.tanh(2.0 * boom) * 1.6, 0.0) + pan2(debris, 0.2)
    return fades(np.tanh(out * 0.9), 0.0003, 0.2)


def sfx_clank(rng):
    n = int(1.6 * SR)
    t = tsec(n)
    base = rng.uniform(150, 700)
    y = np.zeros(n)
    for r, a, d in ((1.0, 1.0, 0.9), (2.32, 0.6, 0.5), (4.25, 0.4, 0.3), (6.63, 0.25, 0.18), (9.1, 0.12, 0.1)):
        y += a * np.sin(TAU * base * r * t + rng.uniform(0, TAU)) * np.exp(-t / (d * rng.uniform(0.6, 1.4)))
    y += filt(white(n, rng), ("bp", base * 3, 1.0)) * env_perc(n, 0.0002, 0.01)
    return fades(y * smoothstep(t / 0.0006), 0.0003, 0.05)


def sfx_riser_alarm(rng, dur):
    n = int(dur * SR)
    t = tsec(n)
    u = t / dur
    two = np.where((t * 9) % 1 < 0.5, 1.0, 1.335)
    f = 620 * two * 2 ** (u * 1.5)
    tone = filt(osc_pulse(f, n, 0.5) + 0.5 * osc_saw(f * 1.004, n), ("lp", 4000), ("hp", 300))
    noise = svf(white(n, rng), 600 * 10 ** u, 2.0, "bp")
    return fades((0.5 * tone + 0.6 * noise) * (0.3 + 0.7 * u ** 1.5), 0.002, 0.01)


def sfx_accel_whoosh(rng, dur=1.4):
    n = int(dur * SR)
    t = tsec(n)
    out = np.zeros((n, 2))
    fc = 150 + 9000 * smoothstep(t / 0.28) * np.exp(-np.clip(t - 0.28, 0, None) / 0.5)
    for c in range(2):
        nz = colored(n, rng, 0.8)
        out[:, c] = svf(nz, np.maximum(fc, 120), 1.2, "lp")
    tone = filt(osc_saw(70 * 2 ** (3 * smoothstep(t / 0.35)), n), ("lp", 1500)) * env_pts(n, [(0, 0), (0.05, 0.5), (0.4, 0.4), (dur, 0)])
    sub = osc_sin(45 * (1 + 0.6 * np.exp(-t / 0.08)), n) * env_perc(n, 0.003, 0.35)
    env = env_pts(n, [(0, 0), (0.06, 1.0), (0.3, 0.9), (dur, 0.0)])
    return fades(out * env[:, None] + pan2(0.6 * tone + 1.1 * sub, 0.0), 0.003, 0.05)


def sfx_yank(rng):
    """Chair yank: zipper rasp (fast AM teeth, rising band-pass) then thud."""
    n = int(0.6 * SR)
    t = tsec(n)
    zd = 0.09
    zu = np.clip(t / zd, 0, 1)
    teeth = 0.5 + 0.5 * np.sign(np.sin(TAU * phase(120 + 380 * zu, n)))
    zip_ = svf(white(n, rng), 600 * (4000 / 600) ** zu, 2.5, "bp") * teeth * (t < zd) * smoothstep(zu / 0.2)
    tt = np.clip(t - zd, 0, None)
    on = t >= zd
    thud = osc_sin(75 * (1 + 0.8 * np.exp(-tt / 0.015)), n) * np.exp(-tt / 0.12) * on * smoothstep(tt / 0.001)
    thud += filt(white(n, rng), ("bp", 700, 1.0)) * np.exp(-tt / 0.02) * on
    return fades(0.7 * zip_ + 1.2 * np.tanh(1.5 * thud), 0.001, 0.03)


def sfx_beta_blip(rng):
    """Tiny 'beta' glitch: stuttered square chirps, sample-and-hold + 4-bit crush."""
    n = int(0.16 * SR)
    out = np.zeros((n, 2))
    pos = 0
    for k, (f, d) in enumerate(((1250, 0.022), (1875, 0.018), (2500, 0.026))):
        m = int(d * SR)
        s = osc_pulse(f * (1 + 0.15 * np.linspace(0, 1, m)), m, 0.35)
        s = np.repeat(s[::6], 6)[:m]
        s = np.round(s * 7) / 7
        out[pos:pos + m] += pan2(fades(s, 0.001, 0.002), (-0.5, 0.5, 0.0)[k])
        pos += m + int(0.011 * SR)
    m = int(0.03 * SR)
    ch = np.repeat(osc_pulse(np.linspace(1800, 400, m), m, 0.5)[::8], 8)[:m]
    out[pos:pos + m] += pan2(fades(np.round(ch * 5) / 5 * 0.6, 0.001, 0.005), 0.0)
    return out


# =============================================================================
# 6. Voice: Windows offline TTS -> PA announcement / whisper
# =============================================================================
VOICE_PA = "Microsoft Zira Desktop"
VOICE_WHISPER = "Microsoft David Desktop"
PA_PARTS = ["Congratulations.", "You are now an expert."]
WHISPER_PARTS = ["Finally.", "I'm caught up."]
MANIFEST = os.path.join(SOURCE, "tts_manifest.json")
PA_PITCH_ST = 1.0        # PA voice pitched down this many semitones ("a touch")
PA_CHIME_GAP = 0.10      # second chime tone, seconds after pa_start
PA_CHIME_LEAD = 0.135    # voice starts this long after pa_start (chime first, voice right after)
PA_MIN_GAP = 0.08        # minimum added pause between the two PA sentences


def _ps(script):
    enc = base64.b64encode(("$ProgressPreference='SilentlyContinue';" + script).encode("utf-16-le")).decode("ascii")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-600:])
    return r.stdout


def installed_voices():
    out = _ps("Add-Type -AssemblyName System.Speech;$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              "$s.GetInstalledVoices()|ForEach-Object{$_.VoiceInfo.Name};$s.Dispose()")
    return [v.strip() for v in out.splitlines() if v.strip()]


def run_tts(voice, text, rate, path):
    q = lambda s: s.replace("'", "''")  # noqa: E731
    _ps("Add-Type -AssemblyName System.Speech;$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{q(voice)}');$s.Rate={int(rate)};$s.Volume=100;"
        f"$s.SetOutputToWaveFile('{q(path)}');$s.Speak('{q(text)}');$s.Dispose()")
    if not os.path.exists(path):
        raise RuntimeError(f"TTS produced no file: {path}")


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read_wav_mono(path):
    with wave.open(path, "rb") as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise RuntimeError(f"{path}: expected 16-bit PCM")
    x = np.frombuffer(raw, "<i2").astype(float) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(1)
    return x, sr


def to48k_trim(x, sr, thr_db=-42.0):
    """Trim leading/trailing silence (on the raw samples: SAPI output carries a
    DC offset while speaking, so DC is removed *after* trimming), resample to
    48 kHz and high-pass."""
    a = np.abs(x)
    idx = np.flatnonzero(a > a.max() * db(thr_db))
    i0, i1 = max(0, idx[0] - int(0.012 * sr)), min(len(x), idx[-1] + int(0.02 * sr))
    pad = int(0.05 * sr)
    xp = np.concatenate([np.zeros(pad), x[i0:i1], np.zeros(pad)])
    y = resample_len(xp, int(round(len(xp) * SR / sr)))
    y = filt(y, ("hp", 60.0), ("hp", 60.0))
    p48 = int(round(pad * SR / sr))
    return fades(y[p48:len(y) - p48], 0.004, 0.012)


def get_voice_sources(retts=False):
    """Return {'pa': [arrays], 'whisper': [arrays], meta} using the cache when valid."""
    os.makedirs(SOURCE, exist_ok=True)
    man = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as fh:
            man = json.load(fh)

    def cached(key, voice, parts):
        e = man.get(key)
        if retts or not e or e.get("voice") != voice or [p["text"] for p in e.get("parts", [])] != parts:
            return None
        for p in e["parts"]:
            fp = os.path.join(SOURCE, p["file"])
            if not os.path.exists(fp) or sha256(fp) != p["sha256"]:
                return None
        if key == "pa" and e.get("dur_s", 1e9) * pa_pitch + PA_MIN_GAP > pa_avail:
            return None          # the PA slot shrank: re-render at a faster rate
        return e

    pa_speech_t = F(E["pa_start"]) + PA_CHIME_LEAD
    pa_avail = F(E["pa_end"]) - 0.025 - pa_speech_t
    pa_pitch = 2 ** (PA_PITCH_ST / 12)
    w_avail = F(E["whisper_end"]) - F(E["whisper_start"]) - 0.02 - 0.035
    need = [k for k, v, p in (("pa", VOICE_PA, PA_PARTS), ("whisper", VOICE_WHISPER, WHISPER_PARTS)) if not cached(k, v, p)]
    if need:
        voices = installed_voices()
        man["installed_voices"] = voices
        man["engine"] = "Windows System.Speech.Synthesis.SpeechSynthesizer (SAPI 5, offline, built into Windows)"
        for key in need:
            voice, parts = (VOICE_PA, PA_PARTS) if key == "pa" else (VOICE_WHISPER, WHISPER_PARTS)
            if voice not in voices:
                raise SystemExit(f"TTS voice '{voice}' is not installed (have: {voices})")
            rates = [3, 4, 5, 6, 7, 8] if key == "pa" else [2]
            chosen = None
            for rate in rates:
                files = []
                for i, text in enumerate(parts):
                    fn = f"{key}_{i + 1}_r{rate}.wav"
                    run_tts(voice, text, rate, os.path.join(SOURCE, fn))
                    files.append(fn)
                dur = sum(len(to48k_trim(*read_wav_mono(os.path.join(SOURCE, fn)))) for fn in files) / SR
                fits = (dur * pa_pitch + PA_MIN_GAP <= pa_avail) if key == "pa" else True
                if fits or rate == rates[-1]:
                    chosen = (rate, files, dur)
                    break
                for fn in files:
                    os.remove(os.path.join(SOURCE, fn))
            rate, files, dur = chosen
            man[key] = dict(voice=voice, rate=rate, dur_s=round(dur, 4), parts=[dict(text=t, file=fn, sha256=sha256(os.path.join(SOURCE, fn)))
                                                         for t, fn in zip(parts, files)])
            log(f"TTS {key}: '{voice}' rate {rate}")
        with open(MANIFEST, "w", encoding="utf-8") as fh:
            json.dump(man, fh, indent=2)
    else:
        log("TTS: using cached voice renders in audio/source/")
    src = {}
    for key in ("pa", "whisper"):
        src[key] = [to48k_trim(*read_wav_mono(os.path.join(SOURCE, p["file"]))) for p in man[key]["parts"]]
    return src, man, dict(pa_avail=pa_avail, pa_pitch=pa_pitch, w_avail=w_avail, pa_speech_t=pa_speech_t)


def stft(x, n_fft=1024, hop=256):
    win = np.hanning(n_fft + 1)[:-1]
    xp = np.concatenate([np.zeros(n_fft // 2), x, np.zeros(n_fft)])
    nfr = 1 + (len(xp) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(nfr)[:, None]
    return np.fft.rfft(xp[idx] * win, axis=1)


def istft(X, n_fft=1024, hop=256):
    win = np.hanning(n_fft + 1)[:-1]
    fr = np.fft.irfft(X, n=n_fft, axis=1) * win
    L = hop * (len(fr) - 1) + n_fft
    out = np.zeros(L)
    ws = np.zeros(L)
    for i in range(len(fr)):
        out[i * hop:i * hop + n_fft] += fr[i]
        ws[i * hop:i * hop + n_fft] += win ** 2
    out /= np.maximum(ws, 1e-3)
    return out[n_fft // 2:]


def whisperize(x, target_s, rng):
    """Turn voiced TTS into a whisper: keep each frame's spectral *envelope*
    (cepstrally liftered, so the harmonics/pitch disappear), re-shape it the way
    whispered speech is shaped, time-stretch the magnitude frames to the exact
    slot, then resynthesise with uniformly random phase so the excitation is
    breath noise instead of a glottal buzz."""
    n_fft, hop = 1024, 256
    X = stft(x, n_fft, hop)
    mag = np.abs(X)
    logm = np.log(mag + 1e-7)
    cep = np.fft.irfft(logm, n=n_fft, axis=1)
    qc = 110
    lift = np.zeros(n_fft)
    lift[:qc] = 1.0
    lift[qc - 30:qc] = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, 30))
    lift[-(qc - 1):] = lift[1:qc][::-1]
    env = np.exp(np.fft.rfft(cep * lift[None, :], axis=1).real)
    m = 0.9 * env + 0.1 * mag
    f = np.fft.rfftfreq(n_fft, 1.0 / SR)
    shape = np.minimum(1.0, (f / 450.0) ** 2) * (1 + 0.6 * np.exp(-((f - 3200) / 1800) ** 2))
    ref = m[:, (f > 6000) & (f < 9000)].mean(1, keepdims=True)
    hf = np.where(f > 9500, np.exp(-(f - 9500) / 3500.0), 0.0)[None, :]
    m = m * shape[None, :] + 0.6 * ref * hf
    e = np.sqrt(np.mean(m ** 2, axis=1))
    g = np.where(e > 1e-3 * e.max(), np.clip((e / e.max()) ** -0.22, 1.0, 2.5), 1.0)
    m *= g[:, None]
    n_in = len(x)
    n_out = int(round(target_s * SR))
    nfr_out = int(round((len(m) - 1) * n_out / n_in)) + 1
    pos = np.linspace(0, len(m) - 1, nfr_out)
    i0 = np.floor(pos).astype(int)
    i1 = np.minimum(i0 + 1, len(m) - 1)
    w = (pos - i0)[:, None]
    ms = (1 - w) * m[i0] + w * m[i1]
    Y = ms * np.exp(1j * rng.uniform(0, TAU, ms.shape))
    y = istft(Y, n_fft, hop)[:n_out]
    y = filt(y, ("hp", 300), ("hp", 300), ("peak", 3600, 0.8, 3.0), ("hs", 4500, 0.7, 5.0), ("lp", 13000))
    return fades(norm(y), 0.01, 0.03)


def pa_chain(sr_len, events, rng):
    """Industrial PA: robot tint, horn band-pass, soft clip, crush, multi-tap
    echo across the hall, then a big FDN hall."""
    x = np.zeros(sr_len)
    for kind, i0, sig in events:
        if kind == "speech":
            t = tsec(len(sig))
            s = sig + 0.28 * sig * np.sin(TAU * 58 * t)          # slight ring-mod 'robot'
            s = comb_fb(s, int(0.0065 * SR), 0.32)               # metallic horn colour
            x[i0:i0 + len(s)] += norm(s)
        else:
            x[i0:i0 + len(sig)] += sig
    y = filt(x, ("hp", 300), ("hp", 300), ("lp", 3500), ("lp", 3500), ("peak", 1650, 1.2, 5.0), ("peak", 2800, 2.0, 2.0))
    y = np.tanh(2.6 * y / (np.max(np.abs(y)) + 1e-9)) / np.tanh(2.6)
    crush = np.round(np.repeat(y[::3], 3)[:len(y)] * 48) / 48     # ~16 kHz hold, ~6.5-bit
    y = filt(0.55 * crush + 0.45 * y, ("lp", 3900), ("hp", 250))
    out = pan2(y, 0.0)
    for dly, g, pan, lp in ((0.15, -9, -0.65, 3200), (0.31, -12, 0.6, 2600), (0.49, -15, -0.35, 2100),
                            (0.72, -19, 0.45, 1700), (1.02, -24, -0.1, 1400)):
        i = int(dly * SR)
        tap = filt(y, ("lp", lp))
        out[i:] += pan2(tap[:len(y) - i], pan) * db(g)
    wet = reverb(out, t60=3.4, size=1.6, damp=0.45, predelay=0.035, seed=41)
    return out + wet * db(-5)


# =============================================================================
# 7. The score
# =============================================================================
def score(mx, voice_src, voice_meta):
    """Place every sound.  All frames come from timeline.E; all musical
    anchors (downbeats, stops, chord points) are derived from E + the
    speed-driven beat grid, so a retimed timeline re-flows the score."""
    spd = chan("speed")
    keys = key_times()

    def bx(frame):
        """Beat phase at the start of `frame`."""
        return beat_at(F(frame))

    def bnext(frame, tol=0.15):
        """First integer beat at (or a hair before) `frame`."""
        return int(np.ceil(bx(frame) - tol))

    def put(buf, sig, t0, gain, pan):
        i0 = int(t0 * SR)
        s = pan2(sig, pan) * gain
        L = min(len(s), len(buf) - i0)
        if L > 0 and i0 >= 0:
            buf[i0:i0 + L] += s[:L]

    # the original lo-fi loop (Fmaj9 / Am9 / Dm9 / Bbmaj9) and its melody, in beats
    LOOP = [(41, [57, 60, 64, 67]), (45, [55, 59, 60, 64]), (38, [53, 57, 60, 64]), (34, [57, 60, 62, 65])]
    LOOP_PAD = [[53, 57, 60, 64], [52, 55, 57, 59], [50, 53, 57, 60], [50, 53, 57, 58]]
    RELIEF_PAD = [[53, 57, 60, 64, 67], [52, 55, 57, 59, 64], [50, 53, 57, 60, 64], [50, 53, 57, 58, 62]]
    MEL = [(0.5, 0.5, 79), (1.0, 0.5, 76), (1.5, 0.5, 72), (2.5, 0.5, 71), (3.0, 0.5, 72), (3.5, 0.5, 76),
           (4.5, 0.5, 77), (5.0, 0.5, 76), (5.5, 0.25, 72), (5.75, 0.25, 69), (6.5, 0.5, 74), (7.0, 1.0, 72)]

    def loop_events(x0, x1):
        chords, mel = [], []
        x, i = x0, 0
        while x1 - x >= 0.5:
            xe = min(x + 2, x1)
            chords.append((x, xe, LOOP[i % 4][0], LOOP[i % 4][1], i % 4))
            x, i = xe, i + 1
        for c in range(int(np.ceil((x1 - x0) / 8.0))):
            for dx, d, m in MEL:
                st_ = x0 + 8 * c + dx
                if st_ < x1 - 0.1:
                    mel.append((st_, min(d, x1 - st_), m))
        return chords, mel

    def ep_render(buf, chords, mel, off, vel=0.5, target=None):
        for x0, x1, bass, notes, _ in chords:
            tgt = target(x0) if target else buf
            d = bt(x1) - bt(x0)
            put(tgt, ep_note(bass, d, vel + 0.05), bt(x0) - off, 0.9, -0.1)
            for i, m in enumerate(notes):
                put(tgt, ep_note(m, d - 0.05, vel + 0.08 * rr.random()), bt(x0) - off + 0.012 * i + 0.004 * rr.random(), 0.55, -0.35 + 0.22 * i)
        for x0, dx, m in mel:
            tgt = target(x0) if target else buf
            put(tgt, ep_note(m, bt(x0 + dx) - bt(x0), 0.62), bt(x0) - off, 0.5, 0.25)

    def lofi(buf):
        w = 0.0016 * SR * (1 + np.sin(TAU * 0.55 * tsec(len(buf)))) + 0.0002 * SR * np.sin(TAU * 6.1 * tsec(len(buf)))
        return filt(np.tanh(1.2 * vdelay(buf, w)) / np.tanh(1.2), ("hp", 90), ("lp", 5200, 0.6))

    def crackle(n, r, rate):
        c = (r.random(n) < rate / SR) * r.uniform(0.2, 1.0, n) * np.sign(r.standard_normal(n))
        return filt(fftconv(c, np.exp(-np.arange(24) / 5.0))[:n], ("hp", 1800))

    # ------------------------------------------------------------------ AMBIENCE
    log("ambience: room tone")
    r = rng_for("room")
    n_room = int(F(E["walls_land"]) * SR) + int(0.05 * SR)
    room = np.zeros((n_room, 2))
    tt = tsec(n_room)
    city_swell = 0.75 + 0.25 * np.sin(TAU * 0.07 * tt) * np.sin(TAU * 0.023 * tt + 1.0)
    for c in range(2):
        air = filt(colored(n_room, r, 1.0), ("lp", 1100, 0.5), ("hp", 70))
        city = filt(colored(n_room, r, 2.0), ("lp", 150), ("hp", 28)) * city_swell
        room[:, c] = db(-47) * air + db(-44) * city
    room += pan2((np.sin(TAU * 60 * tt) + 0.4 * np.sin(TAU * 120 * tt + 0.7)) * db(-66), 0.0)
    cp = filt(colored(n_room, r, 1.5), ("bp", 380, 0.6)) * np.exp(-((tt - 4.6) / 1.2) ** 2) * db(-50)
    room += pan2(cp, np.clip((tt - 4.6) / 2.0, -0.6, 0.6))
    g = np.ones(n_room)
    a, b = int(F(E["silence_start"]) * SR), int(F(E["close_laptop"]) * SR)
    g[a:b] = db(-9)                                                    # 'very faint' room tone
    g[a - 480:a] = np.linspace(1.0, db(-9), 480)
    g[b:b + 9600] = np.linspace(db(-9), db(-2), 9600)
    g[b + 9600:] = db(-2)
    mx.add("amb", fades(room * g[:, None], 0.3, 0.025), 0.0)
    cue(1, "ambience", "Room tone (air, distant city rumble, mains hum, one car pass)",
        "Pink + brown noise, low/high-passed, slow traffic swell, 60/120 Hz sines; drops ~9 dB at frame "
        f"{E['silence_start']}, cut under the wall slam at {E['walls_land']}")

    # ------------------------------------------------------------------ ACT I
    log("act I")
    r = rng_for("pen")
    w1 = pen_strokes("LEARN AI.", F(E["write1_end"]) - F(E["write1_start"]), r, 0.9)
    mx.add("sfx", sfx_pen(w1, r), F(E["write1_start"]), -21, 0.1, {"sfx>room": -14})
    cue(E["write1_start"], "sfx", "Pen writes LEARN AI. (stroke per letter part)",
        "Speed-tracking band-passed friction noise (time-varying SVF), paper-tooth AM, pen-down ticks")
    ud = F(E["underline1_end"]) - F(E["underline1_start"])
    mx.add("sfx", sfx_pen([(0.0, ud - 0.04, 1.0, 0.9), (ud - 0.035, 0.03, 0.8, 1.4)], r), F(E["underline1_start"]), -19, 0.05, {"sfx>room": -14})
    cue(E["underline1_start"], "sfx", "Confident underline + flick", "One long pen stroke with a fast flick")
    w2 = pen_strokes("FASTER", F(E["write2_end"]) - F(E["write2_start"]), r, 1.0, frantic=True)
    mx.add("sfx", sfx_pen(w2, r), F(E["write2_start"]), -19, 0.1, {"sfx>room": -14})
    cue(E["write2_start"], "sfx", "Pen scribbles FASTER (faster, harder strokes)", "As above, frantic stroke timing")

    r = rng_for("sip1")
    mx.add("sfx", sfx_sip(r), F(E["sip1_start"]), -24, -0.1, {"sfx>room": -12})
    mx.add("sfx", sfx_mug_down(r), F(E["sip1_end"]), -17, -0.15, {"sfx>room": -10})
    cue(E["sip1_start"], "sfx", "Coffee: mug lift, slurp, gulp", "Band-passed noise with bubbly AM and rising centre, chirped gulp")
    cue(E["sip1_end"], "sfx", "Mug set down", "Pitched thunk + wood knock + three ceramic partials")

    # notification sounds by kind (timeline.NOTIFICATIONS)
    release_pitches = [(84, 89), (86, 91)]
    n_rel = 0
    for nt in T.NOTIFICATIONS:
        f, kind = nt["frame"], nt["kind"]
        if kind == "release":
            m1, m2 = release_pitches[n_rel % 2]
            n_rel += 1
            mx.add("sfx", notif_ding(mtof(m1), mtof(m2)), F(f), -15, 0.15, {"sfx>room": -16})
            cue(f, "sfx", f"Notification ding: {nt['text']}", "Two-note sine bell (partials 1/2/3), in key with the loop")
        elif kind == "alert":
            mx.add("sfx", notif_alert(rng_for("alert")), F(f), -12, 0.15, {"sfx>room": -14})
            cue(f, "sfx", f"Alert: {nt['text']}", "Triple pulse-wave beep on a tritone cluster + low thump")
    # ('hero', 'hero_alert', 'calm' are placed with their scenes below; ROADMAP OBSOLETE is silent by design)

    # clock: one formula from frame 1 to the dead stop, ticking faster with speed
    r = rng_for("clock")
    t, k = 0.25, 0
    while t < F(E["notif_do_that"]):
        s = chan_at("speed", t)
        a1 = t < F(E["typing_start"])
        bus = "sfx" if a1 else "sfx_a2"
        mx.add(bus, sfx_tick(r, k % 2 == 1), t, -44 if a1 else -36 + 6 * s, 0.45, {bus + ">room": -8})
        t += 1.0 / (1.0 + 14.0 * s ** 2.6)
        k += 1
    cue(1, "sfx", "Wall clock tick-tock (1 Hz, then racing)", "Noise-burst + sine ping; rate = 1 + 14*speed^2.6 Hz, from speed.py")

    # music: lo-fi EP loop (original), warm pad, vinyl crackle
    rr = rng_for("act1music")
    a2 = bnext(E["typing_start"])                     # first Act II downbeat
    x_sour = int(round(bx(E["smile_fade_start"])))     # the loop sours as the smile dies
    chords, melody = loop_events(0, x_sour)
    chords += [(x_sour, a2 - 1, 34, [53, 55, 61, 65], 4), (a2 - 1, a2 - 0.5, 36, [53, 55, 58, 62], 5),
               (a2 - 0.5, a2, 36, [52, 55, 58, 61], 6)]
    melody += [(x_sour + 0.5, (a2 - 1) - (x_sour + 0.5), 73), (a2 - 1, 0.5, 72), (a2 - 0.5, 0.5, 73)]
    nbuf = int((bt(a2) + 2.5) * SR)
    ep = np.zeros((nbuf, 2))
    droop = np.zeros_like(ep)
    ep_render(ep, chords, melody, 0.0, target=lambda x0: droop if x_sour <= x0 < a2 - 1 else ep)
    # tape droop while the smile dies: pitch sags ~6% then recovers (variable delay)
    bump = np.exp(-((tsec(nbuf) - F(E["smile_fade_start"] + 5)) / 0.28) ** 2)
    ep = lofi(ep + vdelay(droop, np.cumsum(0.06 * bump)))
    mx.add("music", ep, 0.0, -17, 0.0, {"music>plate": -10})
    pads = [(x0, x1, LOOP_PAD[j] if j < 4 else ([49, 53, 55, 58] if j == 4 else [48, 52, 55, 58])) for x0, x1, _, _, j in chords]
    pads = pads[:-2] + [(a2 - 1, a2, [48, 52, 55, 58])]
    for i, (x0, x1, notes) in enumerate(pads):
        mx.add("music", saw_pad(notes, bt(x1) - bt(x0), rr, cutoff=1100, attack=0.9 if i == 0 else 0.5, release=0.7),
               bt(x0), -35, 0.0, {"music>plate": -6})
    n = int(F(E["typing_start"] + 4) * SR)
    cr_ = crackle(n, rr, 6.0) + 0.02 * filt(white(n, rr), ("bp", 5000, 0.5))
    mx.add("music", fades(cr_, 0.3, 0.2), 0.0, -47, 0.15)
    cue(1, "music", "Lo-fi loop: Fmaj9 / Am9 / Dm9 / Bbmaj9, original EP melody, warm pad, vinyl crackle",
        "FM electric piano (1:1 bark + 14:1 tine) on the speed.py beat grid, tape wow (variable delay), detuned-saw pad")
    cue(F(E["smile_fade_start"]) * FPS + 1, "music", "Loop sours to Bbm6 with a tape-droop pitch sag",
        f"Variable-delay pitch bend (~6%) on the minor iv chord (beat {x_sour})")
    cue(bt(a2 - 1) * FPS + 1, "music", "C9sus4 -> C7b9 turnaround into Act II", "Same EP/pad, tension voicings")

    # ------------------------------------------------------------------ ACT II
    log("act II")
    stop = F(E["notif_do_that"])
    r = rng_for("keys")
    nk = 0
    for kk in keys:
        t, f = kk["t"], kk["frame"]
        if E["typing_start"] <= f < E["notif_do_that"]:
            bus = "sfx_a2"
        elif E["build_start"] <= f <= E["build_end"]:
            bus = "sfx_a3"
        elif f >= E["yank"]:
            bus = "sfx"
        else:
            continue
        s = chan_at("speed", t)
        gk = -21 + 5 * s + r.uniform(-2.5, 1.5) - (5 if not kk["primary"] else 0)
        mx.add(bus, sfx_key(r, 0.7 + 0.5 * s), t + r.uniform(0.0, 0.006), gk, r.uniform(-0.3, 0.3), {bus + ">room": -15})
        nk += 1
    cue(E["typing_start"], "sfx", f"Keyboard: {nk} key clicks on every speed.py key press (+ ghost strokes), Acts II-IV",
        "Per-key random noise click + pitched body + bottom-out transient; density from typing_phase; muted from the dead stop")

    r = rng_for("snaps")
    for i, f in enumerate(E["snaps"]):
        dur = 0.2 - 0.008 * i
        side = 1 if i % 2 == 0 else -1
        mx.add("sfx_a2", sfx_whoosh(r, dur, 0.6, 300, 2400 + 100 * i, 1.1, -0.6 * side, 0.6 * side), F(f) - 0.6 * dur, -15, 0.0,
               {"sfx_a2>room": -14})
    cue(E["snaps"][0], "sfx", f"Whooshes on {len(E['snaps'])} head snaps (frames {', '.join(map(str, E['snaps']))})",
        "Pink noise through a swept band-pass SVF, peak on the snap frame, panned laptop<->monitor")

    r = rng_for("spawns")
    LO = T.SPAWN_LAND_OFFSET
    for e in EV["books"]:
        mx.add("sfx_a2", sfx_book(r, e["r1"], e["r2"], e["r3"]), F(e["frame"] + LO["books"]), -12 - 3 * e["r2"], -0.5 + e["r1"], {"sfx_a2>room": -9})
    for e in EV["cups"]:
        mx.add("sfx_a2", sfx_cup(r, e["r1"], e["r2"]), F(e["frame"] + LO["cups"]), -19, -0.6 + 1.2 * e["r3"], {"sfx_a2>room": -10})
    for e in EV["papers"]:
        mx.add("sfx_a2", sfx_paper(r), F(e["frame"] + LO["papers"]), -20, -0.7 + 1.4 * e["r1"], {"sfx_a2>room": -12})
    for e in EV["toasts"]:
        mx.add("sfx_a2", sfx_toast(r), F(e["frame"] + LO["toasts"]), -25, 0.2 + 0.3 * e["r1"], {"sfx_a2>room": -16})
    if EV["books"]:
        cue(EV["books"][0]["frame"] + LO["books"], "sfx", f"{len(EV['books'])} book thumps (land = spawn + {LO['books']})",
            "Pitch-dropped sine thud + band-passed slap + page flutter")
    if EV["cups"]:
        cue(EV["cups"][0]["frame"] + LO["cups"], "sfx", f"{len(EV['cups'])} cup clinks (settle = spawn + {LO['cups']})", "Inharmonic ceramic partials + contact tick")
    if EV["papers"]:
        cue(EV["papers"][0]["frame"], "sfx", f"{len(EV['papers'])} paper swishes", "Rising band-passed noise, 0.27 s")
    if EV["toasts"]:
        cue(EV["toasts"][0]["frame"], "sfx", f"{len(EV['toasts'])} UI toast ticks", "Sine chirp pop + 3.3 kHz tick")

    r = rng_for("chatter")
    segs = [(F(E["tutorial_2x"]), F(E["tutorial_4x"]), 2.0, 0.8), (F(E["tutorial_4x"]), F(E["tutorial_16x"]), 4.0, 0.9),
            (F(E["tutorial_16x"]), F(E["nod_start"]), 16.0, 1.0), (F(E["nod_start"]), stop, 16.0, 0.6)]
    mx.add("sfx_a2", sfx_chatter(segs, r), segs[0][0], -15, 0.3, {"sfx_a2>room": -12})
    cue(E["tutorial_2x"], "sfx", "Tutorial voice fast-forward chatter 2x -> 4x -> 16x (no real speech)",
        "Glottal saw + 3 time-varying formant SVFs + fricative bursts; rate/pitch/formants scale with speed-up")

    # rhythm section locked to the speed-driven beat grid
    r = rng_for("act2music")
    x_stop = bx(E["notif_do_that"])
    xs_f = int(np.floor(x_stop))
    seg0, seg1 = int(F(E["typing_start"] - 2) * SR), int(stop * SR) + int(0.3 * SR)
    L = seg1 - seg0
    bass = np.zeros(L)
    arp = np.zeros(L)
    blocks = [(a2, a2 + 2, 38, [62, 65, 69, 74]), (a2 + 2, a2 + 4, 34, [58, 62, 65, 70]),
              (a2 + 4, a2 + 6, 31, [55, 58, 62, 67]), (a2 + 6, a2 + 8, 33, [57, 61, 64, 69])]
    climb = []
    x, m = float(a2 + 8), 34
    while x < x_stop:
        climb.append((x, m))
        m += 1
        x += 0.5 if x < xs_f else 0.25

    def root_at(x):
        for x0, x1, rt, tones in blocks:
            if x0 <= x < x1:
                return rt, tones
        c = [mm for xx, mm in climb if xx <= x + 1e-9]
        if not c:
            return blocks[-1][2], blocks[-1][3]
        return c[-1], [c[-1] + 24, c[-1] + 28, c[-1] + 31, c[-1] + 36]

    def put1(buf, sig, t0):
        i0 = int(t0 * SR) - seg0
        L2 = min(len(sig), len(buf) - i0)
        if L2 > 0 and i0 >= 0:
            buf[i0:i0 + L2] += sig[:L2]

    x = float(a2)
    while x < x_stop - 1e-6:
        step = 0.5 if x < a2 + 4 else 0.25
        rt, tones = root_at(x)
        j = int(round(x / step))
        d = bt(x + step) - bt(x)
        put1(bass, bass_note(rt + (12 if j % 2 else 0), d * 0.9, r), bt(x))
        if x >= a2 + 4:
            put1(arp, pluck_note(tones[j % 4] + (12 if (j // 4) % 2 else 0), d * 0.8, r), bt(x))
        x += step
    tl = (np.arange(L) + seg0) / SR
    sp_seg = spd[seg0:seg1]
    cutoff = 170.0 * (1 + 40.0 * sp_seg ** 2.2)
    bass = svf(bass, cutoff, 0.9, "lp")
    arp = svf(arp, np.minimum(cutoff * 1.6, 12000), 1.4, "lp")
    kicks = [float(x) for x in range(a2, xs_f + 1)] + [x + 0.75 for x in range(a2 + 6, xs_f)] + [xs_f + 0.25, xs_f + 0.5]
    duck = np.ones(L)
    for xk in kicks:
        tk = bt(xk)
        if tk < stop:
            u = tl - tk
            duck *= 1 - 0.55 * np.exp(-np.clip(u, 0, None) / 0.07) * (u >= 0)
    lvl = 0.3 + 0.7 * sp_seg ** 1.3
    mx.add("music", bass * duck * lvl, seg0 / SR, -9, 0.0, {"music>plate": -20})
    dl = int(0.09 * SR)
    arp_st = np.stack([arp, np.concatenate([np.zeros(dl), arp[:-dl]]) * 0.5], 1)
    mx.add("music", arp_st * (duck * lvl)[:, None], seg0 / SR, -17, 0.0, {"music>plate": -9})
    for xk in kicks:
        tk = bt(xk)
        if tk < stop - 0.01:
            mx.add("music", kick(r), tk, -18 + 11 * chan_at("speed", tk), 0.0, {"music>plate": -24})
    for xc in (a2 + 3, a2 + 5, a2 + 7, a2 + 9, xs_f, xs_f + 0.5):
        if bt(xc) < stop - 0.01:
            mx.add("music", clap(r), bt(xc), -17 + 4 * chan_at("speed", bt(xc)), 0.0, {"music>plate": -8})
    x = float(a2 + 2)
    while bt(x) < stop - 0.01:
        step = 0.5 if x < a2 + 5 else 0.25
        acc = 0 if (x * 2) % 1 == 0 else -3
        mx.add("music", hat(r, tone=1.0 + 0.05 * r.random()), bt(x), -24 + acc + 3 * chan_at("speed", bt(x)), 0.25)
        if x >= a2 + 6 and (x % 1) == 0.5:
            mx.add("music", hat(r, open_=True), bt(x), -26, -0.2, {"music>plate": -12})
        x += step
    x = xs_f - 0.5
    while bt(x) < stop - 0.005:
        step = 0.25 if x < xs_f + 0.25 else 0.125
        mx.add("music", snare(r, decay=0.09), bt(x), -24 + 10 * (x - (xs_f - 0.5)), 0.05, {"music>plate": -12})
        x += step
    for xc, gc in ((a2 + 2, -24), (a2 + 4, -22), (a2 + 6, -20), (a2 + 8, -16)):
        if bt(xc) < stop - 0.05:
            mx.add("music", crash(r, 1.4), bt(xc), gc, 0.0, {"music>plate": -12})
    rs0 = F(E["tutorial_16x"])
    nrs = int((stop - rs0) * SR)
    ur = tsec(nrs) / (stop - rs0)
    riser = svf(colored(nrs, r, 0.5), 400 * 18 ** ur, 2.5, "bp") * ur ** 1.6
    riser += 0.3 * filt(osc_saw(110 * 2 ** (2 * ur), nrs) + osc_saw(110.8 * 2 ** (2 * ur), nrs), ("lp", 2500)) * ur ** 2
    mx.add("music", riser, rs0, -17, 0.0, {"music>plate": -6})
    cue(bt(a2) * FPS + 1, "music", "Rhythm layer on the beat grid (D minor): kick, pulsing octave bass, then hats, claps, 16th arp",
        "Layers enter as speed rises; bass/arp low-pass cutoff = 170*(1+40*speed^2.2) Hz (time-varying SVF), kick side-chain")
    cue(E["tutorial_16x"], "music", "Chromatic bass climb, snare roll and riser into the stop", "Swept noise + rising detuned saws")

    # dead stop: soft tone + faint clock on the (slow) grid until the next hit
    mx.add("sfx", notif_ding(mtof(84), mtof(89), soft=True), stop, -24, 0.1)
    held = list(range(xs_f + 1, int(np.ceil(bx(E["notif_better"])))))
    for i, xb in enumerate(held):
        mx.add("sfx", sfx_tick(rng_for(f"deadtick{i}"), i % 2 == 1), bt(xb), -42, 0.45)
    cue(E["notif_do_that"], "all", "DEAD STOP: AI CAN NOW DO THAT FOR YOU.",
        "Music, keys, clutter and their reverb tails hard-gated on the frame; only room tone, a soft dry ding and "
        f"{len(held)} faint clock ticks on beats {held[0]}-{held[-1]}" if held else "Hard gate on the frame")

    # stab + scream + frantic return
    r = rng_for("stab")
    tb = F(E["notif_better"])
    mx.add("music", music_stab(r), tb, -7, 0.0, {"music>plate": -6})
    al = filt(osc_pulse(1318.5, int(0.12 * SR)) + osc_pulse(1396.9, int(0.12 * SR)), ("lp", 5000))
    mx.add("sfx", fades(al, 0.002, 0.01), tb, -18, 0.15)
    cue(E["notif_better"], "music", "Harsh orchestral stab + alert", "D/Eb/Ab cluster saw-brass + strings, timpani boom, crash; minor-2nd pulse alert")
    sc0, fr_end = F(E["scream_start"]), F(E["scream_end"] + 1)
    mx.add("sfx", sfx_scream_roar(r, fr_end - sc0), sc0, -11, 0.0, {"sfx>room": -10})
    cue(E["scream_start"], "sfx", "Silent-scream whoosh-roar (no voice)",
        f"Resonant swept noise + brown rumble, tanh drive, flanger; cut on frame {E['scream_end'] + 1}")
    x = np.ceil(bx(E["scream_start"]) * 2 - 0.2) / 2
    while bt(x) < fr_end - 0.01:
        t = bt(x)
        if (x * 2) % 1 == 0:
            mx.add("music", kick(r, decay=0.25), t, -10, 0.0)
        mx.add("music", hat(r), t, -22 if (x * 4) % 2 else -19, 0.3)
        rt = 38 if (x * 4) % 4 != 3 else 39
        mx.add("music", fades(filt(bass_note(rt + (12 if (x * 4) % 2 else 0), (bt(x + 0.25) - t) * 0.85, r), ("lp", 2500)), 0.001, 0.003), t, -11, 0.0)
        if x % 1 == 0:
            mx.add("music", snare(r), t, -13, 0.0, {"music>plate": -8})
        x += 0.25
    xt = np.floor(beat_at(fr_end))
    for i in range(4):
        if bt(xt + 0.125 * i) < fr_end - 0.01:
            mx.add("music", tom(r, 150 - 22 * i, 0.25), bt(xt + 0.125 * i), -12, -0.5 + 0.33 * i, {"music>plate": -10})
    st = strings_trem([74, 75, 81, 86], fr_end - sc0, r, 15.0)
    mx.add("music", st * np.linspace(0.4, 1.0, len(st))[:, None], sc0, -12, 0.0, {"music>plate": -8})
    cue(E["scream_start"], "music", "Frantic return: 180 bpm drums, 16th bass with b2 grit, tremolo string cluster, tom fill",
        f"Beat-grid sequenced; hard cut at the idea (frame {E['scream_end'] + 1})")

    # ------------------------------------------------------------------ ACT III
    log("act III")
    r = rng_for("act3")
    mx.add("sfx", sfx_sparkle(r), F(E["idea"]), -16, 0.0, {"sfx>room": -6})
    cue(E["idea"], "sfx", "'Idea' sparkle", "Rising five-note bell arpeggio + high shimmer")
    parts = E["machine_parts"]
    for i, f in enumerate(parts):
        gap = (parts[i] - parts[i - 1]) / FPS if i else 0.2
        span = min(0.07, gap * 0.6)
        sv_d = max(0.05, min(0.16, gap * 0.9))
        pan = -0.7 + 1.4 * i / max(1, len(parts) - 1)
        f0 = r.uniform(250, 500)
        mx.add("sfx_a3", sfx_servo(r, sv_d, f0, f0 * r.uniform(1.6, 2.6)), F(f) - span - sv_d * 0.85, -24, pan, {"sfx_a3>room": -12})
        mx.add("sfx_a3", sfx_ratchet_lock(r, span, r.uniform(0.7, 1.5)), F(f) - span, -12, pan, {"sfx_a3>room": -9})
    cue(parts[0], "sfx", f"Machine assembly: servo whir + ratchet + metal lock on each of {len(parts)} parts (frames {', '.join(map(str, parts))})",
        "Gliding saw/pulse motor through band-pass; accelerating noise clicks; modal metal impact landing on the frame")

    ml, bp = F(E["machine_lights"]), F(E["button_press"])
    mx.add("sfx_a3", sfx_relay(r), ml, -14, -0.3, {"sfx_a3>room": -8})
    mx.add("sfx_a3", sfx_whine(r, bp - ml), ml, -24, 0.1, {"sfx_a3>room": -10})
    t = ml + 0.06
    while t < bp - 0.03:
        mx.add("sfx_a3", sfx_relay(r), t, -22 + 6 * (t - ml) / (bp - ml), r.uniform(-0.6, 0.6), {"sfx_a3>room": -10})
        t += 0.06 + 0.18 * (1 - (t - ml) / (bp - ml)) ** 1.5 * r.uniform(0.7, 1.3)
    t = ml
    while t < F(E["silence_start"]) - 0.1:
        mx.add("sfx_a3", sfx_bubble(r), t, -30 if t < bp else -35, r.uniform(-0.7, 0.7), {"sfx_a3>room": -8})
        t += r.exponential(1.0 / (14 if t < bp else 5))
    cue(E["machine_lights"], "sfx", "Machine wakes: rising whine, accelerating relay clicks, data-bubble trickles",
        "Exponential sine/saw sweep with speeding tremolo; HP noise clicks; random chirped sine 'bloops' (continue until the cut)")
    mx.add("sfx_a3", sfx_button(r), bp, -5, 0.0, {"sfx_a3>room": -8})
    mx.add("sfx_a3", sfx_powerup(r), bp + 0.02, -14, 0.0, {"sfx_a3>room": -10})
    nh = int((F(E["silence_start"]) - bp - 0.25) * SR)
    mx.add("sfx_a3", machine_hum(nh, r) * smoothstep(tsec(nh) / 0.6), bp + 0.25, -27, 0.05, {"sfx_a3>room": -14}, fade=False)
    cue(E["button_press"], "sfx", "BIG BUTTON clunk + power-up, then machine hum",
        "Click + resonant 620 Hz thock + latch + 48 Hz sub (tanh); saw/sine 'vwoom' rising to 110 Hz; 55 Hz harmonic hum + fan noise")

    r = rng_for("sip2")
    mx.add("sfx", sfx_sip(r), F(E["sip2_start"]), -25, -0.1, {"sfx>room": -12})
    mx.add("sfx", sfx_mug_down(r), F(E["sip2_end"]), -18, -0.15, {"sfx>room": -10})
    cue(E["sip2_start"], "sfx", "Second sip + mug down", "As Act I")
    chime = np.zeros(int(1.8 * SR))
    for i, m in enumerate((77, 81, 84)):
        b = bell(mtof(m), 0.55, ((1, 1, 1), (3.9, 0.12, 0.25), (9.2, 0.03, 0.08)))
        i0 = int(i * 0.11 * SR)
        chime[i0:i0 + len(b)] += b[:len(chime) - i0]
    mx.add("sfx", fades(chime, 0.0, 0.2), F(E["notif_roadmap"]), -21, 0.15, {"sfx>room": -10})
    cue(E["notif_roadmap"], "sfx", "Roadmap ready chime (calm)", "F-A-C soft bell arpeggio")
    mx.add("sfx", sfx_whoosh(rng_for("open"), 0.18, 0.4, 900, 4500, 1.5, 0.0, 0.3, 0.0), F(E["roadmap_open"]), -28, 0.0)
    t0s, t_end = F(E["scroll_start"]), F(E["print_start"] - 1)
    t, k = t0s, 0
    while t < t_end:
        u = (t - t0s) / (t_end - t0s)
        mx.add("sfx_a3", sfx_scroll(r), t, -23 + 3 * u, 0.35)
        t += 1.0 / (7.0 + 23.0 * u ** 1.3)
        k += 1
    cue(E["scroll_start"], "sfx", f"Mouse-wheel scroll ticks, accelerating ({k} ticks, 7 -> 30 Hz)", "Tiny band-passed noise detents + 1.9 kHz ping")
    mx.add("sfx_a3", sfx_dot_matrix(r, F(E["print_end"]) - F(E["print_start"])), F(E["print_start"]), -13, 0.25, {"sfx_a3>room": -10})
    cue(E["print_start"], "sfx", "Dot-matrix printer / paper feed (to frame %d)" % E["print_end"],
        "Needle impulse bursts at ~1.3 kHz with dot dropouts convolved with a resonant click, line-feed motor buzz, paper rustle")
    for f in (E["look_scroll"], E["look_machine"]):
        mx.add("sfx", sfx_cloth(r, 0.25, 0.6), F(f), -32, 0.0, {"sfx>room": -10})

    # Act III music: montage groove, wake-up build, relief pad, lo-fi reprise
    r = rng_for("act3music")
    x_m, x_w = bnext(E["build_start"]), bnext(E["machine_lights"])
    MONT = [(38, [62, 69, 65, 69]), (34, [58, 65, 62, 65]), (41, [65, 72, 69, 72]), (36, [60, 67, 64, 67])]
    for xb in range(x_m, x_w):
        for h in (0.0, 0.5):
            mx.add("music", kick(r, decay=0.26), bt(xb + h), -9 if h == 0 else -13, 0.0, {"music>plate": -24})
        mx.add("music", clap(r), bt(xb + 0.5), -15, 0.0, {"music>plate": -8})
    x = float(x_m)
    while x < x_w - 1e-6:
        i = int(np.floor(x)) - x_m
        pat = MONT[i % 3] if (i % 3 != 2 or (x % 1) < 0.5) else MONT[3]
        rt, tones = pat
        d = bt(x + 0.25) - bt(x)
        j = int(round(x * 4)) % 4
        mx.add("music", filt(bass_note(rt + (12 if j == 2 else 0), d * 0.85, r), ("lp", 1800)), bt(x), -11, 0.0)
        mx.add("music", filt(pluck_note(tones[j] + 12, d * 0.7, r), ("lp", 5000)), bt(x), -21, 0.3 if j % 2 else -0.3, {"music>plate": -8})
        mx.add("music", hat(r), bt(x), -25 if j % 2 else -22, 0.3)
        x += 0.25
    x = float(x_w)
    while bt(x) < bp - 0.01:
        d = bt(x + 0.25) - bt(x)
        mx.add("music", filt(bass_note(33 + (12 if int(round(x * 4)) % 2 else 0), d * 0.85, r), ("lp", 1200 + 2500 * (x - x_w))), bt(x), -11, 0.0)
        x += 0.25
    for xk in range(x_w, int(np.ceil(bx(E["button_press"])))):
        mx.add("music", kick(r), bt(xk), -8, 0.0)
    t = bt(x_w + 0.5)
    while t < bp - 0.012:
        u = (t - bt(x_w + 0.5)) / (bp - bt(x_w + 0.5))
        mx.add("music", snare(r, decay=0.07), t, -22 + 12 * u, 0.0, {"music>plate": -10})
        t += 0.11 * (1 - 0.65 * u)
    nr = int((bp - ml) * SR)
    ur = tsec(nr) / (bp - ml)
    wr = svf(colored(nr, r, 0.5), 300 * 25 ** ur, 3.0, "bp") * ur ** 1.4
    wr += 0.4 * filt(osc_saw(mtof(57) * 2 ** ur, nr) + osc_saw(mtof(57) * 1.006 * 2 ** ur, nr), ("lp", 3000)) * ur ** 2
    mx.add("music", wr, ml, -16, 0.0, {"music>plate": -6})
    cue(bt(x_m) * FPS + 1, "music", "Montage groove (Dm-Bb-F-C) under the build", "Kick/clap/hat, 16th octave bass and arp on the beat grid")
    cue(E["machine_lights"], "music", "Wake-up build: A pedal opening filter, accelerating snare roll, riser -> hard cut on the button",
        "Rising noise band + octave-gliding saws")

    rr = rng_for("relief")
    rp0, sil = F(E["lean_back"]), F(E["silence_start"])
    x_r = bnext(E["lean_back"])
    rch, rmel = loop_events(x_r, bx(E["silence_start"]))
    for i, (x0, x1, _, _, j) in enumerate(rch):
        t0 = rp0 if i == 0 else bt(x0)
        t1 = sil if i == len(rch) - 1 else bt(x1)
        mx.add("music", saw_pad(RELIEF_PAD[j], t1 - t0, rr, cutoff=1500, attack=1.2 if i == 0 else 0.35, release=0.5), t0, -30, 0.0, {"music>plate": -5})
    off = bt(x_r)
    rep = np.zeros((int((sil - off + 1.5) * SR), 2))
    ep_render(rep, rch, rmel, off, vel=0.48)
    mx.add("music", lofi(rep), off, -16, 0.0, {"music>plate": -10})
    for xb in range(x_r + 2, min(x_r + 6, int(np.floor(bx(E["silence_start"]))))):
        mx.add("music", kick(r, f_hi=120, decay=0.22, click=0.2), bt(xb), -21, 0.0)
        mx.add("music", snare(r, tone=210, decay=0.08, noise=0.5), bt(xb + 0.5), -29, 0.1, {"music>plate": -8})
        for h in (0.25, 0.75):
            mx.add("music", hat(r, decay=0.02), bt(xb + h), -33, 0.3)
    n = int((sil - rp0) * SR)
    mx.add("music", fades(crackle(n, rr, 5.0), 0.5, 0.01), rp0, -48, 0.15)
    cue(E["lean_back"], "music", "Relief: calm Fmaj9 pad, then the Act I lo-fi loop returns with soft drums",
        f"Detuned-saw pad (slow attack); FM EP reprise from beat {x_r}, so ROADMAP OBSOLETE lands on a downbeat")
    cue(E["silence_start"], "all", "NEAR SILENCE: ROADMAP OBSOLETE.",
        "Music, machine hum, bubbles and every reverb tail hard-cut on the frame; room tone dropped ~9 dB")

    # ------------------------------------------------------------------ ACT IV
    log("act IV")
    r = rng_for("act4")
    mx.add("sfx", sfx_clack(r), F(E["laptop_clack"]) - 0.04, -12, -0.1, {"sfx>room": -9})
    cue(E["laptop_clack"], "sfx", "Laptop lid clack", "Air puff before the hit, plastic clack band + 300 Hz body + rattle")
    mx.add("sfx", sfx_cloth(r, F(E["stand_end"]) - F(E["stand_start"]), 0.8), F(E["stand_start"]), -28, 0.0, {"sfx>room": -10})
    mx.add("sfx", sfx_chair_roll(r), F(E["chair_roll"]), -15, -0.3, {"sfx>room": -9})
    cue(E["chair_roll"], "sfx", "Chair creak + caster roll", "Band-passed pink noise with wheel-bump AM, brown rumble, saw creak")
    if E["stretch_end"] - E["stretch_start"] >= 8:          # the stretch is optional in the cut
        mx.add("sfx", sfx_cloth(r, F(E["stretch_end"]) - F(E["stretch_start"]), 1.0), F(E["stretch_start"]), -24, 0.1, {"sfx>room": -10})
    cue(E["stand_start"], "sfx", f"Cloth: standing (to {E['stand_end']}) and hoodie stretch ({E['stretch_start']}-{E['stretch_end']})",
        "Band-passed noise with slow swell + sparse crackle grains")
    for i, f in enumerate(E["steps"]):
        mx.add("sfx", sfx_step(r, creak=(i == 1)), F(f), -13 - i, -0.1 + 0.25 * i, {"sfx>room": -8})
    cue(E["steps"][0], "sfx", f"Footsteps on frames {', '.join(map(str, E['steps']))}", "Heel thump (sine + low noise) + sole scuff; floor creak on step 2")
    b0 = F(E["breath"]) - 0.27
    mx.add("sfx", sfx_breath(r, F(E["whisper_start"]) - b0 - 0.015), b0, -16, 0.0)
    cue(E["breath"], "sfx", "Deep breath in (swells through the breath frame, ends as the whisper starts)", "Swept band-passed noise, high-passed")
    mx.add("sfx", sfx_handle(r), F(E["handle_turn"]), -16, 0.4, {"sfx>room": -9})
    cue(E["handle_turn"], "sfx", "Door handle + latch", "Two resonant metal clicks with partials, tiny spring squeak")
    cr0 = F(E["wall_creak"])
    mx.add("sfx", sfx_creak(r, F(E["walls_land"]) - cr0 - 0.03), cr0, -15, 0.0, {"sfx>room": -6})
    fw0 = F(E["walls_fall_start"])
    mx.add("sfx", sfx_whoosh(r, F(E["walls_land"]) - fw0 + 0.04, 0.92, 120, 900, 0.7, -0.5, 0.5, 0.8), fw0, -14, 0.0)
    cue(E["wall_creak"], "sfx", "Wooden creak as the flats tip, falling-air whoosh", "Jittered stick-slip impulse train through 4 wood resonances; low swept noise")
    mx.add("sfx", sfx_slam(r), F(E["walls_land"]), -4.0, 0.0, {"sfx>hall": -13})
    cue(E["walls_land"], "sfx", "MASSIVE wall slam into the hall", "Four-impact flam (slap + low thud), pitch-dropping 50 Hz sub boom, debris; huge FDN hall")

    # industrial hall ambience
    log("act IV: hall ambience")
    r = rng_for("hall")
    h0, h1 = F(E["walls_land"]), F(E["black"])
    acc = F(E["accelerate"])
    nh = int((h1 - h0) * SR) + 1
    th = tsec(nh) + h0
    belt = np.interp(th, np.arange(len(CH["belt_speed"])) / FPS, CH["belt_speed"])
    rise = smoothstep((th - h0) / 1.2) * (0.6 + 0.7 * smoothstep((th - h0) / max(0.5, acc - h0)))
    up = 2 ** (3 * smoothstep((th - acc) / 0.35) / 12)
    drone = np.zeros((nh, 2))
    for c in range(2):
        for m, a in ((26, 1.0), (33, 0.7), (38, 0.5)):
            for v in (-1, 0, 1):
                drone[:, c] += a * osc_saw(mtof(m) * 2 ** (v * 6 / 1200 + c * 0.0007) * up, nh, r.uniform())
    drone = filt(drone, ("lp", 160, 0.6), ("lp", 220), ("hp", 25))
    drone /= np.max(np.abs(drone))
    imp = np.diff(np.floor(np.cumsum(3.2 * belt) / SR), prepend=0.0)
    kt = np.arange(int(0.03 * SR)) / SR
    kern = (np.sin(TAU * 620 * kt) + 0.6 * np.sin(TAU * 1330 * kt)) * np.exp(-kt / 0.006)
    clack = np.stack([fftconv(imp, kern)[:nh], fftconv(np.roll(imp, 410), kern)[:nh]], 1)
    rumble = svf(colored(nh, r, 2.0), 110 + 26 * belt, 0.8, "lp")
    whine = osc_sin(17 * belt, nh) * 0.25 + 0.1 * osc_sin(34.2 * belt, nh)
    conveyor = (clack * 0.35 + pan2(rumble + whine, 0.0)) * (0.5 + 0.5 * np.clip(belt / 8, 0, 1.5))[:, None]
    air = np.stack([filt(colored(nh, r, 1.0), ("lp", 420)) for _ in range(2)], 1)
    amb = (db(-6) * drone + db(-10) * conveyor + db(-20) * air) * rise[:, None]
    mx.add("amb", fades(amb, 0.03, 0.01), h0, -12, 0.0, {"amb>hall": -6}, fade=False)
    t = h0 + 0.3
    while t < h1 - 0.1:
        mx.add("amb", sfx_clank(r), t, -32, r.uniform(-0.9, 0.9), {"amb>hall": 4})
        t += r.exponential(0.55)
    a_on = np.clip((th - acc) / 0.3, 0, 1)
    nimp = (r.random(nh) < (260 + 520 * a_on) / SR) * r.exponential(1.0, nh)
    kc = filt(white(200, r) * np.exp(-np.arange(200) / SR / 0.0009), ("bp", 2600, 1.0))
    crowd = np.stack([fftconv(nimp, kc)[:nh], fftconv(np.roll(nimp, 977), kc)[:nh]], 1)
    crowd = filt(crowd, ("lp", 5000)) * (smoothstep((th - h0) / 1.0) * (0.5 + 0.8 * a_on))[:, None]
    mx.add("amb", crowd, h0, -30, 0.0, {"amb>hall": 2}, fade=False)
    cue(E["walls_land"], "ambience", "Industrial hall: D/A low drone, conveyor clatter+rumble, distant clanks, crowd typing, air",
        "Detuned saws low-passed at 160 Hz; roller impulses at 3.2*belt_speed Hz through metal resonances (pitches up with the belt); "
        "modal metal clanks; dense random key-click texture; all into a 4.8 s FDN hall; rises to the acceleration")

    # PA announcement (voice stem): chime on pa_start, voice right after, done by pa_end
    log("voice: PA + whisper")
    r = rng_for("pa")
    p1, p2 = voice_src["pa"]
    pf = voice_meta["pa_pitch"]
    raw = (len(p1) + len(p2)) / SR
    gap = float(np.clip(voice_meta["pa_avail"] / pf - raw, 0.06, 0.3))
    n_sp = len(p1) + len(p2) + int(gap * SR)
    sp_ = np.concatenate([np.zeros(2400), p1, np.zeros(int(gap * SR)), p2, np.zeros(2400)])
    sp_ = resample_len(sp_, int(len(sp_) * pf))
    sp_ = fades(sp_[int(2400 * pf):int(2400 * pf) + int(n_sp * pf)], 0.003, 0.01)
    pa_t0 = F(E["pa_start"]) - 0.02
    speech_t = voice_meta["pa_speech_t"]
    chime = np.zeros(int(2.5 * SR))
    for i, (m, dt_) in enumerate(((81, 0.0), (78, PA_CHIME_GAP))):
        b = bell(mtof(m), 0.5, ((1, 1, 1), (3.9, 0.3, 0.3), (9.2, 0.08, 0.1)))
        b *= 1 + 0.15 * np.sin(TAU * 5.0 * tsec(len(b)))
        i0 = int(dt_ * SR)
        chime[i0:i0 + len(b)] += b[:len(chime) - i0] * (1.0 if i == 0 else 0.9)
    chime = fades(chime, 0.0, 0.3)
    total = int((h1 - pa_t0) * SR) + int(0.05 * SR)
    pa = pa_chain(total, [("chime", int(0.02 * SR), chime * 0.5), ("speech", int((speech_t - pa_t0) * SR), sp_)], r)
    mx.add("voice", pa, pa_t0, -9, 0.0, fade=False)
    speech_end = speech_t + len(sp_) / SR
    cue(E["pa_start"], "voice", "Two-tone PA chime (A5 -> F#5)", "Vibraphone-like bell partials with tremolo, through the same PA chain")
    cue(speech_t * FPS + 1, "voice", f"PA: \"{T.PA_LINE}\" (ends frame {speech_end * FPS + 1:.1f}, slot ends {E['pa_end']})",
        f"{VOICE_PA} (SAPI rate {voice_meta['pa_rate']}), pitched down {PA_PITCH_ST} st by resampling, ring-mod + comb robot tint, "
        "300-3500 Hz horn band-pass, tanh clip, ~6.5-bit/16 kHz crush, 5-tap hall echo, 3.4 s FDN hall")

    # whisper (voice stem): dry, intimate, close
    r = rng_for("whisper")
    w1_, w2_ = voice_src["whisper"]
    wgap = float(np.clip(voice_meta["w_avail"] - (len(w1_) + len(w2_)) / SR, 0.1, 0.22))
    wsrc = np.concatenate([w1_, np.zeros(int(wgap * SR)), w2_])
    wh = whisperize(wsrc, voice_meta["w_avail"], r)
    wt0 = F(E["whisper_start"]) + 0.02
    mx.add("voice", wh, wt0, -9, -0.05)
    cue(E["whisper_start"], "voice", f"Whisper: \"{T.WHISPER_LINE}\" (ends frame {(wt0 + len(wh) / SR) * FPS + 1:.1f}, slot ends {E['whisper_end']})",
        f"{VOICE_WHISPER} (SAPI rate {voice_meta['w_rate']}); STFT: cepstral envelope (harmonics removed), whisper EQ, "
        "magnitude time-fit, random phase resynthesis, 300 Hz HP; dry")

    # finish-line choir hint, proud swell (music)
    r = rng_for("choir")
    c0 = F(E["finish_recede_start"])
    ch_ = choir([69, 74, 76, 78], h1 - c0 + 0.01, r)
    env = env_pts(len(ch_), [(0, 0), (F(E["realize"]) - c0, 0.35), (F(E["proud_start"]) - c0, 0.45), (F(E["proud_end"]) - c0, 1.0),
                             (max(F(E["display_flip"]), F(E["proud_end"]) + 0.01) - c0, 0.6), (acc - c0, 0.8), (h1 - c0, 1.0)])
    mx.add("music", ch_ * env[:, None], c0, -9, 0.0, {"music>hall": -2})
    cue(E["finish_recede_start"], "music", "Distant choir 'aah' (D major add9) hinting at the finish line; swells on the proud beat",
        "Vibrato saws through four formant band-passes, mostly hall reverb")

    # alarm riser, acceleration, yank
    r = rng_for("accel")
    df = F(E["display_flip"])
    mx.add("sfx", sfx_riser_alarm(r, acc - df + 0.06), df, -13, 0.0, {"sfx>hall": -6})
    cue(E["display_flip"], "sfx", "Alarm riser (two-tone, rising) into 10X", "Pulse/saw two-tone with exponential pitch rise + swept noise")
    mx.add("sfx", sfx_accel_whoosh(r), acc, -10, 0.0, {"sfx>hall": -6})
    cue(E["accelerate"], "sfx", "Huge acceleration whoosh; conveyor rumble/whine pitch up with belt_speed",
        "Opening low-pass noise sweep, rising saw, sub drop; belt-driven roller rate in the ambience")
    mx.add("sfx", sfx_yank(r), F(E["yank"]) - 0.09, -10, 0.2, {"sfx>hall": -8})
    cue(E["yank"], "sfx", "Chair yank: zip + thud", "Toothed (AM) rising band-pass rasp, then pitch-dropped thud")

    # absurd epic climax (music): chord points derived from the grid between accelerate and black
    log("act IV: climax")
    r = rng_for("climax")
    x_acc, x_blk, x_pb = bx(E["accelerate"]), bx(E["black"]), bx(E["pullback_start"])
    pts = [x_acc] + [float(k) for k in range(int(np.ceil(x_acc + 0.3)), int(np.ceil(x_blk - 0.3)))]
    segs_c = [(a_, b_) for a_, b_ in zip(pts, pts[1:] + [x_blk])]
    if segs_c[-1][1] - segs_c[-1][0] >= 0.75:
        a_, b_ = segs_c.pop()
        segs_c += [(a_, (a_ + b_) / 2), ((a_ + b_) / 2, b_)]
    V = dict(Bb=[34, 46, 53, 58, 62, 65], C=[36, 48, 55, 60, 64, 67], Dm=[38, 50, 57, 62, 65, 69])
    cyc = ["Bb", "C", "Dm"]
    names = [cyc[i % 3] for i in range(len(segs_c) - 2)] + ["Bb", "C"]
    for i, ((x0, x1), nm) in enumerate(zip(segs_c, names)):
        t0 = acc if i == 0 else bt(x0)
        t1 = h1 if i == len(segs_c) - 1 else bt(x1)
        notes = V[nm] + ([70] if i >= len(segs_c) - 2 else [])
        if i == len(segs_c) - 1:                                   # Csus4 -> C on the last chord
            tm = t0 + (t1 - t0) * 0.5
            for nn, ta, tb_ in (([36, 48, 55, 60, 65, 67, 72], t0, tm), ([36, 48, 55, 60, 64, 67, 72], tm, t1)):
                mx.add("music", brass_chord(nn, tb_ - ta + 0.02, r, bright=1.0 + 0.12 * i, attack=0.015, release=0.05), ta, -12.5 + 0.6 * i, 0.0, {"music>hall": -8})
        else:
            mx.add("music", brass_chord(notes, t1 - t0 + 0.02, r, bright=1.0 + 0.12 * i, attack=0.02, release=0.06), t0, -12.5 + 0.6 * i, 0.0, {"music>hall": -8})
    prog_txt = " - ".join(names[:-1]) + " - Csus4/C -> D"
    cue(E["accelerate"], "music", f"ABSURD EPIC climax: {prog_txt} brass saw-stack progression",
        "4 detuned saws/note with pitch scoop, delayed vibrato, per-chord low-pass 'blat' envelope (SVF); chord points on the beat grid")
    hits = sorted(set([round(p, 4) for p in pts] + [float(k) for k in range(int(np.ceil(x_acc)), int(np.ceil(x_blk)))]))
    for xk in hits:
        t0 = acc if abs(xk - x_acc) < 1e-6 else bt(xk)
        if t0 < h1 - 0.02:
            mx.add("music", kick(r, f_hi=130, f_lo=40, decay=0.4, drive=2.2), t0, -9, 0.0, {"music>hall": -12})
            mx.add("music", tom(r, 72, 0.5, 0.8), t0, -12, 0.0, {"music>hall": -6})
    x_roll = max(x_pb + 0.75, x_blk - 1.25)
    for xs in np.arange(np.floor(x_acc) + 0.5, x_roll, 1.0):
        if xs > x_acc + 0.1:
            mx.add("music", snare(r, decay=0.2), bt(xs), -12, 0.0, {"music>hall": -6})
    x = np.ceil(x_pb * 8) / 8
    while x < min(x_pb + 0.75, x_roll):
        u = (x - x_pb) / 0.75
        mx.add("music", tom(r, 125 - 50 * u, 0.3), bt(x), -14, -0.5 + u, {"music>hall": -8})
        x += 0.125
    t, tr0 = bt(x_roll), bt(x_roll)
    while t < h1 - 0.006:
        u = (t - tr0) / (h1 - tr0)
        mx.add("music", snare(r, decay=0.06), t, -21 + 11 * u, 0.0, {"music>hall": -10})
        t += (bt(x_roll + 0.25) - tr0) / (2 if u < 0.5 else 4)
    for tc in (acc, F(E["pullback_start"])):
        mx.add("music", crash(r, 1.5), tc, -13, 0.0, {"music>hall": -8})
    rc0 = bt(max(x_acc + 0.5, x_blk - 1.0))
    rc = crash(r, 1.4, length=h1 - rc0)[::-1]
    mx.add("music_final", rc * np.linspace(0, 1, len(rc))[:, None] ** 2, rc0, -13, 0.0)
    x = pts[1] if len(pts) > 1 else x_acc
    while bt(x) < h1 - 0.01:
        d = bt(x + 0.125) - bt(x)
        mx.add("music", filt(bass_note((38, 50)[int(round(x * 8)) % 2], d * 0.8, r), ("lp", 3000)), bt(x), -15, 0.0)
        x += 0.125
    cue(E["pullback_start"], "music", "Drums build: kick+taiko on the chord points/beats, tom run from the pull-back, snare roll crescendo, reverse crash into black",
        "Synth drums (sine pitch envelopes + filtered noise), reversed crash swell, 32nd octave bass ostinato; 75 ms -12 dB suck-out before black")

    # final hit (bypasses the cut-to-black gate)
    log("final hit")
    r = rng_for("final")
    tb = F(E["black"])
    n = int(3.0 * SR)
    t = tsec(n)
    chord = np.zeros((n, 2))
    for m in (38, 50, 57, 62, 66, 69, 74, 78, 81):
        for v in range(7):
            chord += pan2(osc_saw(mtof(m) * 2 ** ((v - 3) / 3 * 22 / 1200), n, r.uniform()), np.clip((v - 3) / 3 * 0.8, -0.9, 0.9))
    chord /= np.sqrt(9 * 7)
    chord = svf(chord, 900 + 9000 * np.exp(-t / 0.35), 0.8, "lp") * env_perc(n, 0.004, 0.75)[:, None]
    boom = osc_sin(55 * (1 + 0.9 * np.exp(-t / 0.06)) * (1 - 0.45 * (1 - np.exp(-t / 0.6))), n) * env_perc(n, 0.002, 0.8)
    hit = chord + pan2(1.3 * np.tanh(2.0 * boom), 0.0) + 0.55 * crash(r, 1.6, length=3.0)
    hit += pan2(filt(white(n, r), ("lp", 2500)) * env_perc(n, 0.0005, 0.05), 0.0) * 0.6
    hit = fades(hit, 0.0005, 0.3)
    wet = reverb(hit, t60=2.2, size=1.4, damp=0.35, predelay=0.02, seed=77)
    mx.add("music_final", hit + wet * db(-4), tb, -4, 0.0, fade=False)
    cue(E["black"], "music", "FINAL HIT on the cut to black: sub boom + bright detuned D major + noise crash",
        "9-note x 7-voice supersaw (+/-22 cents) with closing low-pass, 55->28 Hz sub, crash; own 2.2 s FDN tail, faded to digital silence")
    mx.add("sfx_final", sfx_beta_blip(rng_for("beta")), F(E["subtitle"]), -16, 0.0)
    cue(E["subtitle"], "sfx", "'Beta' glitch blip under HUMANITY: STILL IN BETA.", "Stuttered square chirps, sample-and-hold + 4-bit quantiser")
    return dict(speech_t=speech_t, speech_end=speech_end, whisper_t=wt0, whisper_end=wt0 + len(wh) / SR)


# =============================================================================
# 8. Mixdown, mastering, metering
# =============================================================================
def gate_env(off, fade=0.004):
    """1 everywhere except the (t0, t1) windows (seconds, t1=None: to the end),
    with raised-cosine ramps that *finish* at t0 and *start* at t1."""
    g = np.ones(N)
    fl = int(fade * SR)
    for t0, t1 in off:
        a = int(round(t0 * SR))
        b = N if t1 is None else int(round(t1 * SR))
        g[a:b] = 0.0
        i0 = max(0, a - fl)
        g[i0:a] *= 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, a - i0))
        if b < N:
            i1 = min(N, b + fl)
            g[b:i1] *= 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, i1 - b))
    return g


def rev_bus(mx, name, **kw):
    if name not in mx.b:
        return np.zeros((N, 2))
    x = mx.b.pop(name)
    nz = np.flatnonzero(np.abs(x).max(1) > 1e-10)
    if len(nz) == 0:
        return np.zeros((N, 2))
    a, b = nz[0], min(N, nz[-1] + int(kw["t60"] * 1.2 * SR))
    out = np.zeros((N, 2))
    out[a:b] = reverb(x[a:b], **kw)
    return out


def k_weight(x):
    b1, a1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
    b2, a2 = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]
    return filt(x, ("ba", b1, a1), ("ba", b2, a2))


def lufs_blocks(x, win=0.4, hop=0.1):
    y = k_weight(x)
    p = (y ** 2).sum(1)
    c = np.concatenate([[0.0], np.cumsum(p)])
    w, h = int(win * SR), int(hop * SR)
    starts = np.arange(0, len(p) - w + 1, h)
    return (c[starts + w] - c[starts]) / w, starts


def integrated_lufs(x):
    ms, _ = lufs_blocks(x)
    lk = -0.691 + 10 * np.log10(ms + 1e-20)
    g1 = ms[lk > -70.0]
    rel = -0.691 + 10 * np.log10(g1.mean()) - 10.0
    g2 = ms[(lk > -70.0) & (lk > rel)]
    return -0.691 + 10 * np.log10(g2.mean())


def _minfilt(a, w):
    """Sliding minimum, centred window w (odd), van Herk/Gil-Werman, O(n)."""
    pad = w // 2
    n = len(a)
    tot = n + 2 * pad
    tot2 = int(np.ceil(tot / w)) * w
    ap = np.concatenate([np.ones(pad), a, np.ones(tot2 - n - pad)])
    blk = ap.reshape(-1, w)
    pre = np.minimum.accumulate(blk, axis=1).ravel()
    suf = np.minimum.accumulate(blk[:, ::-1], axis=1)[:, ::-1].ravel()
    return np.minimum(suf[:n], pre[w - 1:w - 1 + n])


def limiter_gain(x, ceiling_db, look=0.003, release=0.12):
    """Look-ahead peak limiter gain curve: windowed-minimum of the required
    gain, smoothed by a moving average no wider than the look-ahead (never
    overshoots), then a program-dependent exponential release."""
    c = db(ceiling_db)
    pk = np.max(np.abs(x), axis=1)
    taps, os_ = 32, 4                       # also detect 4x-oversampled (inter-sample) peaks
    tt = np.arange(-taps * os_ // 2, taps * os_ // 2) / os_
    h = np.sinc(tt) * np.kaiser(len(tt), 8.0)
    for ch in range(x.shape[1]):
        for p in range(1, os_):
            pk = np.maximum(pk, np.abs(np.convolve(x[:, ch], h[p::os_], "same")))
    req = np.minimum(1.0, c / np.maximum(pk, 1e-12))
    W = int(look * SR) | 1
    m = _minfilt(req, 2 * W + 1)
    k = np.ones(W) / W
    s = np.convolve(np.concatenate([np.full(W, m[0]), m, np.full(W, m[-1])]), k, "same")[W:W + len(m)]
    s = np.minimum(s, req)
    if s.min() >= 1.0:
        return s
    rel = 1.0 - np.exp(-1.0 / (release * SR))
    g = s.tolist()
    cur = 1.0
    for i, v in enumerate(g):
        cur = cur + (1.0 - cur) * rel
        if v < cur:
            cur = v
        g[i] = cur
    return np.array(g)


def true_peak_db(x, os_=4, taps=32):
    """4x oversampled peak via a polyphase windowed-sinc interpolator."""
    t = np.arange(-taps * os_ // 2, taps * os_ // 2) / os_
    h = np.sinc(t) * np.kaiser(len(t), 8.0)
    pk = 0.0
    for c in range(x.shape[1]):
        for p in range(os_):
            pk = max(pk, np.max(np.abs(np.convolve(x[:, c], h[p::os_], "same"))))
    return 20 * np.log10(pk + 1e-12)


def write_wav(path, x, rng):
    """16-bit PCM with TPDF dither (digital silence stays exactly zero)."""
    y = x * 32767.0
    d = (rng.random(y.shape) - rng.random(y.shape))
    y = np.where(np.abs(x) < 2e-8, 0.0, y + d)   # FFT round-off below -150 dBFS stays digital zero
    q = np.clip(np.round(y), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(q.tobytes())
    return q


def mixdown(mx):
    log("reverbs")
    room = dict(t60=0.5, size=0.32, damp=0.45, predelay=0.004, seed=5)
    music = mx.b.pop("music") + rev_bus(mx, "music>plate", t60=1.7, size=0.75, damp=0.3, predelay=0.012, seed=7) \
        + rev_bus(mx, "music>hall", t60=3.6, size=1.6, damp=0.35, predelay=0.03, seed=9)
    sfx_a2 = mx.b.pop("sfx_a2") + rev_bus(mx, "sfx_a2>room", **room)
    sfx_a3 = mx.b.pop("sfx_a3") + rev_bus(mx, "sfx_a3>room", **room)
    sfx = mx.b.pop("sfx") + rev_bus(mx, "sfx>room", **room) + rev_bus(mx, "sfx>hall", t60=4.0, size=1.9, damp=0.4, predelay=0.04, seed=13)
    amb = mx.b.pop("amb") + rev_bus(mx, "amb>hall", t60=4.8, size=1.9, damp=0.4, predelay=0.04, seed=17)
    voice = mx.b.pop("voice")
    hp = lambda a: filt(a, ("hp", 22.0, 0.7071), pad=0.5)  # noqa: E731  DC/subsonic removal *before* the gates
    music, sfx_a2, sfx_a3, sfx, amb, voice = (hp(a) for a in (music, sfx_a2, sfx_a3, sfx, amb, voice))
    log("gates")
    black = F(E["black"])
    so = np.ones(N)                                    # 75 ms pre-hit suck-out (-12 dB) so the final hit lands
    a_, b_, r_ = int((black - 0.075) * SR), int(black * SR), int(0.025 * SR)
    so[a_:b_] = db(-12)
    so[a_:a_ + r_] = np.linspace(1.0, db(-12), r_)
    g_music = gate_env([(F(E["notif_do_that"]), F(E["notif_better"])), (F(E["scream_end"] + 1), bt(np.ceil(beat_at(F(E["build_start"])) - 0.15)) - 0.004),
                        (F(E["button_press"]), F(E["lean_back"])), (F(E["silence_start"]), F(E["walls_land"])),
                        (black, None)], 0.003)
    music = music * (g_music * so)[:, None] + hp(mx.b.pop("music_final"))
    sfx = (sfx_a2 * gate_env([(F(E["notif_do_that"]), None)], 0.003)[:, None]
           + sfx_a3 * gate_env([(F(E["silence_start"]), None)], 0.003)[:, None]
           + sfx * (gate_env([(black, None)], 0.003) * so)[:, None] + hp(mx.b.pop("sfx_final")))
    amb = amb * (gate_env([(black, None)], 0.003) * so)[:, None]
    voice = voice * (gate_env([(black, None)], 0.003) * so)[:, None]
    stems = dict(music=music, sfx=sfx, ambience=amb, voice=voice)
    # end decisively: fade the final tail, then exact digital silence
    fe1 = int(F(T.FRAME_END - 4) * SR)               # the last ~4 frames are digital silence
    fe0 = min(fe1 - int(0.3 * SR), int((F(E["subtitle"]) + 0.45) * SR))
    tail = np.ones(N)
    tail[fe0:fe1] = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, fe1 - fe0))
    tail[fe1:] = 0.0
    for k in stems:
        stems[k] *= tail[:, None]
    mix = sum(stems.values())
    log("master: loudness + limiter")
    gain = TARGET_LUFS - integrated_lufs(mix)
    for _ in range(6):
        lg = limiter_gain(mix * db(gain), CEILING_DB - 0.05)
        L = integrated_lufs(mix * (db(gain) * lg)[:, None])
        if abs(L - TARGET_LUFS) < 0.1:
            break
        gain += TARGET_LUFS - L
    master = db(gain) * lg
    out = mix * master[:, None]
    red = -20 * np.log10(lg)
    fr = red[:N // SPF * SPF].reshape(-1, SPF).max(1)
    busy = [i + 1 for i in np.flatnonzero(fr > 3.0)]
    lim = dict(pct_over_1db=100.0 * np.mean(red > 1.0), pct_over_3db=100.0 * np.mean(red > 3.0),
               max_at_frame=int(np.argmax(red) // SPF + 1), frames_over_3db=busy)
    stems = {k: v * master[:, None] for k, v in stems.items()}
    return out, stems, dict(gain_db=gain, min_gain_db=20 * np.log10(lg.min()), limiter=lim)


def analyse(mix, events):
    rms = lambda a: 20 * np.log10(np.sqrt(np.mean(a ** 2)) + 1e-12)  # noqa: E731
    st = {}
    st["frames"] = len(mix)
    st["peak_dbfs"] = 20 * np.log10(np.max(np.abs(mix)) + 1e-12)
    st["true_peak_dbtp"] = true_peak_db(mix)
    st["lufs_i"] = integrated_lufs(mix)
    st["dc"] = mix.mean(0).tolist()
    st["per_second_rms"] = [rms(mix[i * SR:(i + 1) * SR]) for i in range(30)]
    ms, starts = lufs_blocks(mix, 3.0, 1.0)
    st["short_term_lufs"] = [(-0.691 + 10 * np.log10(m + 1e-20)) for m in ms]

    def win(f0, f1):
        return mix[int(F(f0) * SR):int(F(f1) * SR)]
    st["dead_stop_rms"] = rms(win(E["notif_do_that"] + 1, E["notif_better"]))
    st["dead_stop_rms_excl_ding"] = rms(win(E["notif_do_that"] + 14, E["notif_better"]))
    st["silence_rms"] = rms(win(E["silence_start"], E["close_laptop"]))
    st["silence_peak_dbfs"] = 20 * np.log10(np.max(np.abs(win(E["silence_start"], E["close_laptop"]))) + 1e-12)
    st["tail_zero_from_sample"] = int(np.flatnonzero(np.abs(mix).max(1) > 0)[-1]) + 1
    st.update(events)
    return st


def overview_png(path, mix, stems):
    from PIL import Image, ImageDraw, ImageFont
    W, PADL, PADR = 1900, 70, 20
    H_WAV, H_SPEC, H_RMS, H_LAB = 180, 300, 170, 120
    H = H_LAB + H_WAV + H_SPEC + H_RMS + 40
    img = Image.new("RGB", (W, H), (14, 15, 20))
    dr = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=12)
    except TypeError:
        font = ImageFont.load_default()
    pw = W - PADL - PADR
    x_of = lambda t: PADL + t / 30.0 * pw  # noqa: E731
    mono = mix.mean(1)
    # waveform
    y0 = H_LAB
    cols = np.array_split(mono, pw)
    mid = y0 + H_WAV / 2
    for i, c in enumerate(cols):
        lo, hi = c.min(), c.max()
        dr.line([(PADL + i, mid - hi * H_WAV / 2), (PADL + i, mid - lo * H_WAV / 2)], fill=(120, 190, 255))
    dr.text((6, y0 + 4), "waveform", fill=(200, 200, 200), font=font)
    # spectrogram (log-frequency)
    y1 = y0 + H_WAV + 10
    nfft, hop = 2048, 480
    win = np.hanning(nfft)
    nfr = (len(mono) - nfft) // hop
    idx = np.arange(nfft)[None, :] + hop * np.arange(nfr)[:, None]
    spec = np.abs(np.fft.rfft(mono[idx] * win, axis=1)) / (win.sum() / 2)
    spec_db = 20 * np.log10(spec + 1e-9)
    freqs = np.fft.rfftfreq(nfft, 1.0 / SR)
    rows = np.geomspace(30, 20000, H_SPEC)[::-1]
    bins = np.clip(np.searchsorted(freqs, rows), 0, len(freqs) - 1)
    colsel = np.linspace(0, nfr - 1, pw).astype(int)
    S_ = spec_db[colsel][:, bins].T
    v = np.clip((S_ + 110) / 95, 0, 1)
    stops = np.array([[0, 0, 4], [59, 15, 112], [140, 41, 129], [222, 73, 104], [254, 159, 109], [252, 253, 191]], float)
    pos = np.linspace(0, 1, len(stops))
    rgb = np.stack([np.interp(v, pos, stops[:, k]) for k in range(3)], -1).astype(np.uint8)
    img.paste(Image.fromarray(rgb), (PADL, y1))
    for f in (100, 1000, 10000):
        yy = y1 + int(np.searchsorted(-rows, -f))
        dr.text((6, yy - 6), f"{f // 1000}k" if f >= 1000 else f"{f}", fill=(200, 200, 200), font=font)
    dr.text((6, y1 + 4), "spec", fill=(200, 200, 200), font=font)
    # per-frame RMS of mix + stems
    y2 = y1 + H_SPEC + 10
    colors = dict(mix=(255, 255, 255), music=(255, 170, 60), sfx=(90, 220, 140), ambience=(150, 150, 255), voice=(255, 90, 160))
    for name, sig in [("mix", mix)] + list(stems.items()):
        m = sig.mean(1).reshape(-1, SPF)
        r = 20 * np.log10(np.sqrt((m ** 2).mean(1)) + 1e-9)
        pts = [(x_of(i / FPS), y2 + H_RMS * (1 - (np.clip(v_, -80, 0) + 80) / 80)) for i, v_ in enumerate(r)]
        dr.line(pts, fill=colors[name], width=2 if name == "mix" else 1)
    for d in (-20, -40, -60):
        yy = y2 + H_RMS * (1 - (d + 80) / 80)
        dr.line([(PADL, yy), (W - PADR, yy)], fill=(50, 50, 60))
        dr.text((6, yy - 6), f"{d} dB", fill=(160, 160, 160), font=font)
    lx = W - PADR - 380
    for i, (k, c) in enumerate(colors.items()):
        dr.text((lx + i * 75, y2 + 2), k, fill=c, font=font)
    # markers
    marks = [("notif1", E["notif1"]), ("notif3", E["notif3"]), ("typing", E["typing_start"]), ("16x", E["tutorial_16x"]),
             ("DO THAT (stop)", E["notif_do_that"]), ("BETTER stab", E["notif_better"]), ("idea", E["idea"]),
             ("build", E["build_start"]), ("BUTTON", E["button_press"]), ("lean", E["lean_back"]), ("print", E["print_start"]),
             ("OBSOLETE (silence)", E["silence_start"]), ("clack", E["laptop_clack"]), ("whisper", E["whisper_start"]),
             ("WALLS", E["walls_land"]), ("PA", E["pa_start"]), ("10X", E["accelerate"]), ("BLACK", E["black"]),
             ("beta", E["subtitle"])]
    for i, (lab, f) in enumerate(marks):
        xx = x_of(F(f))
        dr.line([(xx, H_LAB - 8), (xx, H - 30)], fill=(255, 255, 255) if "(" in lab or lab.isupper() else (110, 110, 120))
        dr.text((xx + 2, 6 + (i % 7) * 15), f"{lab} {f}", fill=(255, 230, 120), font=font)
    for s_ in range(31):
        xx = x_of(s_)
        dr.line([(xx, H - 30), (xx, H - 24)], fill=(180, 180, 180))
        if s_ % 2 == 0:
            dr.text((xx - 6, H - 20), f"{s_}s", fill=(180, 180, 180), font=font)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    img.save(path)


def write_readme(stats, man, extra):
    def tc(t):
        return f"{int(t // 60):02d}:{t % 60:06.3f}"
    lines = []
    A = lines.append
    A("# SKILL ISSUE: soundtrack")
    A("")
    A("Original, fully procedural soundtrack: music, sound effects and ambience are synthesised from scratch in")
    A("`scripts/generate_audio.py` (numpy + the standard-library `wave` module only). No samples, loops, sound")
    A("libraries or downloads are used, and the music is composed for this film (no existing melodies).")
    A("The two voice lines come from Windows' built-in offline speech synthesiser (see the disclosure below).")
    A("")
    A("## Files")
    A("")
    A("| File | Content |")
    A("|---|---|")
    A("| `skill_issue_mix.wav` | Final mix: 48 kHz, 16-bit, stereo, exactly 1,440,000 samples (30.000 s = frames 1-720 at 24 fps) |")
    A("| `stems/music.wav` | Score: lo-fi loop, rhythm layers, stab, montage, relief, choir, climax, final hit |")
    A("| `stems/sfx.wav` | Foley and UI sounds, with their room/hall reverb |")
    A("| `stems/ambience.wav` | Bedroom room tone, then the industrial hall |")
    A("| `stems/voice.wav` | Whisper + PA chime and announcement |")
    A("| `source/*.wav`, `source/tts_manifest.json` | Cached raw TTS renders (so the mix rebuilds without the TTS engine) |")
    A("")
    A("The stems use the same master gain and limiter gain curve as the mix, so they sum back to it")
    A("(within 16-bit dither).")
    A("")
    A("## Regenerate")
    A("")
    A("```")
    A("python scripts/generate_audio.py              # uses the cached TTS in audio/source/")
    A("python scripts/generate_audio.py --retts      # re-synthesise the voice lines (Windows only)")
    A("python scripts/generate_audio.py --overview overview.png   # also draw waveform/spectrogram/levels")
    A("```")
    A("")
    A("Requirements: Python 3.11, numpy (Pillow only for `--overview`). Every random choice is seeded, so the")
    A("output is deterministic. All timing is read from `scripts/skill_issue/timeline.py` (`E`, `NOTIFICATIONS`,")
    A("`SPAWN_LAND_OFFSET`, `PA_LINE`, `WHISPER_LINE`) and `scripts/skill_issue/speed.py` (`compute()`: speed curve,")
    A("beat grid, hero key presses, book/cup/paper/toast spawns, belt speed). Change the timeline, re-run, and")
    A("sound stays in sync. Frame *f* starts at (f-1)/24 s = sample (f-1)*2000.")
    A("")
    A("## Disclosure: synthetic voice (TTS)")
    A("")
    A(f"- Engine: {man.get('engine', 'Windows System.Speech (SAPI 5)')}. Offline; nothing is sent anywhere.")
    A(f"- PA line \"{T.PA_LINE}\": **{man['pa']['voice']}**, rate {man['pa']['rate']}, each sentence rendered")
    A(f"  separately and joined, pitched down {PA_PITCH_ST:g} semitone, then processed into a distorted industrial PA.")
    A(f"- Whisper \"{T.WHISPER_LINE}\": **{man['whisper']['voice']}**, rate {man['whisper']['rate']}, converted into")
    A("  a whisper by STFT processing (cepstral spectral envelope + random-phase resynthesis).")
    A("- No human voice recordings and no cloned voices are used.")
    A("")
    A("## Mix stats")
    A("")
    A(f"- Length: {stats['frames']:,} samples at 48 kHz ({stats['frames'] / SR:.3f} s)")
    A(f"- Integrated loudness: {stats['lufs_i']:.1f} LUFS (ITU-R BS.1770 K-weighted, gated); sample peak "
      f"{stats['peak_dbfs']:.2f} dBFS; true peak ~{stats['true_peak_dbtp']:.2f} dBTP")
    A(f"- Dead stop (frames {E['notif_do_that'] + 1}-{E['notif_better'] - 1}): {stats['dead_stop_rms']:.1f} dBFS RMS "
      f"({stats['dead_stop_rms_excl_ding']:.1f} dBFS after the soft ding)")
    A(f"- Near silence (frames {E['silence_start']}-{E['close_laptop'] - 1}): {stats['silence_rms']:.1f} dBFS RMS, "
      f"peak {stats['silence_peak_dbfs']:.1f} dBFS")
    A(f"- Limiter: max {-stats['min_gain_db']:.1f} dB of gain reduction (frame {stats['limiter']['max_at_frame']}), "
      f"{stats['limiter']['pct_over_3db']:.1f}% of samples above 3 dB (climax drum transients and the final hit)")
    A(f"- Digital silence from sample {stats['tail_zero_from_sample']:,} "
      f"(frame {stats['tail_zero_from_sample'] / SPF + 1:.0f}) to the end")
    A("")
    A("Per-second level of the final mix (RMS dBFS, and short-term loudness over the 3 s ending at that second):")
    A("")
    A("| Second | Frames | RMS dBFS | Short-term LUFS |")
    A("|---|---|---|---|")
    for i, v in enumerate(stats["per_second_rms"]):
        stl = f"{stats['short_term_lufs'][i - 2]:.1f}" if i >= 2 else "-"
        A(f"| {i}-{i + 1} | {i * FPS + 1}-{(i + 1) * FPS} | {v:.1f} | {stl} |")
    A("")
    A("## Cue sheet")
    A("")
    A("Times are from the start of the film (frame 1 = 00:00.000). Stem = where the sound lives.")
    A("")
    A("| Time | Frame | Stem | Sound | How it was synthesised |")
    A("|---|---|---|---|---|")
    for f, stem, sound, how in sorted(CUES, key=lambda c: c[0]):
        fr = f"{f:.0f}" if abs(f - round(f)) < 1e-6 else f"{f:.1f}"
        A(f"| {tc(F(f))} | {fr} | {stem} | {sound} | {how} |")
    A("")
    A("## Sound arc (how the jokes are supported)")
    A("")
    A("- **Act I** quiet bedroom: room tone, a slow clock, pen scratches, a warm lo-fi loop, pleasant dings. The")
    A("  third notification is an alarm and the loop sags (tape droop) while the smile dies.")
    A("- **Act II** the beat grid comes from the speed curve (84 -> 173 bpm). Kick, octave bass, hats, claps and an")
    A("  arp enter as speed rises, and the low-pass opens with it. Keys, whooshes, books, cups, papers, toasts,")
    A("  fast-forward chatter and a racing clock are layered on top. At AI CAN NOW DO THAT everything is gated to")
    A("  nothing on the exact frame, leaving a dry soft ding and three faint ticks; the stab breaks it.")
    A("- **Act III** mechanical montage, a chunky button, machine hum, relief pad and the lo-fi loop reprised, so")
    A("  ROADMAP OBSOLETE can cut it all to near silence on the downbeat.")
    A("- **Act IV** close, dry foley and a whisper, then the slam opens a huge hall. The PA congratulates him, the")
    A("  belt accelerates, the brass progression builds, and one final hit lands on black. The tail is faded to digital")
    A("  silence before the last frames.")
    A("")
    with open(os.path.join(AUDIO, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _ranges(fs):
    out, start, prev = [], None, None
    for f in fs:
        if start is None:
            start = prev = f
        elif f == prev + 1:
            prev = f
        else:
            out.append(f"{start}-{prev}" if prev > start else f"{start}")
            start = prev = f
    if start is not None:
        out.append(f"{start}-{prev}" if prev > start else f"{start}")
    return ", ".join(out) or "none"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--retts", action="store_true", help="re-run the Windows TTS instead of using audio/source/")
    ap.add_argument("--overview", help="write a waveform/spectrogram PNG with event markers to this path")
    args = ap.parse_args()
    os.makedirs(STEMS, exist_ok=True)
    voice_src, man, vmeta = get_voice_sources(args.retts)
    vmeta["pa_rate"] = man["pa"]["rate"]
    vmeta["w_rate"] = man["whisper"]["rate"]
    mx = Mix()
    ev = score(mx, voice_src, vmeta)
    mix, stems, mst = mixdown(mx)
    log("writing wavs")
    r = rng_for("dither")
    q = write_wav(os.path.join(AUDIO, "skill_issue_mix.wav"), mix, r)
    for k, v in stems.items():
        write_wav(os.path.join(STEMS, f"{k}.wav"), v, r)
    mix_q = q.astype(float) / 32767.0
    stats = analyse(mix_q, ev)
    stats.update(mst)
    write_readme(stats, man, vmeta)
    if args.overview:
        overview_png(args.overview, mix_q, stems)
        log(f"overview -> {args.overview}")
    # ---- report
    print()
    print(f"mix: {stats['frames']:,} frames @ {SR} Hz  ({stats['frames'] / SR:.3f} s)")
    print(f"integrated loudness {stats['lufs_i']:.2f} LUFS | sample peak {stats['peak_dbfs']:.2f} dBFS | "
          f"true peak {stats['true_peak_dbtp']:.2f} dBTP | DC {stats['dc'][0]:.2e} {stats['dc'][1]:.2e}")
    lm = stats["limiter"]
    print(f"master gain {stats['gain_db']:+.1f} dB, max limiter reduction {stats['min_gain_db']:.1f} dB at frame {lm['max_at_frame']}; "
          f"{lm['pct_over_1db']:.1f}% of samples >1 dB, {lm['pct_over_3db']:.2f}% >3 dB")
    print("frames with >3 dB limiting:", _ranges(lm["frames_over_3db"]))
    print(f"dead stop RMS ({E['notif_do_that'] + 1}-{E['notif_better'] - 1}): {stats['dead_stop_rms']:.1f} dBFS "
          f"(after ding: {stats['dead_stop_rms_excl_ding']:.1f})")
    print(f"near-silence RMS ({E['silence_start']}-{E['close_laptop'] - 1}): {stats['silence_rms']:.1f} dBFS, "
          f"peak {stats['silence_peak_dbfs']:.1f}")
    print(f"PA speech {stats['speech_t'] * FPS + 1:.1f} -> {stats['speech_end'] * FPS + 1:.1f} (slot {E['pa_start']}-{E['pa_end']}); "
          f"whisper {stats['whisper_t'] * FPS + 1:.1f} -> {stats['whisper_end'] * FPS + 1:.1f} (slot {E['whisper_start']}-{E['whisper_end']})")
    print(f"digital silence from sample {stats['tail_zero_from_sample']:,} (frame {stats['tail_zero_from_sample'] / SPF + 1:.1f})")
    print("per-second RMS (dBFS) | short-term LUFS (3 s window ending at that second):")
    for i, v in enumerate(stats["per_second_rms"]):
        stl = stats["short_term_lufs"][i - 2] if i >= 2 else float("nan")
        print(f"  {i:2d}-{i + 1:2d}s  frames {i * 24 + 1:3d}-{i * 24 + 24:3d}  {v:7.1f}   {stl:7.1f}")
    log("done")


if __name__ == "__main__":
    main()
