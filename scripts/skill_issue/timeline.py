"""SKILL ISSUE: the single source of truth for timing.

Pure Python (no bpy), so the Blender build, the screen-graphics generator and
the audio synthesiser all read the same frame numbers. Change a frame here,
re-run the pipeline, and picture, screens and sound stay in sync.

Frames are 1-based, 24 fps, 720 frames = 30.0 s.
"""

FPS = 24
FRAME_START = 1
FRAME_END = 720

# ---------------------------------------------------------------------------
# Shot list.  camera = name of the camera object bound by a timeline marker.
# ---------------------------------------------------------------------------
SHOTS = [
    # ACT I: FALSE CONFIDENCE  (calm, locked-off, eye level)
    dict(id="S01", start=1,   end=44,  cam="CAM_Establish",  act=1, desc="Wide push-in: he writes LEARN AI."),
    dict(id="S02", start=45,  end=68,  cam="CAM_Notebook",   act=1, desc="Notebook insert: LEARN AI. underlined"),
    dict(id="S03", start=69,  end=94,  cam="CAM_Webcam",     act=1, desc="Webcam MCU: smug smile, sip. Ding."),
    dict(id="S04", start=95,  end=126, cam="CAM_Laptop",     act=1, desc="Laptop: three notifications stack"),
    dict(id="S05", start=127, end=138, cam="CAM_Webcam",     act=1, desc="Webcam: the smile dies"),
    dict(id="S06", start=139, end=156, cam="CAM_Notebook",   act=1, desc="Notebook: LEARN AI FASTER."),
    # ACT II: THE ARMS RACE  (cuts and moves accelerate, one fact per shot)
    dict(id="S07", start=157, end=176, cam="CAM_Keyboard",   act=2, desc="Keyboard insert: typing accelerates"),
    dict(id="S08", start=177, end=196, cam="CAM_Montage",    act=2, desc="Three-quarter: head snaps, book tower, cups"),
    dict(id="S08b", start=197, end=208, cam="CAM_Clock",     act=2, desc="The desk clock races"),
    dict(id="S09", start=209, end=230, cam="CAM_Laptop",     act=2, desc="Laptop: tutorial 2x / 4x / 16x"),
    dict(id="S10", start=231, end=240, cam="CAM_Webcam",     act=2, desc="Webcam: furious nodding"),
    dict(id="S11", start=241, end=258, cam="CAM_Laptop",     act=2, desc="Laptop: AI CAN NOW DO THAT FOR YOU."),
    dict(id="S12", start=259, end=284, cam="CAM_Profile",    act=2, desc="Code. Notification. Code. Hold."),
    dict(id="S13", start=285, end=296, cam="CAM_Laptop",     act=2, desc="Laptop: NEW MODEL. BETTER AT EVERYTHING."),
    dict(id="S14", start=297, end=310, cam="CAM_Scream",     act=2, desc="Silent scream, crash zoom"),
    # ACT III: AUTOMATE THE SUFFERING  (slower, every beat held long enough to read)
    dict(id="S15", start=311, end=348, cam="CAM_Build",      act=3, desc="The idea. The agent machine assembles itself"),
    dict(id="S16", start=349, end=374, cam="CAM_Machine",    act=3, desc="Machine wakes. He slams the BIG BUTTON"),
    dict(id="S17", start=375, end=398, cam="CAM_Relax",      act=3, desc="He finally relaxes. Sip. Chime."),
    dict(id="S18", start=399, end=432, cam="CAM_Laptop",     act=3, desc="ROADMAP READY -> 0 / 847 SKILLS MASTERED -> scroll"),
    dict(id="S19", start=433, end=452, cam="CAM_Printer",    act=3, desc="The machine prints his roadmap: the header hangs off the desk"),
    dict(id="S19b", start=453, end=470, cam="CAM_PrinterWide", act=3, desc="...and keeps printing: paper floods the room toward the door"),
    dict(id="S20", start=471, end=492, cam="CAM_Webcam",     act=3, desc="He looks at the paper... then at us. Reaches for coffee"),
    dict(id="S21", start=493, end=516, cam="CAM_LaptopHigh", act=3, desc="NEW RELEASE. ROADMAP OBSOLETE."),
    dict(id="S22", start=517, end=530, cam="CAM_Empty",      act=3, desc="Silence. Empty face"),
    # ACT IV: THE PUNCHLINE
    dict(id="S23", start=531, end=548, cam="CAM_Stand",      act=4, desc="Closes the laptop, stands"),
    dict(id="S24", start=549, end=584, cam="CAM_Door",       act=4, desc="Walks to the door. Breath. Whisper."),
    dict(id="S25", start=585, end=618, cam="CAM_Reveal",     act=4, desc="Walls fall. Orbit reveal of the hall"),
    dict(id="S26", start=619, end=638, cam="CAM_Proud",      act=4, desc="CONGRATULATIONS. Pride."),
    dict(id="S27", start=639, end=654, cam="CAM_Display",    act=4, desc="Display: 10X FASTER. Yanked back"),
    dict(id="S28", start=655, end=674, cam="CAM_Pullback",   act=4, desc="Impossible pull-back: the loop"),
    dict(id="S29", start=675, end=720, cam="CAM_Title",      act=5, desc="SKILL ISSUE. / HUMANITY: STILL IN BETA."),
]

# ---------------------------------------------------------------------------
# Named story beats (frame numbers).  Everything animates off these.
# ---------------------------------------------------------------------------
E = dict(
    # Act I
    write1_start=8, write1_end=52,          # "LEARN AI."  (last letters land in the S02 insert)
    underline1_start=54, underline1_end=62,
    smile_start=70, sip1_start=74, sip1_end=88,
    notif1=92, notif2=104, notif3=115,      # stacked on the laptop
    glance1=94, smile_fade_start=128, smile_fade_end=136,
    write2_start=141, write2_end=153,       # "LEARN AI FASTER."
    # Act II
    typing_start=157, typing_stop=244,
    snaps=[181, 188, 193, 197, 200, 203, 205],   # head snaps laptop <-> monitor
    tutorial_2x=209, tutorial_4x=216, tutorial_16x=223,
    nod_start=231, nod_end=240,
    notif_do_that=242,                       # AI CAN NOW DO THAT FOR YOU.
    look_code1=262, look_notif=270, look_code2=278,
    notif_better=285,                        # NEW MODEL. BETTER AT EVERYTHING.
    scream_start=298, scream_end=310,
    # Act III
    idea=312, build_start=318, build_end=344,
    machine_lights=350, button_press=363,
    lean_back=377, sip2_start=380, sip2_end=392, notif_roadmap=388,
    roadmap_open=408, scroll_start=420,
    print_start=433, print_end=468,
    look_scroll=474, look_machine=479, look_audience=484, reach_coffee=488,
    notif_obsolete=495, silence_start=495, empty_face=517,
    # Act IV
    close_laptop=531, stand_start=538, stand_end=546, stretch_start=546, stretch_end=546,
    walk_start=549, walk_end=560, breath=562, whisper_start=564, whisper_end=588,
    handle_turn=584, walls_fall_start=586, walls_land=597,
    finish_recede_start=600, run_student=602, reach_student=606,
    pa_start=604, pa_end=640,                # chime at 604, voice right after
    realize=620, proud_start=627, proud_end=640,
    display_flip=641, accelerate=645, yank=647, defeat=652,
    pullback_start=655, black=675, title_slam=676, subtitle=688,
    # Extra SFX sync points
    laptop_clack=537, chair_roll=538, steps=[551, 555, 559], wall_creak=585,
    machine_parts=[319, 322, 325, 328, 331, 334, 337, 340, 343],  # each part locks in
    # Screen-graphics phase boundaries (independent of shot numbering)
    notifs_out=156, code_done=259, builder_start=311, dashboard_start=375,
    scrib_start=178, scrib_end=230,
)

# Animation conventions shared by Blender and the audio synth:
#   books : spawn frame f, fall 5 frames, land (thump) at f + 5
#   cups  : pop in at f, settle (clink) at f + 2
#   papers: slide in over f..f+6 (swish starts at f)
#   toasts: small UI notification tick at f
SPAWN_LAND_OFFSET = dict(books=5, cups=2, papers=0, toasts=0)

# Laptop / phone notifications (screen generator + audio "ding" read this).
NOTIFICATIONS = [
    dict(frame=E["notif1"],         text="NEW MODEL RELEASED.",             kind="release"),
    dict(frame=E["notif2"],         text="NEW AGENT FRAMEWORK.",            kind="release"),
    dict(frame=E["notif3"],         text="NEW BENCHMARK. EVERYTHING CHANGED.", kind="alert"),
    dict(frame=E["notif_do_that"],  text="AI CAN NOW DO THAT FOR YOU.",     kind="hero"),
    dict(frame=E["notif_better"],   text="NEW MODEL. BETTER AT EVERYTHING.", kind="hero_alert"),
    dict(frame=E["notif_roadmap"],  text="YOUR PERSONALIZED AI LEARNING ROADMAP IS READY.", kind="calm"),
    dict(frame=E["notif_obsolete"], text="NEW RELEASE. ROADMAP OBSOLETE.",  kind="hero_alert"),
]

PA_LINE = "Congratulations. You are now an expert."
WHISPER_LINE = "Finally. I'm caught up."
DISPLAY_FINAL = ("NEW MODEL RELEASED.", "10X FASTER", "THAN PREVIOUS GENERATION.")
TITLE = "SKILL ISSUE."
SUBTITLE = "HUMANITY: STILL IN BETA."

ROADMAP_TOTAL = 847


def shot_at(frame):
    for s in SHOTS:
        if s["start"] <= frame <= s["end"]:
            return s
    return SHOTS[-1]


def sec(frame):
    return (frame - 1) / FPS


def validate():
    """Shots must tile 1..720 with no gaps or overlaps."""
    expected = FRAME_START
    for s in SHOTS:
        assert s["start"] == expected, f"gap/overlap before {s['id']}: {s['start']} != {expected}"
        assert s["end"] >= s["start"], s["id"]
        expected = s["end"] + 1
    assert expected - 1 == FRAME_END, f"shots end at {expected - 1}, not {FRAME_END}"
    return True


if __name__ == "__main__":
    validate()
    for s in SHOTS:
        print(f"{s['id']}  {s['start']:4d}-{s['end']:4d}  {sec(s['start']):5.2f}s  {(s['end']-s['start']+1)/FPS:4.2f}s  {s['desc']}")
