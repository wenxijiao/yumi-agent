# Voice acceptance test — 2026-09-26

Status: **Nexus conversation pipeline works; wake-word reliability is not ready for general release.**

Environment: macOS, SRS-XB13 Bluetooth microphone/speaker, negotiated 8 kHz
hands-free audio. Client is the working-tree 0.0.5 implementation. Nexus is the
local Docker deployment exposed at `api.yumi.nexus`.

## Verified

- Running the actual `yumi --voice` CLI presents local/Nexus choices.
- Browser device authorization completes; restarting reuses the saved credential.
- Public service health and authenticated voice capabilities respond successfully.
- 81 core/voice regression tests and 7 enterprise voice-permission tests pass.
- A synthesized English WAV was uploaded to the real Nexus STT endpoint, accurately
  transcribed, answered by the real chat model, synthesized, and sent to the physical
  output device. Complete turn: **12.87 seconds**, with 128 capture frames received
  while processing and playing the reply. This is one observation, not a latency benchmark.
- A follow-up utterance injected into the real client state machine, without a new
  wake phrase, created a real Nexus turn. During spoken counting, a replacement
  utterance interrupted playback, received a server cancellation acknowledgement,
  and got the requested new answer. Combined test: **44.57 seconds**.
- Separately, an actual in-flight chat request was cancelled after its first
  `turn_phase` event. Server acknowledgement: **98 ms**.

The follow-up/interruption tests injected synthesized PCM into the client; they
validate state transitions, HTTP requests and device playback, not a human's
far-field barge-in experience. Audio output completed at the device API; no human
listening assessment was collected. Test messages remain in the account's personal
conversation; they requested speech-only responses and no tool actions.

## Wake-word failures

With the shipped model and default keyword parameters:

| Input | 16 kHz | Downsampled to 8 kHz, then resampled to 16 kHz |
| --- | --- | --- |
| Samantha: “Hey Yumi” | Hit | Miss |
| Samantha: “Hey Yumi, tell me the time” | Hit | Hit |
| Eddy (English US): “Hey Yumi” | Miss | Miss |
| Eddy (English US): “Hey Yumi, tell me the time” | Miss | Miss |

Six negative phrases, each in both voices at both sample rates, produced no hits
in this small synthetic set. These samples do not establish a population accuracy
or false-alarm rate.

An experimental keyword score of 2 / threshold of 0.1 recovered Samantha's narrowband
wake, but still missed Eddy. The production settings were **not** changed based on
this limited sample; merely lowering the threshold does not solve speaker variation.

Playing a test phrase through the Mac mini speaker into the room did not trigger
the active SRS-XB13 client. This physical test is sensitive to device distance,
volume, microphone gain and Bluetooth processing; it is not enough to isolate the
cause to the wake model alone.

## Remaining acceptance work

1. Collect human “Hey Yumi” samples across voices/accents and normal microphone
   conditions; evaluate keyword tokenization and the selected model against them.
2. Establish microphone signal level and Bluetooth hands-free behavior before
   tuning wake parameters. Provide device diagnostics and a clear fallback path.
3. Test real-speaker double talk and echo rejection, including speech during TTS.
4. Test Windows/Linux devices and publishing/install flow separately.

Do not describe the current implementation as generally ready just because the
mocked regression tests and one synthetic wake sample pass.

The follow-up physical signal probe received nonzero microphone audio: raw PCM
RMS peaked at 2948.7 and processed RMS at 1537.7 (int16 units); no wake hit occurred.
This rules out completely silent capture during that probe, but does not prove
adequate speech intelligibility. Raw microphone audio was not saved.

All test capture/playback sessions were stopped afterward. The Nexus device login
is retained for the next `yumi --voice` run.

## Follow-up: audible feedback and music behavior

- 123 targeted automated tests pass after adding local wake/sleep/pause/retry
  cues, conversation-ending phrases, explicit microphone release, and structured
  music playback feedback. Ruff and targeted Pyright pass.
- Tests cover the actual capture loop returning and closing audio/HTTP resources
  on pause, cue replacement, known empty-transcription 422 versus other errors,
  and playing/paused/unknown/missing music states. No real lights or player actions
  were executed for these regression tests.
- Music speech suppression requires a successful Room Control action result with
  `ok: true` and `playback.state: playing`. Music status/search tools do not mute
  answers. Voice-only prompt guidance removes unsupported manual-play and
  lighting claims. Playback-finished notifications are not implemented.
- This change does not remove the Bluetooth hands-free limitation. With only the
  SRS-XB13 microphone, wake-only standby still holds the microphone open. The new
  pause command releases it until Enter resumes capture. Human assessment of the
  cues, improved barge-in threshold and audio-profile recovery is still required.

Deployed the feedback update as `yumi-nexus:macmini-20260926-voice-r4`. All six
application services started; API is healthy. Local/public `/health` and saved
voice-credential `/chat/capabilities` returned 200. A container-side smoke check
confirmed structured playback feedback and prompt catalog 1.2.2. The local CLI
uses the editable source; an already-running voice process must be restarted.
