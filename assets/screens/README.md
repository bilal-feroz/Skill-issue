# Screen graphics

These are the image sequences that Blender maps onto the in-world screens of *SKILL ISSUE*.
`scripts/generate_screens.py` renders all of them deterministically. Every frame number comes
from `scripts/skill_issue/timeline.py` (`E`, `SHOTS`, `NOTIFICATIONS`) and every procedural rate
comes from `scripts/skill_issue/speed.py` (`compute()` channels and spawn events). If you retime
the film, re-run the script and the screens follow. Files are named by **film frame number**.

| Sequence | Size | Frames | Format | What it shows |
|---|---|---|---|---|
| `laptop/laptop_####.jpg` | 1280×800 | 0001–0720 | JPEG q88 | The laptop. Every state has one hero message in big type with one accent colour (blue info, red alert, cyan agent, amber warning) and the UI behind it blurred and darkened. Entrances are a 6-frame eased slide plus fade. An online course; at `notif1/2/3` three big notification cards stack in the centre (gone by `notifs_out`). From `typing_start` the clutter grows with `speed`: tabs, OUTDATED tags, and big speed-spawned toasts (max four). Then the tutorial at 2x / 4x / 16x (16x falls apart deliberately; the badge stays crisp and toast ticks collapse into one +N updates pill), the **AI CAN NOW DO THAT FOR YOU.** card, and the full-screen red **NEW MODEL. BETTER AT EVERYTHING.** (3-frame glitch entrance, then solid). From `builder_start`, the AGENT BUILDER (nodes pop in on `machine_parts`, **AGENT ONLINE ●** at `button_press`); from `dashboard_start`, a calm agent dashboard. At `notif_roadmap` a big centred **YOUR PERSONALIZED AI LEARNING ROADMAP IS READY.** card with OPEN, which a cursor clicks at `roadmap_open`−3. At `roadmap_open` the giant pinned **0 / 847 SKILLS MASTERED** opens and holds perfectly still until `scroll_start`, then the list scrolls on the integrated `speed`; from `print_start` a **PRINTING… page n of ∞** chip. At `notif_obsolete` the roadmap greys out under an OBSOLETE stamp and a full-width red **NEW RELEASE. / ROADMAP OBSOLETE.** band (3-frame entrance, then static). Black from `close_laptop`. From `yank`+5 to `black` the lid is reopened: a frantic **32x** tutorial under a **NEW MODEL RELEASED · 10X FASTER** banner. |
| `monitor/monitor_####.jpg` | 1600×900 | 0001–0720 | JPEG q88 | His work. A paper reader plus a **TODAY'S GOAL: Learn AI.** widget. From `typing_start`, a code editor typing at `typing_phase`, a terminal installing ever-deprecated agent frameworks, a leaderboard and big update pop-ups. From `code_done`, the finished code behind a hero card (**4,812 LINES · 9 HOURS · ✓ ALL TESTS PASSED**). Then a red glitch at `notif_better`. From `builder_start`, cyan telemetry (TRAINING AGENT… → ONLINE). From `print_start`, **PRINTING ROADMAP… page N of ∞** with a paper feed. At `notif_obsolete` it is greyed with OBSOLETE, then a dim **KEEP UP.** screensaver. |
| `notebook/notebook_####.png` | 1024×1024 | 0001–`scrib_end` | PNG RGB | The right-hand page of a spiral notebook: cream paper, blue rules, red margin and light grain. The handwriting is a procedural single-stroke font defined in code, drawn as a true write-on, stroke by stroke. It writes **LEARN AI.** (`write1_*`), a confident underline (`underline1_*`) and **LEARN AI FASTER.** (`write2_*`, messier and heavier), then the frantic scribbles of `scrib_start`–`scrib_end` (FASTER!!, SLEEP LATER, AGENTS?? circled, crossed-out words). Blender should hold the last frame. |
| `display/display_####.jpg` | 1920×640 | 0560–0720 | JPEG q88 | The stadium LED jumbotron: a 240×80 LED grid at an 8 px pitch, with bloom and light scanlines. It shows **KEEP UP.** with a ticking *MODELS RELEASED TODAY* counter, then **CONGRATULATIONS. / YOU ARE NOW AN EXPERT.** with LED confetti from `pa_start`. At `display_flip` comes a 4-frame split-flap glitch, then the red/amber warning (`T.DISPLAY_FINAL`) flashing slightly. |
| `crowd_atlas.png` | 2048×1280 | single | PNG | 4×4 grid of 512×320 tiles: sixteen fictional AI-announcement screens for the background students' monitors. Tile *i* sits at column `i % 4`, row `i // 4`. |
| `roadmap_paper_head.png` | 512×1536 | single | PNG | Start of the physical thermal printout (top edge = first paper out): off-white paper and near-black ink, the big header **YOUR AI LEARNING ROADMAP**, a line *847 SKILLS · PERSONALIZED · v1.0*, a receipt block, then checkbox items ☐ 001… |
| `roadmap_paper_tile.png` | 512×2048 | single | PNG | The printout continued: items 101–130 plus two section lines on a 64 px row grid. Tiles seamlessly in V, and the head's bottom edge joins its top. |
| `keyboard.png` | 2048×780 | single | PNG | Albedo for the laptop keyboard plane (0.29 × 0.11 m): a dark six-row QWERTY laptop layout with function row and inverted-T arrows, rounded keycaps, bevel, shadow, light-grey legends and a soft cool backlight bleed. |
| `keyboard_glow.png` | 2048×780 | single | PNG (L) | Emission mask in the same layout: white legends plus the keycap-edge backlight glow on black. |

## Regenerate

```
python scripts/generate_screens.py                           # everything (~30 s on 16 cores)
python scripts/generate_screens.py --only laptop,monitor     # some outputs (laptop, monitor, notebook, display, atlas, paper, keyboard)
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
