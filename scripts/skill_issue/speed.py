"""The SPEED system: one normalised speed curve drives the whole film.

`speed(f)` is a 0..1 value with four phases: a slow opening, an escalating
middle, dead stops on punchlines, and an explosive ending.  Every procedural
channel is derived from it with its own response curve, lag and offset, so
the typing, the clock, the spawning clutter, the conveyor belts, the camera
shake, the monitor light pulses and the music tempo all accelerate together
without moving in lockstep.

Pure Python + deterministic seeds: Blender, the screen generator and the
audio synthesiser call `compute()` and get identical numbers.
"""

import math
import random

from . import timeline as T

SEED = 7_2024  # global seed for every random decision derived here

# (frame, value, interpolation into this key) ; "smooth" | "linear" | "step"
SPEED_KEYS = [
    (1,   0.04, "smooth"),
    (91,  0.05, "smooth"),
    (94,  0.10, "step"),     # notification 1 jolt
    (104, 0.14, "smooth"),
    (115, 0.20, "smooth"),
    (138, 0.16, "smooth"),
    (156, 0.20, "smooth"),
    (176, 0.40, "smooth"),   # typing takes off
    (208, 0.62, "smooth"),
    (223, 0.86, "smooth"),   # 16x
    (241, 0.92, "smooth"),
    (245, 0.00, "linear"),   # AI CAN NOW DO THAT FOR YOU -> dead stop
    (284, 0.00, "linear"),
    (286, 0.97, "step"),     # NEW MODEL. BETTER AT EVERYTHING.
    (310, 1.00, "smooth"),
    (312, 0.45, "linear"),   # the idea
    (320, 0.80, "smooth"),   # frantic build
    (348, 0.82, "smooth"),
    (363, 0.70, "smooth"),   # BUTTON
    (377, 0.18, "smooth"),   # relief
    (399, 0.10, "smooth"),
    (420, 0.30, "smooth"),   # scrolling
    (432, 0.50, "smooth"),
    (468, 0.40, "smooth"),
    (493, 0.15, "smooth"),
    (495, 0.00, "step"),     # ROADMAP OBSOLETE -> silence
    (530, 0.00, "linear"),
    (534, 0.02, "smooth"),
    (586, 0.03, "smooth"),
    (606, 0.20, "smooth"),   # walls down, the system is visible
    (632, 0.32, "smooth"),
    (644, 0.36, "smooth"),
    (648, 1.00, "linear"),   # 10X FASTER
    (674, 1.00, "smooth"),
    (675, 0.00, "step"),     # black
    (720, 0.00, "linear"),
]


def _smoothstep(t):
    return t * t * (3.0 - 2.0 * t)


def speed(f):
    keys = SPEED_KEYS
    if f <= keys[0][0]:
        return keys[0][1]
    for (f0, v0, _), (f1, v1, mode) in zip(keys, keys[1:]):
        if f0 <= f <= f1:
            if mode == "step":
                return v1 if f >= f1 else v0
            t = (f - f0) / max(1e-9, (f1 - f0))
            if mode == "smooth":
                t = _smoothstep(t)
            return v0 + (v1 - v0) * t
    return keys[-1][1]


def _in(f, a, b):
    return a <= f <= b


def compute():
    """Return a dict of per-frame channels (index 0 == frame 1) and events."""
    rng = random.Random(SEED)
    E = T.E
    frames = list(range(T.FRAME_START, T.FRAME_END + 1))
    ch = {k: [] for k in (
        "speed", "typing_rate", "typing_phase", "typing_active",
        "crowd_typing_phase", "clock_minutes", "stress", "cam_intensity",
        "light_pulse", "belt_speed", "belt_distance", "finish_gap",
        "tempo_bpm", "beat_phase", "music_level")}
    events = {"beats": [], "books": [], "cups": [], "papers": [], "toasts": [],
              "keys": []}

    typing_phase = 0.0
    crowd_phase = 0.0
    clock = 21 * 60.0          # 9:00 PM, in minutes
    stress = 0.0
    cam = 0.0
    belt_dist = 0.0
    gap = 70.0                 # metres between our hero and the CAUGHT UP line
    beat = 0.0
    acc = dict(books=0.0, cups=0.0, papers=0.0, toasts=0.0)
    notif_frames = [n["frame"] for n in T.NOTIFICATIONS]

    for f in frames:
        s = speed(f)
        ch["speed"].append(s)

        # -- Hero typing: frequency grows super-linearly with speed ----------
        active = 1.0 if (_in(f, E["typing_start"], E["typing_stop"]) or
                         _in(f, E["build_start"], E["build_end"]) or
                         f >= E["yank"] + 2 and f < E["black"]) else 0.0
        rate = 2.0 + 15.0 * (s ** 1.35)                    # taps per second
        typing_phase += active * rate / T.FPS
        ch["typing_rate"].append(rate * active)
        ch["typing_phase"].append(typing_phase)
        ch["typing_active"].append(active)
        if active and int(typing_phase * 2) != int((typing_phase - rate / T.FPS) * 2):
            events["keys"].append(dict(frame=f, rate=rate))

        # -- Crowd typing: lags behind, flatter response, always on in Act IV --
        crowd_rate = 3.0 + 9.0 * (s ** 1.1) + (14.0 if f >= E["accelerate"] else 0.0)
        crowd_phase += crowd_rate / T.FPS
        ch["crowd_typing_phase"].append(crowd_phase)

        # -- Clock: real time when calm, hours per second when frantic -------
        if f < E["black"]:
            clock += 1.0 / (60 * T.FPS) + 16.0 * (s ** 2.6) * (1.0 if f < E["close_laptop"] else 0.0)
        ch["clock_minutes"].append(clock)

        # -- Stress: integral of speed, never recovers ----------------------
        stress = min(1.0, stress + (s ** 1.2) / 190.0)
        ch["stress"].append(stress)

        # -- Camera intensity: one-pole low-pass (camera reacts late) --------
        cam += (s - cam) * (0.18 if s > cam else 0.08)
        ch["cam_intensity"].append(cam)

        # -- Light pulses: decaying impulses at every notification + beats --
        pulse = 0.0
        for nf in notif_frames:
            if f >= nf:
                pulse += math.exp(-(f - nf) / 5.0)
        ch["light_pulse"].append(min(1.5, pulse))

        # -- Music tempo + beat grid (shared with the audio synth) -----------
        bpm = 84.0 + 96.0 * (s ** 0.9)
        prev = beat
        beat += bpm / 60.0 / T.FPS
        if int(beat) != int(prev):
            events["beats"].append(dict(frame=f, bpm=bpm, n=int(beat)))
        ch["tempo_bpm"].append(bpm)
        ch["beat_phase"].append(beat)
        ch["music_level"].append(s)

        # -- Conveyor: only visible after the walls fall --------------------
        hall_on = f >= E["walls_land"]
        v = 0.0
        if hall_on:
            v = 0.5 + 3.0 * s
            if f >= E["accelerate"]:
                v = 0.5 + 3.0 * s + 22.0 * min(1.0, (f - E["accelerate"]) / 6.0)  # "10x"
        belt_dist += v / T.FPS
        ch["belt_speed"].append(v)
        ch["belt_distance"].append(belt_dist)
        # The finish line is always a bit faster than the people chasing it.
        if f >= E["finish_recede_start"]:
            gap += (6.0 + 1.4 * v) / T.FPS
        ch["finish_gap"].append(gap)

        # -- Spawners: accumulators turn speed into discrete events ----------
        if _in(f, E["typing_start"] + 22, E["notif_do_that"] - 2):
            acc["books"] += 7.0 * (s ** 1.5) / T.FPS
            acc["cups"] += 4.2 * (s ** 2.0) / T.FPS
            acc["papers"] += 2.6 * (s ** 1.2) / T.FPS
        if _in(f, E["typing_start"] + 2, E["notif_do_that"] - 2):
            acc["toasts"] += 5.0 * (s ** 1.3) / T.FPS
        for kind in ("books", "cups", "papers", "toasts"):
            while acc[kind] >= 1.0:
                acc[kind] -= 1.0
                events[kind].append(dict(frame=f, i=len(events[kind]),
                                         r1=rng.random(), r2=rng.random(),
                                         r3=rng.random()))
    return dict(frames=frames, ch=ch, events=events)


def value(channels, name, f):
    """Channel lookup with clamping (f is a 1-based frame)."""
    arr = channels["ch"][name]
    i = max(0, min(len(arr) - 1, int(round(f)) - T.FRAME_START))
    return arr[i]


def clock_string(minutes, ampm=True):
    m = int(minutes) % (24 * 60)
    h, mm = divmod(m, 60)
    if not ampm:
        return f"{h:02d}:{mm:02d}"
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{mm:02d} {suffix}"


if __name__ == "__main__":
    c = compute()
    ev = c["events"]
    print("books", len(ev["books"]), "cups", len(ev["cups"]), "papers", len(ev["papers"]),
          "toasts", len(ev["toasts"]), "beats", len(ev["beats"]), "keys", len(ev["keys"]))
    for f in (1, 90, 160, 200, 248, 290, 320, 380, 440, 500, 600, 650, 668):
        print(f, round(value(c, "speed", f), 2), clock_string(value(c, "clock_minutes", f)),
              "stress", round(value(c, "stress", f), 2), "belt", round(value(c, "belt_distance", f), 1),
              "gap", round(value(c, "finish_gap", f), 1))
