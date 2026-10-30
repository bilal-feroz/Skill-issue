# Production log

Newest entries at the bottom. Records decisions, milestones, render settings and recovery steps.

## 2026-10-31: Environment and plan

**Environment inspected**
- Blender **5.2.3 LTS** at `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`
  (a leftover `Blender 4.5` folder has no executable). Engines: EEVEE, Cycles (OptiX/CUDA), Workbench.
- GPU: NVIDIA GeForce RTX 3050 Laptop, **4 GB VRAM**. CPU: Ryzen 7 7435HS (8C/16T). RAM: 15.8 GB.
- Disk: only **~11 GB free on C:**. Frame storage is budgeted, intermediates are deleted after validation.
- FFmpeg/FFprobe 9.0.2, system Python 3.11 with Pillow 12.3 and numpy 2.4.
- No asset libraries with characters are installed. Everything is built from code.
- **Blender MCP isn't connected in this session** (no Blender tools exposed to the agent).
  Workaround: drive Blender headlessly (`blender -b -P script.py`) with the same bpy API. WIP
  screenshots come from launching the real Blender UI on the project file and capturing the
  window with `bpy.ops.screen.screenshot`.

**Key decisions**
- Engine: EEVEE (chosen for the 4 GB GPU). Will benchmark before committing.
- One shared, pure-Python timing core (`scripts/skill_issue/timeline.py` + `speed.py`) read by
  Blender, the screen-graphics generator and the audio synthesiser. This keeps sync deterministic.
- Screens (laptop, monitor, notebook handwriting, stadium display) are generated as image
  sequences with Pillow from the same event table, then mapped as textures in Blender.
- Fonts: Inter (OFL 1.1) and DejaVu Sans Mono (Bitstream Vera license), copied from Blender's
  bundled datafiles. Handwriting is a custom procedural single-stroke font written in code.
- Git: plain Git (no LFS) to keep cloning simple. Binary files are committed only at milestones.

## 2026-10-31: First complete assembly

- The whole project now builds from code in ~6 s: `blender -b --factory-startup -P scripts/build_scene.py`.
  Modules: `character` (rig + deforming meshes), `puppet` (2-bone IK pose solver -> baked bone
  keys), `room`, `machine`, `hall` (Geometry Nodes crowd + far loops), `animate` (performance),
  `cameras`, `lighting`, `render_setup`.
- Screen graphics (`scripts/generate_screens.py`, 1,833 frames) and the soundtrack
  (`scripts/generate_audio.py`) were built in parallel and both read the shared timeline.
- Retimed Act IV so the whisper doesn't collide with the walls falling, and so the
  pull-back and the title card get enough screen time. S12 was split so the
  "AI CAN NOW DO THAT FOR YOU" card gets a readable insert before the look gag.
- Blender 5.2 API notes (for anyone extending this):
  - Geometry Nodes modifier inputs are `mod.properties.inputs.Socket_N.value`
    (no ID properties). Driver path: `modifiers["X"].properties.inputs.Socket_N.value`.
  - New shape keys default to value 1.0, so they're zeroed explicitly.
  - The compositor uses node groups (`scene.compositing_node_group`) with a Group Output.
    Mix and Map Range are Shader nodes; `FunctionNodeCompare` only exposes the active inputs.
  - Actions are slotted, so f-curves go through `anim_utils.action_ensure_channelbag_for_slot`.
- Bugs found by rendering and inspecting test frames, then fixed:
  - A GN crowd station spawned inside the bedroom (the per-lane stagger offset the hero slot).
  - The office chair was built backwards (backrest between him and the desk).
  - The hero rig got the belt offset twice (parented to the station and baked with it).
  - The procedural iris used object-space coordinates, which slide under the Armature
    modifier, so the eyes rendered blank white. Fixed by storing rest-pose coordinates as
    a `rest_co` mesh attribute that all character shaders read. This also stops fabric and
    skin textures swimming.
  - The CAUGHT UP sign was mirrored and lost in glare. It's now a large panel sign above the gate.
- Render benchmark (EEVEE, RTX 3050 4 GB): preview (50 %, 12 spp) ~2 s/frame;
  full 1080p (48 spp) ~6–9 s/frame; draft animatic (25 %, 4 spp) ~0.65 s/frame.

## 2026-10-31: Timing review and final render

- Rendered a full 480×270 draft animatic (720 frames, 412 s) and muxed it with the soundtrack
  (`renders/skill_issue_animatic_v1.mp4`). I reviewed it as dense contact sheets (every 4th–8th frame).
  Fixes that came out of it:
  - The coffee sip never reached his mouth (the head-relative offset was in the wrong axes).
    The mug now leads (`Hero.mug_world`) and the left hand follows it.
  - The book towers were hidden from the front shot. They now rise on the notebook and beside the chair.
  - The machine moved within reach so the BIG BUTTON slam lands on camera, and the core glow was toned down.
  - The S10/S17 insert camera was inside the (backwards) chair backrest. The S15 camera was
    inside a book tower.
  - The whisper caption is composited (Alpha Over in the compositor, keyed per frame) because
    a 3D text card either went out of focus or sat inside his head.
  - The clock now races harder (16·s^2.6 min/frame).
  - The pull-back arrives early and holds on the loop field. Motion-blur shutter is keyed down
    during it.
- Final render: preset `final` (1920×1080, EEVEE 48 spp, screen-space ray tracing + fast GI,
  motion blur 0.42, AgX Medium High Contrast, compositor mist fog, fog glow, vignette),
  ~4.8 s/frame, PNG frames to `renders/frames/` (git-ignored). Resumable with Blender's
  placeholder/no-overwrite mode: rerun the same command to continue after an interruption.
- Recovery: if the .blend is lost, run the generators, then `build_scene.py`. Everything is
  deterministic. To re-render a range: `render_frames.py -- --preset final --frames A-B --overwrite`.

## 2026-10-31: Delivery

- Final render complete: 720/720 frames at 1920×1080 in ~60 min (~4.8 s/frame).
- EEVEE logged "Shadow buffer full (2545/2048)" on the wide hall shots (Act IV). I inspected
  those frames and saw no visibly missing shadows, so it was left as is. If a future change
  shows popping shadows, raise `scene.eevee.shadow_pool_size` or lower the hall light count.
- Post-render review found one broken shot: S20 (frames 491–502) rendered as a blurry smear
  because the book tower on the notebook had grown around the over-the-shoulder camera.
  It now has a high-angle over-the-shoulder camera, and frames 490–503 were re-rendered
  (`--overwrite`). Everything else is deterministic, so the rest of the sequence is unchanged.
- Assembled with `scripts/assemble_video.py` (libx264 CRF 16, preset slow, tune animation,
  yuv420p, AAC 256 kbps, faststart): `renders/skill_issue_final.mp4`, 23.5 MB.
- `scripts/validate_project.py`: 14/14 checks pass (720 frames present, consistent size,
  H.264, 1920×1080, 24/1 fps, 720 frames decoded, yuv420p, 30.000 s, AAC present, audio 30.000 s,
  decodes without errors, no unintended black). The .blend check (`-- --blend`) passes 7/7.
- The soundtrack was regenerated from the final timeline before muxing. Sync points come
  from the same frame table as the picture.

### Known limitations
- The character is a stylised primitive-built puppet. Fingers and cloth don't simulate, and
  sleeves can show minor interpenetration in extreme poses.
- Voice lines are processed Windows TTS (disclosed). A human performance would be warmer.
- The far-loop field is a set of emissive instances (it reads as the system from 1 km up,
  but has no detail up close).
