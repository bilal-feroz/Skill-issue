# Work-in-progress evidence

Every image here is a genuine capture of the actual project at the stage named.
None are mock-ups or retouched. UI screenshots come from running the real Blender 5.2.3
interface on `project/skill_issue.blend` with `scripts/capture_evidence.py`, which arranges
the editors, waits for the UI to draw and calls `bpy.ops.screen.screenshot`. An isolated,
throwaway Blender config directory (`BLENDER_USER_CONFIG`) suppresses the first-run splash
without touching the machine's real preferences.

| File | Captured | What it shows |
|---|---|---|
| `01_scene_blockout.png` | 2026-10-31, first complete assembly of the code-built scene, before the lighting/material/camera fix passes | Solid-shaded viewport of the bedroom set: the student rig at the desk, the bed, the door, the shelf, shot cameras, outliner collections |
| `02_character_and_lighting.png` | 2026-10-31, after the final render | EEVEE *Rendered* viewport (real scene lights + world) through the S05 webcam camera at frame 130: the character lit by the cool laptop spill, fairy-light bokeh behind |
| `03_procedural_system.png` | 2026-10-31, during final rendering | Top: camera view of the industrial reveal with the `GN_Crowd` instances selected. Bottom: the `GN_CrowdStations` Geometry Nodes tree that places and animates ~3,200 stations from Belt Distance / Typing Phase |
| `04_final_frame_preview.png` | 2026-10-31, from the final 1080p render | Final rendered frame 606 (S24): the industrial reveal with the CONGRATULATIONS display and the CAUGHT UP finish line |
| `05_blender_timeline.png` | 2026-10-31, during final rendering | Graph Editor (normalized) of the `SPEED_CONTROLLER` channels (speed, typing phase, belt distance, finish gap, stress, camera intensity) with the 29 camera-bound timeline markers |
