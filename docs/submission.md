# Submission materials (prepared, NOT submitted)

Copy-ready text for the RenderJuice *Blender Animation & Programmatic Rendering* contest entry
and its Devpost mirror. The official entry needs the creator's RenderJuice account, the
contest Discord and a post in the submission channel. **None of that has been done yet.**

## Title
SKILL ISSUE

## Creator
Bilal Feroz

## Video
`renders/skill_issue_final.mp4` (1920×1080, 24 fps, 30.0 s). Upload it to a public host
(YouTube, Vimeo or similar) and paste the link here.

## Interpretation of speed (short)
A student tries to learn AI faster than AI changes. Every notification adds a skill, every
tool he builds speeds up the treadmill, and his 847-skill roadmap is obsolete before he
finishes his coffee. When he finally stops, his bedroom turns out to be a stage set on an
endless conveyor of identical students chasing a finish line called CAUGHT UP. It's engineered
to move faster than they do. The speed is literal in the code too: one normalised speed
curve drives the typing, the clock, the clutter, the music, the lights, the camera shake, the
conveyor belts and the receding finish line.

## Workflow notes (procedural & programmatic category)
- Built 100% from Python in Blender 5.2.3. `scripts/build_scene.py` recreates the entire
  project (character, rig, sets, crowd, cameras, lights, all animation) from nothing in ~6 s.
- **Speed controller:** `speed.py` defines a 0..1 speed curve with distinct phases (slow open,
  escalation, dead stops on punchlines, explosive end). Derived channels with different response
  curves, lags and offsets (typing frequency, clock rate, spawn rates, camera intensity, light
  pulses, music tempo, belt speed, finish-line recession, stress) are baked onto a
  `SPEED_CONTROLLER` empty and wired with drivers into Geometry Nodes and shaders.
- **Geometry Nodes crowd:** ~3,200 identical students on 11 belts of an analytic oval
  track. Their positions come from *Sample Curve* at `slot·spacing + BeltDistance`, their arms
  and heads are animated by the crowd typing phase, and every screen picks a different AI
  announcement through a per-instance attribute. Twenty-four more loops are instanced into the
  distance.
- **Code-driven acting:** a custom pose solver (analytic two-bone IK) bakes pose-to-pose
  performance onto a real armature. Typing, nods, blinks, breathing, saccades and handheld
  noise are procedural layers.
- **One timeline, three media:** the same `timeline.py` drives the Blender animation, the
  generated screen UIs (Pillow) and the synthesised soundtrack (numpy), so picture and sound
  stay frame-accurate after any retime.
- Deterministic and reproducible: seeded randomness, and a resumable renderer, FFmpeg
  assembly and automated validation scripts.

## AI & third-party disclosure
Made with an AI coding agent (Claude by Anthropic, in Claude Code), which wrote all the code
that generates the film. No generative image, video, 3D or music models, and no third-party
3D, texture, music or SFX assets. The two short voice lines are Windows' built-in offline TTS,
heavily processed. Fonts: Inter (OFL) and DejaVu Sans Mono (Bitstream Vera), bundled with
Blender. Details: `docs/asset_disclosures.md`.

## WIP image
`evidence/01_scene_blockout.png` (any of the files in `evidence/` qualifies; all are genuine
captures of the Blender UI or renders).
