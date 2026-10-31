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

## 2026-10-31: Second pass (director's notes: more cinematic, less chaotic, a better face)

Notes received: some shots unreadable, the character too low-poly with a misaligned nose,
a blurry keyboard insert, an Act III (machine → roadmap → printout → obsolete) that went by
too fast to follow, UI polish, and later "I don't like the face".

- **Skills.** Installed the Blender Expert Skills from scenario-labs/skills and followed them:
  sculpting (masses first, stated planes, the hair rules), previs (one fact per shot, eye-height
  cameras, a consistent insert angle, a visibility audit) and lighting (a large-source face key,
  light compositing). Their `bx_sculpt.py` is vendored unmodified in `scripts/vendor/` (MIT).
- **Face, round 1.** Rebuilt the head as one signed-distance sculpt (`head_sculpt.py`), which
  fixed the floating, misaligned nose. Styled it on a caricature reference from the creator
  (long nose, heavy lids, big ears) and dropped the glasses.
- **Face, round 2 (final).** The creator still disliked it. Asked what was wrong: the nose, the
  head and jaw shape, and the overall look. Their chosen direction was "cute, appealing".
  Redesigned it: a big round cranium, big eyes (r 35 mm) on the head's midline, a button nose,
  a short soft jaw with full cheeks and rosy blush, softer arched brows and medium ears. Skin
  bump reduced (it read as sandpaper in close-ups), the face key softened from 26 W to 13 W,
  and the base eyelid opening raised so stress never drops the lids to a sleepy 14°.
- **Hair.** The shell now follows the skull (the skull field +7 mm), because blended jaw masses
  bulged through a fixed ellipsoid. The forehead hairline cut is limited to the front half; one
  tilted plane had shaved the back of the head (the skill's "garrison cap" mistake). Comb
  grooves read as cap seams, so they became soft raised clumps. Messy and Blown displacements
  saturate at 14 mm, because the bigger quiff had spiked 20 cm in the hall shots.
- **Neck.** Replaced the one-span cylinder (it subdivided into a striped barrel) with a tapered
  16-ring tube, and added a ribbed crew collar so it doesn't read as a peg.
- **Retime.** Act III beats are held 0.8–1.6 s. 31 shots now; S19 is split into S19 (the printout
  hangs off the desk, header readable) and S19b (a locked-off wide as the paper floods the room).
- **Readability fixes:**
  - Keyboard insert (S07): it was a grazing angle whose specular glare washed out the keys. Now
    a high three-quarter at f/8 over matte keycaps with backlit legends.
  - The printed roadmap read upside down from the front, so it's re-oriented. It prints slowly
    for 20 frames, then pours.
  - S12 is now shot from the notification side, so both of his looks read.
  - S21 moved clear of the larger quiff.
  - The whisper (S24) settles between him and the door, so his face is three-quarter and lit by
    a door-motivated key. The whisper caption is bolder and sits on a soft dark pill.
- **Visibility audit.** `scripts/audit_shots.py` ray-casts five rays per shot at its start,
  middle and end, and reports anything hit well before the focus distance. It ended with 0 findings.
- **Audio.** Regenerated from the new timeline. The optional stretch beat was cut, so its cloth
  sound is now skipped when the window is empty (it crashed the synth before).

## 2026-10-31: Second-pass delivery

- Final render, preset `final`: 720/720 frames at 1920×1080, about 6–11 s/frame (the bedroom
  gets slower as it fills with clutter and paper).
- Blender quit without an error message after frame 491 (exit code 4). Disk space was fine
  (19 GB free). It was most likely the 4 GB GPU under a long session. Frames 492–720 were
  re-rendered in 40-frame chunks, one Blender process each with an automatic retry, and every
  chunk completed. All 720 frames were checked to be newer than the final `.blend`.
- Assembled with `scripts/assemble_video.py`: `renders/skill_issue_final.mp4`, 22.3 MB.
- `scripts/validate_project.py`: 14/14 checks pass on the frames and MP4. The `.blend` check
  (`-- --blend`) passes 7/7, with 31 camera markers bound.
- `evidence/06_character_redesign.png` comes from the new `scripts/character_turnaround.py`.
