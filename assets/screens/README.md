# Screen graphics

These are the image sequences that Blender maps onto the in-world screens of *SKILL ISSUE*.
`scripts/generate_screens.py` renders all of them deterministically. Every frame number comes
from `scripts/skill_issue/timeline.py` (`E`, `SHOTS`, `NOTIFICATIONS`) and every procedural rate
comes from `scripts/skill_issue/speed.py` (`compute()` channels and spawn events). If you retime
the film, re-run the script and the screens follow. Files are named by **film frame number**.

| Sequence | Size | Frames | Format | What it shows |
|---|---|---|---|---|
| `laptop/laptop_####.jpg` | 1280×800 | 0001–0720 | JPEG q88 | The laptop: a dark-mode fictional OS showing an online course. The three big notification cards stack top-right (90 / 103 / 114, gone after S06), speed-spawned mini toasts appear and the clutter grows with `speed`, then a full-screen tutorial at 2x / 4x / 16x (16x falls apart), the **AI CAN NOW DO THAT FOR YOU.** hero card, the red **NEW MODEL. BETTER AT EVERYTHING.** takeover, the AGENT BUILDER blueprint (nodes pop in on `machine_parts`, then **AGENT ONLINE ●** at `button_press`), a calm agent dashboard with the roadmap toast, and the **0 / 847 SKILLS MASTERED** roadmap, whose scroll is the integrated `speed` channel. At `notif_obsolete` it goes grey with an OBSOLETE stamp and the **NEW RELEASE. ROADMAP OBSOLETE.** alert. Black from `close_laptop`. |
| `monitor/monitor_####.jpg` | 1600×900 | 0001–0720 | JPEG q88 | His work, on the external monitor. First a paper reader plus a `learn_ai.ipynb` cell (`# Day 1`). Then a code editor that types at `typing_phase`, a terminal installing ever-deprecated agent frameworks, and a leaderboard where each new bar towers over the old ones. Then the finished `agent_v7_final_FINAL.py` (**4,812 lines · 9 hours**), a red glitch flicker, cyan agent telemetry (TRAINING AGENT… → ONLINE), and **PRINTING ROADMAP… page N of ∞** with a paper feed. At `notif_obsolete` it is greyed with OBSOLETE, then a dim **KEEP UP.** screensaver. |
| `notebook/notebook_####.png` | 1024×1024 | 0001–0232 | PNG RGB | The right-hand page of a spiral notebook: cream paper, blue rules, red margin and light grain. The handwriting is a procedural single-stroke font defined in code, drawn as a true write-on, stroke by stroke. It writes **LEARN AI.** (`write1_*`), a confident underline (`underline1_*`) and **LEARN AI FASTER.** (`write2_*`, messier and heavier), then the frantic scribbles of S08–S09 (FASTER!!, SLEEP LATER, AGENTS?? circled, crossed-out words). Blender should hold the last frame. |
| `display/display_####.jpg` | 1920×640 | 0560–0720 | JPEG q88 | The stadium LED jumbotron: a 240×80 LED grid at an 8 px pitch, with bloom and light scanlines. It shows **KEEP UP.** with a ticking *MODELS RELEASED TODAY* counter, then **CONGRATULATIONS. / YOU ARE NOW AN EXPERT.** with LED confetti from `pa_start`. At `display_flip` comes a 4-frame split-flap glitch, then the red/amber warning (`T.DISPLAY_FINAL`) flashing slightly. |
| `crowd_atlas.png` | 2048×1280 | single | PNG | 4×4 grid of 512×320 tiles: sixteen fictional AI-announcement screens for the background students' monitors. Tile *i* sits at column `i % 4`, row `i // 4`. |

## Regenerate

```
python scripts/generate_screens.py                           # everything (~30 s on 16 cores)
python scripts/generate_screens.py --only laptop,monitor     # some sequences (laptop, monitor, notebook, display, atlas)
python scripts/generate_screens.py --only laptop --frames 230-320
python scripts/generate_screens.py --contact sheet.jpg       # key-frame contact sheet
```

Requirements: system Python 3.11, Pillow and numpy (`requirements.txt`). Everything is
seeded, so no randomness depends on time and identical inputs give identical files.

**Static holds are hard links.** If two frames of a sequence encode to the same bytes (the
finished-code hold, the hero card hold, black frames, notebook pauses), the writer stores the
file once and hard-links the other names to it. That cuts disk use from ≈180 MB to ≈130 MB,
and git deduplicates identical content anyway. Before writing, the script always deletes the
old name, so re-rendering one frame never changes a frame that was linked to it. Blender just
sees normal files.

## Fonts

Only the two fonts bundled in `assets/fonts/` are used (no system fonts):

- **Inter** (`Inter.woff2`, variable: `opsz` 14–32, `wght` 100–900), © The Inter Project
  Authors, **SIL Open Font License 1.1** (`assets/fonts/Inter-OFL-1.1.txt`). It sets all UI
  text, with weight and optical size chosen per call through `set_variation_by_axes`.
- **DejaVu Sans Mono** (`DejaVuSansMono.woff2`), released under the **Bitstream Vera Fonts
  license** (DejaVu changes are in the public domain;
  `assets/fonts/DejaVuSansMono-Bitstream-Vera-LICENSE.txt`). It sets code and terminal text.

The notebook handwriting is not a font file: it is stroke data and a renderer in
`generate_screens.py` (`GLYPHS`, `hand_text`). All brands, products, people and frameworks shown
on screen are fictional.
