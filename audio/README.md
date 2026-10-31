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
- Integrated loudness: -15.0 LUFS (ITU-R BS.1770 K-weighted, gated); sample peak -1.05 dBFS; true peak ~-1.05 dBTP
- Dead stop (frames 243-284): -37.4 dBFS RMS (-43.0 dBFS after the soft ding)
- Near silence (frames 495-530): -60.6 dBFS RMS, peak -48.7 dBFS
- Limiter: max 6.3 dB of gain reduction (frame 683), 3.5% of samples above 3 dB (climax drum transients and the final hit)
- Digital silence from sample 1,429,995 (frame 716) to the end

Per-second level of the final mix (RMS dBFS, and short-term loudness over the 3 s ending at that second):

| Second | Frames | RMS dBFS | Short-term LUFS |
|---|---|---|---|
| 0-1 | 1-24 | -24.7 | - |
| 1-2 | 25-48 | -24.9 | - |
| 2-3 | 49-72 | -25.2 | -22.8 |
| 3-4 | 73-96 | -24.2 | -22.4 |
| 4-5 | 97-120 | -21.3 | -20.3 |
| 5-6 | 121-144 | -25.3 | -20.4 |
| 6-7 | 145-168 | -23.7 | -20.5 |
| 7-8 | 169-192 | -21.7 | -21.9 |
| 8-9 | 193-216 | -17.8 | -19.5 |
| 9-10 | 217-240 | -13.0 | -15.4 |
| 10-11 | 241-264 | -24.1 | -15.6 |
| 11-12 | 265-288 | -19.6 | -15.7 |
| 12-13 | 289-312 | -12.3 | -14.2 |
| 13-14 | 313-336 | -16.7 | -13.2 |
| 14-15 | 337-360 | -15.1 | -12.7 |
| 15-16 | 361-384 | -17.9 | -15.2 |
| 16-17 | 385-408 | -22.2 | -16.7 |
| 17-18 | 409-432 | -22.7 | -19.1 |
| 18-19 | 433-456 | -22.5 | -20.2 |
| 19-20 | 457-480 | -23.9 | -20.7 |
| 20-21 | 481-504 | -25.7 | -21.3 |
| 21-22 | 505-528 | -60.6 | -24.0 |
| 22-23 | 529-552 | -29.1 | -27.1 |
| 23-24 | 553-576 | -28.4 | -28.2 |
| 24-25 | 577-600 | -17.0 | -21.2 |
| 25-26 | 601-624 | -12.3 | -14.9 |
| 26-27 | 625-648 | -15.5 | -13.4 |
| 27-28 | 649-672 | -11.4 | -10.8 |
| 28-29 | 673-696 | -10.6 | -10.3 |
| 29-30 | 697-720 | -16.9 | -10.7 |

## Cue sheet

Times are from the start of the film (frame 1 = 00:00.000). Stem = where the sound lives.

| Time | Frame | Stem | Sound | How it was synthesised |
|---|---|---|---|---|
| 00:00.000 | 1 | ambience | Room tone (air, distant city rumble, mains hum, one car pass) | Pink + brown noise, low/high-passed, slow traffic swell, 60/120 Hz sines; drops ~9 dB at frame 495, cut under the wall slam at 597 |
| 00:00.000 | 1 | sfx | Wall clock tick-tock (1 Hz, then racing) | Noise-burst + sine ping; rate = 1 + 14*speed^2.6 Hz, from speed.py |
| 00:00.000 | 1 | music | Lo-fi loop: Fmaj9 / Am9 / Dm9 / Bbmaj9, original EP melody, warm pad, vinyl crackle | FM electric piano (1:1 bark + 14:1 tine) on the speed.py beat grid, tape wow (variable delay), detuned-saw pad |
| 00:00.292 | 8 | sfx | Pen writes LEARN AI. (stroke per letter part) | Speed-tracking band-passed friction noise (time-varying SVF), paper-tooth AM, pen-down ticks |
| 00:02.208 | 54 | sfx | Confident underline + flick | One long pen stroke with a fast flick |
| 00:03.042 | 74 | sfx | Coffee: mug lift, slurp, gulp | Band-passed noise with bubbly AM and rising centre, chirped gulp |
| 00:03.625 | 88 | sfx | Mug set down | Pitched thunk + wood knock + three ceramic partials |
| 00:03.792 | 92 | sfx | Notification ding: NEW MODEL RELEASED. | Two-note sine bell (partials 1/2/3), in key with the loop |
| 00:04.292 | 104 | sfx | Notification ding: NEW AGENT FRAMEWORK. | Two-note sine bell (partials 1/2/3), in key with the loop |
| 00:04.750 | 115 | sfx | Alert: NEW BENCHMARK. EVERYTHING CHANGED. | Triple pulse-wave beep on a tritone cluster + low thump |
| 00:05.292 | 128 | music | Loop sours to Bbm6 with a tape-droop pitch sag | Variable-delay pitch bend (~6%) on the minor iv chord (beat 8) |
| 00:05.833 | 141 | sfx | Pen scribbles FASTER (faster, harder strokes) | As above, frantic stroke timing |
| 00:06.317 | 152.6 | music | C9sus4 -> C7b9 turnaround into Act II | Same EP/pad, tension voicings |
| 00:06.500 | 157 | sfx | Keyboard: 133 key clicks on every speed.py key press (+ ghost strokes), Acts II-IV | Per-key random noise click + pitched body + bottom-out transient; density from typing_phase; muted from the dead stop |
| 00:06.868 | 165.8 | music | Rhythm layer on the beat grid (D minor): kick, pulsing octave bass, then hats, claps, 16th arp | Layers enter as speed rises; bass/arp low-pass cutoff = 170*(1+40*speed^2.2) Hz (time-varying SVF), kick side-chain |
| 00:07.417 | 179 | sfx | 8 UI toast ticks | Sine chirp pop + 3.3 kHz tick |
| 00:07.500 | 181 | sfx | Whooshes on 7 head snaps (frames 181, 188, 193, 197, 200, 203, 205) | Pink noise through a swept band-pass SVF, peak on the snap frame, panned laptop<->monitor |
| 00:08.083 | 195 | sfx | 10 book thumps (land = spawn + 5) | Pitch-dropped sine thud + band-passed slap + page flutter |
| 00:08.292 | 200 | sfx | 4 paper swishes | Rising band-passed noise, 0.27 s |
| 00:08.458 | 204 | sfx | 5 cup clinks (settle = spawn + 2) | Inharmonic ceramic partials + contact tick |
| 00:08.667 | 209 | sfx | Tutorial voice fast-forward chatter 2x -> 4x -> 16x (no real speech) | Glottal saw + 3 time-varying formant SVFs + fricative bursts; rate/pitch/formants scale with speed-up |
| 00:09.250 | 223 | music | Chromatic bass climb, snare roll and riser into the stop | Swept noise + rising detuned saws |
| 00:10.042 | 242 | all | DEAD STOP: AI CAN NOW DO THAT FOR YOU. | Music, keys, clutter and their reverb tails hard-gated on the frame; only room tone, a soft dry ding and 3 faint clock ticks on beats 19-21 |
| 00:11.833 | 285 | music | Harsh orchestral stab + alert | D/Eb/Ab cluster saw-brass + strings, timpani boom, crash; minor-2nd pulse alert |
| 00:12.375 | 298 | sfx | Silent-scream whoosh-roar (no voice) | Resonant swept noise + brown rumble, tanh drive, flanger; cut on frame 311 |
| 00:12.375 | 298 | music | Frantic return: 180 bpm drums, 16th bass with b2 grit, tremolo string cluster, tom fill | Beat-grid sequenced; hard cut at the idea (frame 311) |
| 00:12.958 | 312 | sfx | 'Idea' sparkle | Rising five-note bell arpeggio + high shimmer |
| 00:13.250 | 319 | sfx | Machine assembly: servo whir + ratchet + metal lock on each of 9 parts (frames 319, 322, 325, 328, 331, 334, 337, 340, 343) | Gliding saw/pulse motor through band-pass; accelerating noise clicks; modal metal impact landing on the frame |
| 00:13.498 | 324.9 | music | Montage groove (Dm-Bb-F-C) under the build | Kick/clap/hat, 16th octave bass and arp on the beat grid |
| 00:14.542 | 350 | sfx | Machine wakes: rising whine, accelerating relay clicks, data-bubble trickles | Exponential sine/saw sweep with speeding tremolo; HP noise clicks; random chirped sine 'bloops' (continue until the cut) |
| 00:14.542 | 350 | music | Wake-up build: A pedal opening filter, accelerating snare roll, riser -> hard cut on the button | Rising noise band + octave-gliding saws |
| 00:15.083 | 363 | sfx | BIG BUTTON clunk + power-up, then machine hum | Click + resonant 620 Hz thock + latch + 48 Hz sub (tanh); saw/sine 'vwoom' rising to 110 Hz; 55 Hz harmonic hum + fan noise |
| 00:15.667 | 377 | music | Relief: calm Fmaj9 pad, then the Act I lo-fi loop returns with soft drums | Detuned-saw pad (slow attack); FM EP reprise from beat 32, so ROADMAP OBSOLETE lands on a downbeat |
| 00:15.792 | 380 | sfx | Second sip + mug down | As Act I |
| 00:16.125 | 388 | sfx | Roadmap ready chime (calm) | F-A-C soft bell arpeggio |
| 00:17.458 | 420 | sfx | Mouse-wheel scroll ticks, accelerating (8 ticks, 7 -> 30 Hz) | Tiny band-passed noise detents + 1.9 kHz ping |
| 00:18.000 | 433 | sfx | Dot-matrix printer / paper feed (to frame 468) | Needle impulse bursts at ~1.3 kHz with dot dropouts convolved with a resonant click, line-feed motor buzz, paper rustle |
| 00:20.583 | 495 | all | NEAR SILENCE: ROADMAP OBSOLETE. | Music, machine hum, bubbles and every reverb tail hard-cut on the frame; room tone dropped ~9 dB |
| 00:22.333 | 537 | sfx | Laptop lid clack | Air puff before the hit, plastic clack band + 300 Hz body + rattle |
| 00:22.375 | 538 | sfx | Chair creak + caster roll | Band-passed pink noise with wheel-bump AM, brown rumble, saw creak |
| 00:22.375 | 538 | sfx | Cloth: standing (to 546) and hoodie stretch (546-546) | Band-passed noise with slow swell + sparse crackle grains |
| 00:22.917 | 551 | sfx | Footsteps on frames 551, 555, 559 | Heel thump (sine + low noise) + sole scuff; floor creak on step 2 |
| 00:23.375 | 562 | sfx | Deep breath in (swells through the breath frame, ends as the whisper starts) | Swept band-passed noise, high-passed |
| 00:23.458 | 564 | voice | Whisper: "Finally. I'm caught up." (ends frame 587.2, slot ends 588) | Microsoft David Desktop (SAPI rate 2); STFT: cepstral envelope (harmonics removed), whisper EQ, magnitude time-fit, random phase resynthesis, 300 Hz HP; dry |
| 00:24.292 | 584 | sfx | Door handle + latch | Two resonant metal clicks with partials, tiny spring squeak |
| 00:24.333 | 585 | sfx | Wooden creak as the flats tip, falling-air whoosh | Jittered stick-slip impulse train through 4 wood resonances; low swept noise |
| 00:24.833 | 597 | sfx | MASSIVE wall slam into the hall | Four-impact flam (slap + low thud), pitch-dropping 50 Hz sub boom, debris; huge FDN hall |
| 00:24.833 | 597 | ambience | Industrial hall: D/A low drone, conveyor clatter+rumble, distant clanks, crowd typing, air | Detuned saws low-passed at 160 Hz; roller impulses at 3.2*belt_speed Hz through metal resonances (pitches up with the belt); modal metal clanks; dense random key-click texture; all into a 4.8 s FDN hall; rises to the acceleration |
| 00:24.958 | 600 | music | Distant choir 'aah' (D major add9) hinting at the finish line; swells on the proud beat | Vibrato saws through four formant band-passes, mostly hall reverb |
| 00:25.125 | 604 | voice | Two-tone PA chime (A5 -> F#5) | Vibraphone-like bell partials with tremolo, through the same PA chain |
| 00:25.260 | 607.2 | voice | PA: "Congratulations. You are now an expert." (ends frame 639.4, slot ends 640) | Microsoft Zira Desktop (SAPI rate 7), pitched down 1.0 st by resampling, ring-mod + comb robot tint, 300-3500 Hz horn band-pass, tanh clip, ~6.5-bit/16 kHz crush, 5-tap hall echo, 3.4 s FDN hall |
| 00:26.667 | 641 | sfx | Alarm riser (two-tone, rising) into 10X | Pulse/saw two-tone with exponential pitch rise + swept noise |
| 00:26.833 | 645 | sfx | Huge acceleration whoosh; conveyor rumble/whine pitch up with belt_speed | Opening low-pass noise sweep, rising saw, sub drop; belt-driven roller rate in the ambience |
| 00:26.833 | 645 | music | ABSURD EPIC climax: Bb - C - Bb - Csus4/C -> D brass saw-stack progression | 4 detuned saws/note with pitch scoop, delayed vibrato, per-chord low-pass 'blat' envelope (SVF); chord points on the beat grid |
| 00:26.917 | 647 | sfx | Chair yank: zip + thud | Toothed (AM) rising band-pass rasp, then pitch-dropped thud |
| 00:27.250 | 655 | music | Drums build: kick+taiko on the chord points/beats, tom run from the pull-back, snare roll crescendo, reverse crash into black | Synth drums (sine pitch envelopes + filtered noise), reversed crash swell, 32nd octave bass ostinato; 75 ms -12 dB suck-out before black |
| 00:28.083 | 675 | music | FINAL HIT on the cut to black: sub boom + bright detuned D major + noise crash | 9-note x 7-voice supersaw (+/-22 cents) with closing low-pass, 55->28 Hz sub, crash; own 2.2 s FDN tail, faded to digital silence |
| 00:28.625 | 688 | sfx | 'Beta' glitch blip under HUMANITY: STILL IN BETA. | Stuttered square chirps, sample-and-hold + 4-bit quantiser |

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
