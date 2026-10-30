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
