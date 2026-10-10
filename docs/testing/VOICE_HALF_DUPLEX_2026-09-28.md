# Bluetooth playback and conversational style — 2026-09-28

## Audio behavior

Opt-in `--voice-audio-mode half-duplex` closes capture for the entire spoken reply,
waits for the output profile, plays all TTS segments with output alone, and reopens
capture. Enter stops playback and resumes conversation; it never grants tool
approval. Cancellation, output-open failure, and playback errors restore capture.
Device identity is re-resolved after transitions; an ambiguous or missing device
fails explicitly instead of switching to another microphone or speaker.

Successful external music playback pauses capture until Enter. There is no music
completion event yet. The microphone cannot detect wake words or speech while
closed. Full duplex remains the package default; this Mac's saved configuration
was switched from `full-duplex` to `half-duplex` for the requested trial.

## Physical SRS-XB13 test on this Mac

Both input and output were the user's SRS-XB13. No microphone audio was saved or
uploaded; capture frames were only counted. Playback used the existing Japanese
sample in `~/Downloads/yumi-voice-20260928/japanese-after.wav`.

1. The first output-only implementation requested 48 kHz PCM, but macOS still
   reported 8 kHz / 1 channel. Application sample rate was misleading.
2. CoreAudio's process API identified `com.apple.Sound-Settings.extension` as an
   active input client even with no voice terminal. Closing the Sound window
   removed that input client.
3. With both Yumi streams closed, macOS took about two seconds to change from
   8 kHz to 44.1 kHz. Opening output after only 600 ms kept it in the low-rate
   profile. No audio-service restart or system device-selection change was needed.
4. The final implementation polls the public CoreAudio native output rate while
   both streams are closed (bounded to four seconds), then prefers that rate for
   playback. Actual hardware result:

| Phase | Native output | Input frames |
| --- | --- | ---: |
| Listening | 8 kHz / 1 channel | 3 |
| Japanese reply | 44.1 kHz / 2 channels | 0 |
| Listening restored | 8 kHz / 1 channel | 6 |

The reader returned suspended status 201 times during the output window. Output
and input streams closed cleanly afterward. This verifies the native format
transition and capture restoration, not subjective Japanese accent or audio
quality on every Bluetooth device. Other platforms do not have native-format
verification and still need hardware testing. Other apps can prevent the switch.

## Prompt behavior

Catalog version 1.3.0 changes both general conversation and spoken delivery:
connected prose for ordinary conversation, no reflexive service offers or action
menus, restrained acknowledgement, and no invented human identity or senses.
Lists remain appropriate when requested or needed to explain real steps. Tool
instructions and runtime confirmation rules remain in force.

An initial live comparison showed that merely requesting shorter prose still
produced “need help?” endings. After making the small-talk rule explicit and
adding short examples, a second run used the configured `deepseek-v4-pro` model:
seven cases, two generations each (Chinese, English, Japanese, requested steps,
and a simulated light tool). Casual greetings included “回来啦。” and “Welcome
home.” Some replies asked a relevant conversational question. Neither of the two
action trials skipped the expected `lamp_set_power(on=true)` call. No actual
light function was executed. Explicit three-step requests still returned lists.

This is a small qualitative check, not a general guarantee of natural dialogue.
Raw local results: `/tmp/yumi-natural-dialogue-eval-first.json` and
`/tmp/yumi-natural-dialogue-eval-final.json`. Provider credentials were never
included in the reports.

## Regression checks

146 targeted tests pass across voice, prompt composition/catalog, cancellation,
music feedback, voice-message routes, and TTS providers. New cases cover profile
waiting and bounded fallback, native device discrimination, output PCM integrity,
input restoration on cancellation/failure, Enter interruption and confirmation
isolation, verified music pausing, and CLI flag validation. Ruff and focused
Pyright checks pass. Native microphone and speaker testing remains macOS-only.

## Deployment

Deployed `yumi-nexus:macmini-20260928-voice-r6` to all six application services;
API is healthy. Local/public health and the saved voice credential's authenticated
capabilities endpoint return 200. The installed prompt catalog is version 1.3.0,
hash `feb17cc9f0a1cd76`. The r5 release/image and previous compose file remain
available for rollback. Local editable `yumi` picks up the client changes after
restart. This is a local Docker/source deployment, not a PyPI release.
