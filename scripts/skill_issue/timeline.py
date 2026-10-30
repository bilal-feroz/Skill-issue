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
    # ACT I: FALSE CONFIDENCE
    dict(id="S01", start=1,   end=44,  cam="CAM_S01_Establish",   act=1, desc="Wide push-in, writing LEARN AI."),
    dict(id="S02", start=45,  end=68,  cam="CAM_S02_Notebook",    act=1, desc="Notebook insert, underline"),
    dict(id="S03", start=69,  end=92,  cam="CAM_S03_Webcam",      act=1, desc="Webcam MCU: smug smile, coffee sip"),
    dict(id="S04", start=93,  end=122, cam="CAM_S04_Screen",      act=1, desc="Laptop: three notifications stack"),
    dict(id="S05", start=123, end=140, cam="CAM_S05_WebcamDoubt", act=1, desc="Webcam: smile fades"),
    dict(id="S06", start=141, end=160, cam="CAM_S02_Notebook",    act=1, desc="Notebook: adds FASTER"),
    # ACT II: THE ARMS RACE
    dict(id="S07", start=161, end=184, cam="CAM_S07_Hands",       act=2, desc="Hands CU, typing accelerates"),
    dict(id="S08", start=185, end=214, cam="CAM_S08_Front",       act=2, desc="Front MS: head snaps, books stack"),
    dict(id="S09", start=215, end=232, cam="CAM_S09_Clock",       act=2, desc="Desk dolly: racing clock, cups, papers"),
    dict(id="S10", start=233, end=256, cam="CAM_S10_Tutorial",    act=2, desc="Laptop: tutorial 2x / 4x / 16x"),
    dict(id="S11", start=257, end=268, cam="CAM_S11_Nod",         act=2, desc="Webcam CU: furious nodding"),
    dict(id="S12", start=269, end=312, cam="CAM_S12_Shoulder",    act=2, desc="AI CAN NOW DO THAT FOR YOU. The look."),
    dict(id="S13", start=313, end=330, cam="CAM_S13_Scream",      act=2, desc="NEW MODEL. Silent scream, crash zoom"),
    # ACT III: AUTOMATE THE SUFFERING
    dict(id="S14", start=331, end=362, cam="CAM_S14_Build",       act=3, desc="Idea + agent machine assembles"),
    dict(id="S15", start=363, end=386, cam="CAM_S15_Machine",     act=3, desc="Machine CU: lights, tubes, BUTTON"),
    dict(id="S16", start=387, end=410, cam="CAM_S16_Relax",       act=3, desc="He relaxes, sips; roadmap ready"),
    dict(id="S17", start=411, end=434, cam="CAM_S17_Roadmap",     act=3, desc="Laptop: 0 / 847 skills, scroll"),
    dict(id="S18", start=435, end=468, cam="CAM_S18_Scroll",      act=3, desc="Pull back: paper scroll out the door"),
    dict(id="S19", start=469, end=490, cam="CAM_S19_Looks",       act=3, desc="Looks: scroll, machine, audience"),
    dict(id="S20", start=491, end=502, cam="CAM_S04_Screen",      act=3, desc="ROADMAP OBSOLETE."),
    dict(id="S21", start=503, end=516, cam="CAM_S21_Empty",       act=3, desc="Silence. Empty face."),
    # ACT IV: THE PUNCHLINE
    dict(id="S22", start=517, end=552, cam="CAM_S22_Stand",       act=4, desc="Closes laptop, stands, stretches"),
    dict(id="S23", start=553, end=584, cam="CAM_S23_Door",        act=4, desc="Walks to door, breath, whisper"),
    dict(id="S24", start=585, end=618, cam="CAM_S24_Reveal",      act=4, desc="Walls fall. Orbit reveal of the hall"),
    dict(id="S25", start=619, end=642, cam="CAM_S25_Proud",       act=4, desc="CONGRATULATIONS. Proud."),
    dict(id="S26", start=643, end=656, cam="CAM_S26_Display",     act=4, desc="Display: NEW MODEL 10X. Yanked back"),
    dict(id="S27", start=657, end=668, cam="CAM_S27_Pullback",    act=4, desc="Impossible pull-back: the loop"),
    dict(id="S28", start=669, end=720, cam="CAM_S28_Title",       act=5, desc="SKILL ISSUE. / HUMANITY: STILL IN BETA."),
]

# ---------------------------------------------------------------------------
# Named story beats (frame numbers).  Everything animates off these.
# ---------------------------------------------------------------------------
E = dict(
    # Act I
    write1_start=6, write1_end=40,          # "LEARN AI."
    underline1_start=47, underline1_end=56,
    smile_start=70, sip1_start=74, sip1_end=88,
    notif1=90, notif2=103, notif3=114,      # stacked on laptop
    glance1=92, smile_fade_start=124, smile_fade_end=136,
    write2_start=143, write2_end=157,       # "FASTER"
    # Act II
    typing_start=161, typing_stop=272,
    snaps=[188, 195, 200, 204, 207, 210, 212],   # head snaps laptop <-> monitor
    tutorial_2x=233, tutorial_4x=241, tutorial_16x=248,
    nod_start=257, nod_end=268,
    notif_do_that=270,                       # AI CAN NOW DO THAT FOR YOU.
    look_code1=279, look_notif=290, look_code2=300,
    notif_better=313,                        # NEW MODEL. BETTER AT EVERYTHING.
    scream_start=316, scream_end=330,
    # Act III
    idea=332, build_start=338, build_end=360,
    machine_lights=363, button_press=377,
    lean_back=388, sip2_start=392, sip2_end=404, notif_roadmap=400,
    roadmap_open=411, scroll_start=415,
    print_start=437, print_end=466,
    look_scroll=470, look_machine=475, look_audience=480, reach_coffee=486,
    notif_obsolete=492, silence_start=492, empty_face=503,
    # Act IV
    close_laptop=519, stand_start=528, stand_end=540, stretch_start=538, stretch_end=552,
    walk_start=554, walk_end=571, breath=573, whisper_start=575, whisper_end=596,
    handle_turn=586, walls_fall_start=588, walls_land=599,
    finish_recede_start=602, reach_student=606, run_student=604,
    pa_start=611, pa_end=648,                # CONGRATULATIONS. YOU ARE NOW AN EXPERT.
    realize=620, proud_start=632, proud_end=642,
    display_flip=644, accelerate=648, yank=650, defeat=654,
    pullback_start=657, black=669, title_slam=670, subtitle=682,
)

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
