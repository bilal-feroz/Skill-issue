# SKILL ISSUE: soundtrack

Original, fully procedural soundtrack: music, sound effects and ambience are synthesised from scratch in
`scripts/generate_audio.py` (numpy + the standard-library `wave` module only). No samples, loops, sound
libraries or downloads are used, and the music is composed for this film (no existing melodies).
The two voice lines come from Windows' built-in offline speech synthesiser (see the disclosure below).

## Files

| File | Content |
|---|---|
| `skill_issue_mix.wav` | Final mix: 48 kHz, 16-bit, stereo, exactly 1,440,000 samples (30.000 s = frames 1-720 at 24 fps) |
| `stems/music.wav` | Score: lo-fi loop, rhythm layers, stab, montage, relief, choir, climax, final hit |
| `stems/sfx.wav` | Foley and UI sounds, with their room/hall reverb |
| `stems/ambience.wav` | Bedroom room tone, then the industrial hall |
| `stems/voice.wav` | Whisper + PA chime and announcement |
| `source/*.wav`, `source/tts_manifest.json` | Cached raw TTS renders (so the mix rebuilds without the TTS engine) |

The stems use the same master gain and limiter gain curve as the mix, so they sum back to it
(within 16-bit dither).

## Regenerate

```
python scripts/generate_audio.py              # uses the cached TTS in audio/source/
python scripts/generate_audio.py --retts      # re-synthesise the voice lines (Windows only)
python scripts/generate_audio.py --overview overview.png   # also draw waveform/spectrogram/levels
```

Requirements: Python 3.11, numpy (Pillow only for `--overview`). Every random choice is seeded, so the
output is deterministic. All timing is read from `scripts/skill_issue/timeline.py` (`E`, `NOTIFICATIONS`,
`SPAWN_LAND_OFFSET`, `PA_LINE`, `WHISPER_LINE`) and `scripts/skill_issue/speed.py` (`compute()`: speed curve,
beat grid, hero key presses, book/cup/paper/toast spawns, belt speed). Change the timeline, re-run, and
sound stays in sync. Frame *f* starts at (f-1)/24 s = sample (f-1)*2000.

## Disclosure: synthetic voice (TTS)

- Engine: Windows System.Speech.Synthesis.SpeechSynthesizer (SAPI 5, offline, built into Windows). Offline; nothing is sent anywhere.
- PA line "Congratulations. You are now an expert.": **Microsoft Zira Desktop**, rate 7, each sentence rendered
  separately and joined, pitched down 1 semitone, then processed into a distorted industrial PA.
- Whisper "Finally. I'm caught up.": **Microsoft David Desktop**, rate 2, converted into
  a whisper by STFT processing (cepstral spectral envelope + random-phase resynthesis).
- No human voice recordings and no cloned voices are used.

## Mix stats

- Length: 1,440,000 samples at 48 kHz (30.000 s)
- Integrated loudness: -15.1 LUFS (ITU-R BS.1770 K-weighted, gated); sample peak -1.05 dBFS; true peak ~-1.05 dBTP
- Dead stop (frames 271-312): -37.7 dBFS RMS (-43.4 dBFS after the soft ding)
- Near silence (frames 492-516): -61.0 dBFS RMS, peak -49.6 dBFS
- Limiter: max 6.3 dB of gain reduction (frame 647), 3.3% of samples above 3 dB (climax drum transients and the final hit)
- Digital silence from sample 1,429,989 (frame 716) to the end

Per-second level of the final mix (RMS dBFS, and short-term loudness over the 3 s ending at that second):

| Second | Frames | RMS dBFS | Short-term LUFS |
|---|---|---|---|
| 0-1 | 1-24 | -25.1 | - |
| 1-2 | 25-48 | -25.4 | - |
| 2-3 | 49-72 | -25.7 | -23.2 |
| 3-4 | 73-96 | -24.2 | -22.6 |
| 4-5 | 97-120 | -22.1 | -20.8 |
| 5-6 | 121-144 | -25.8 | -20.8 |
| 6-7 | 145-168 | -24.3 | -21.1 |
| 7-8 | 169-192 | -22.5 | -22.7 |
| 8-9 | 193-216 | -18.8 | -20.4 |
| 9-10 | 217-240 | -16.7 | -17.9 |
| 10-11 | 241-264 | -12.4 | -14.5 |
| 11-12 | 265-288 | -16.9 | -14.3 |
| 12-13 | 289-312 | -45.3 | -15.4 |
| 13-14 | 313-336 | -12.6 | -14.3 |
| 14-15 | 337-360 | -14.4 | -13.3 |
| 15-16 | 361-384 | -15.5 | -12.4 |
| 16-17 | 385-408 | -24.8 | -15.4 |
| 17-18 | 409-432 | -22.7 | -18.2 |
| 18-19 | 433-456 | -22.9 | -21.3 |
| 19-20 | 457-480 | -24.0 | -21.0 |
| 20-21 | 481-504 | -29.4 | -22.4 |
| 21-22 | 505-528 | -38.8 | -25.3 |
| 22-23 | 529-552 | -27.9 | -28.3 |
| 23-24 | 553-576 | -30.6 | -27.9 |
| 24-25 | 577-600 | -14.5 | -19.2 |
| 25-26 | 601-624 | -14.0 | -15.0 |
| 26-27 | 625-648 | -14.1 | -13.0 |
| 27-28 | 649-672 | -11.9 | -11.1 |
| 28-29 | 673-696 | -10.5 | -10.4 |
| 29-30 | 697-720 | -18.3 | -11.2 |

## Cue sheet

Times are from the start of the film (frame 1 = 00:00.000). Stem = where the sound lives.

| Time | Frame | Stem | Sound | How it was synthesised |
|---|---|---|---|---|
| 00:00.000 | 1 | ambience | Room tone (air, distant city rumble, mains hum, one car pass) | Pink + brown noise, low/high-passed, slow traffic swell, 60/120 Hz sines; drops ~9 dB at frame 492, cut under the wall slam at 591 |
| 00:00.000 | 1 | sfx | Wall clock tick-tock (1 Hz, then racing) | Noise-burst + sine ping; rate = 1 + 14*speed^2.6 Hz, from speed.py |
| 00:00.000 | 1 | music | Lo-fi loop: Fmaj9 / Am9 / Dm9 / Bbmaj9, original EP melody, warm pad, vinyl crackle | FM electric piano (1:1 bark + 14:1 tine) on the speed.py beat grid, tape wow (variable delay), detuned-saw pad |
| 00:00.208 | 6 | sfx | Pen writes LEARN AI. (stroke per letter part) | Speed-tracking band-passed friction noise (time-varying SVF), paper-tooth AM, pen-down ticks |
| 00:01.917 | 47 | sfx | Confident underline + flick | One long pen stroke with a fast flick |
| 00:03.042 | 74 | sfx | Coffee: mug lift, slurp, gulp | Band-passed noise with bubbly AM and rising centre, chirped gulp |
| 00:03.625 | 88 | sfx | Mug set down | Pitched thunk + wood knock + three ceramic partials |
| 00:03.708 | 90 | sfx | Notification ding: NEW MODEL RELEASED. | Two-note sine bell (partials 1/2/3), in key with the loop |
| 00:04.250 | 103 | sfx | Notification ding: NEW AGENT FRAMEWORK. | Two-note sine bell (partials 1/2/3), in key with the loop |
| 00:04.708 | 114 | sfx | Alert: NEW BENCHMARK. EVERYTHING CHANGED. | Triple pulse-wave beep on a tritone cluster + low thump |
| 00:05.125 | 124 | music | Loop sours to Bbm6 with a tape-droop pitch sag | Variable-delay pitch bend (~6%) on the minor iv chord (beat 8) |
| 00:05.917 | 143 | sfx | Pen scribbles FASTER (faster, harder strokes) | As above, frantic stroke timing |
| 00:06.313 | 152.5 | music | C9sus4 -> C7b9 turnaround into Act II | Same EP/pad, tension voicings |
| 00:06.667 | 161 | sfx | Keyboard: 155 key clicks on every speed.py key press (+ ghost strokes), Acts II-IV | Per-key random noise click + pitched body + bottom-out transient; density from typing_phase; muted from the dead stop |
| 00:06.876 | 166.0 | music | Rhythm layer on the beat grid (D minor): kick, pulsing octave bass, then hats, claps, 16th arp | Layers enter as speed rises; bass/arp low-pass cutoff = 170*(1+40*speed^2.2) Hz (time-varying SVF), kick side-chain |
| 00:07.667 | 185 | sfx | 11 UI toast ticks | Sine chirp pop + 3.3 kHz tick |
| 00:07.792 | 188 | sfx | Whooshes on 7 head snaps (frames 188, 195, 200, 204, 207, 210, 212) | Pink noise through a swept band-pass SVF, peak on the snap frame, panned laptop<->monitor |
| 00:08.417 | 203 | sfx | 14 book thumps (land = spawn + 5) | Pitch-dropped sine thud + band-passed slap + page flutter |
| 00:08.625 | 208 | sfx | 5 paper swishes | Rising band-passed noise, 0.27 s |
| 00:08.792 | 212 | sfx | 7 cup clinks (settle = spawn + 2) | Inharmonic ceramic partials + contact tick |
| 00:09.667 | 233 | sfx | Tutorial voice fast-forward chatter 2x -> 4x -> 16x (no real speech) | Glottal saw + 3 time-varying formant SVFs + fricative bursts; rate/pitch/formants scale with speed-up |
| 00:10.292 | 248 | music | Chromatic bass climb, snare roll and riser into the stop | Swept noise + rising detuned saws |
| 00:11.208 | 270 | all | DEAD STOP: AI CAN NOW DO THAT FOR YOU. | Music, keys, clutter and their reverb tails hard-gated on the frame; only room tone, a soft dry ding and 3 faint clock ticks on beats 22-24 |
| 00:13.000 | 313 | music | Harsh orchestral stab + alert | D/Eb/Ab cluster saw-brass + strings, timpani boom, crash; minor-2nd pulse alert |
| 00:13.125 | 316 | sfx | Silent-scream whoosh-roar (no voice) | Resonant swept noise + brown rumble, tanh drive, flanger; cut on frame 331 |
| 00:13.125 | 316 | music | Frantic return: 180 bpm drums, 16th bass with b2 grit, tremolo string cluster, tom fill | Beat-grid sequenced; hard cut at the idea (frame 331) |
| 00:13.792 | 332 | sfx | 'Idea' sparkle | Rising five-note bell arpeggio + high shimmer |
| 00:14.034 | 337.8 | music | Montage groove (Dm-Bb-F-C) under the build | Kick/clap/hat, 16th octave bass and arp on the beat grid |
| 00:14.083 | 339 | sfx | Machine assembly: servo whir + ratchet + metal lock on each of 9 parts (frames 339, 343, 346, 349, 351, 353, 355, 357, 359) | Gliding saw/pulse motor through band-pass; accelerating noise clicks; modal metal impact landing on the frame |
| 00:15.083 | 363 | sfx | Machine wakes: rising whine, accelerating relay clicks, data-bubble trickles | Exponential sine/saw sweep with speeding tremolo; HP noise clicks; random chirped sine 'bloops' (continue until the cut) |
| 00:15.083 | 363 | music | Wake-up build: A pedal opening filter, accelerating snare roll, riser -> hard cut on the button | Rising noise band + octave-gliding saws |
| 00:15.667 | 377 | sfx | BIG BUTTON clunk + power-up, then machine hum | Click + resonant 620 Hz thock + latch + 48 Hz sub (tanh); saw/sine 'vwoom' rising to 110 Hz; 55 Hz harmonic hum + fan noise |
| 00:16.125 | 388 | music | Relief: calm Fmaj9 pad, then the Act I lo-fi loop returns with soft drums | Detuned-saw pad (slow attack); FM EP reprise from beat 33, so ROADMAP OBSOLETE lands on a downbeat |
| 00:16.292 | 392 | sfx | Second sip + mug down | As Act I |
| 00:16.625 | 400 | sfx | Roadmap ready chime (calm) | F-A-C soft bell arpeggio |
| 00:17.250 | 415 | sfx | Mouse-wheel scroll ticks, accelerating (15 ticks, 7 -> 30 Hz) | Tiny band-passed noise detents + 1.9 kHz ping |
| 00:18.167 | 437 | sfx | Dot-matrix printer / paper feed (to frame 466) | Needle impulse bursts at ~1.3 kHz with dot dropouts convolved with a resonant click, line-feed motor buzz, paper rustle |
| 00:20.458 | 492 | all | NEAR SILENCE: ROADMAP OBSOLETE. | Music, machine hum, bubbles and every reverb tail hard-cut on the frame; room tone dropped ~9 dB |
| 00:21.750 | 523 | sfx | Laptop lid clack | Air puff before the hit, plastic clack band + 300 Hz body + rattle |
| 00:21.792 | 524 | sfx | Cloth: standing (to 532) and hoodie stretch (530-538) | Band-passed noise with slow swell + sparse crackle grains |
| 00:21.833 | 525 | sfx | Chair creak + caster roll | Band-passed pink noise with wheel-bump AM, brown rumble, saw creak |
| 00:22.500 | 541 | sfx | Footsteps on frames 541, 546, 551 | Heel thump (sine + low noise) + sole scuff; floor creak on step 2 |
| 00:23.000 | 553 | sfx | Deep breath in (swells through the breath frame, ends as the whisper starts) | Swept band-passed noise, high-passed |
| 00:23.208 | 558 | voice | Whisper: "Finally. I'm caught up." (ends frame 583.2, slot ends 584) | Microsoft David Desktop (SAPI rate 2); STFT: cepstral envelope (harmonics removed), whisper EQ, magnitude time-fit, random phase resynthesis, 300 Hz HP; dry |
| 00:24.042 | 578 | sfx | Door handle + latch | Two resonant metal clicks with partials, tiny spring squeak |
| 00:24.083 | 579 | sfx | Wooden creak as the flats tip, falling-air whoosh | Jittered stick-slip impulse train through 4 wood resonances; low swept noise |
| 00:24.583 | 591 | sfx | MASSIVE wall slam into the hall | Four-impact flam (slap + low thud), pitch-dropping 50 Hz sub boom, debris; huge FDN hall |
| 00:24.583 | 591 | ambience | Industrial hall: D/A low drone, conveyor clatter+rumble, distant clanks, crowd typing, air | Detuned saws low-passed at 160 Hz; roller impulses at 3.2*belt_speed Hz through metal resonances (pitches up with the belt); modal metal clanks; dense random key-click texture; all into a 4.8 s FDN hall; rises to the acceleration |
| 00:24.708 | 594 | music | Distant choir 'aah' (D major add9) hinting at the finish line; swells on the proud beat | Vibrato saws through four formant band-passes, mostly hall reverb |
| 00:24.875 | 598 | voice | Two-tone PA chime (A5 -> F#5) | Vibraphone-like bell partials with tremolo, through the same PA chain |
| 00:25.010 | 601.2 | voice | PA: "Congratulations. You are now an expert." (ends frame 633.4, slot ends 634) | Microsoft Zira Desktop (SAPI rate 7), pitched down 1.0 st by resampling, ring-mod + comb robot tint, 300-3500 Hz horn band-pass, tanh clip, ~6.5-bit/16 kHz crush, 5-tap hall echo, 3.4 s FDN hall |
| 00:26.458 | 636 | sfx | Alarm riser (two-tone, rising) into 10X | Pulse/saw two-tone with exponential pitch rise + swept noise |
| 00:26.625 | 640 | sfx | Huge acceleration whoosh; conveyor rumble/whine pitch up with belt_speed | Opening low-pass noise sweep, rising saw, sub drop; belt-driven roller rate in the ambience |
| 00:26.625 | 640 | music | ABSURD EPIC climax: Bb - C - Dm - Bb - Csus4/C -> D brass saw-stack progression | 4 detuned saws/note with pitch scoop, delayed vibrato, per-chord low-pass 'blat' envelope (SVF); chord points on the beat grid |
| 00:26.708 | 642 | sfx | Chair yank: zip + thud | Toothed (AM) rising band-pass rasp, then pitch-dropped thud |
| 00:27.083 | 651 | music | Drums build: kick+taiko on the chord points/beats, tom run from the pull-back, snare roll crescendo, reverse crash into black | Synth drums (sine pitch envelopes + filtered noise), reversed crash swell, 32nd octave bass ostinato; 75 ms -12 dB suck-out before black |
| 00:28.000 | 673 | music | FINAL HIT on the cut to black: sub boom + bright detuned D major + noise crash | 9-note x 7-voice supersaw (+/-22 cents) with closing low-pass, 55->28 Hz sub, crash; own 2.2 s FDN tail, faded to digital silence |
| 00:28.542 | 686 | sfx | 'Beta' glitch blip under HUMANITY: STILL IN BETA. | Stuttered square chirps, sample-and-hold + 4-bit quantiser |

## Sound arc (how the jokes are supported)

- **Act I** quiet bedroom: room tone, a slow clock, pen scratches, a warm lo-fi loop, pleasant dings. The
  third notification is an alarm and the loop sags (tape droop) while the smile dies.
- **Act II** the beat grid comes from the speed curve (84 -> 173 bpm). Kick, octave bass, hats, claps and an
  arp enter as speed rises, and the low-pass opens with it. Keys, whooshes, books, cups, papers, toasts,
  fast-forward chatter and a racing clock are layered on top. At AI CAN NOW DO THAT everything is gated to
  nothing on the exact frame, leaving a dry soft ding and three faint ticks; the stab breaks it.
- **Act III** mechanical montage, a chunky button, machine hum, relief pad and the lo-fi loop reprised, so
  ROADMAP OBSOLETE can cut it all to near silence on the downbeat.
- **Act IV** close, dry foley and a whisper, then the slam opens a huge hall. The PA congratulates him, the
  belt accelerates, the brass progression builds, and one final hit lands on black. The tail is faded to digital
  silence before the last frames.
