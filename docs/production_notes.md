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
