# Bluetooth music startup, turn language and standby — 2026-09-28

## Changes

- Capable half-duplex macOS clients opt into `media_prepare` before terminal
  `music_play` / `music_play_request` dispatch. After normal tool permission and
  confirmation checks, the server waits for an account-bound, one-shot readiness
  acknowledgement. The client releases both streams and observes two consecutive
  native output rates >= 32 kHz before acknowledging. This is a route check, not
  an arbitrary sleep or an application sample-rate override.
- Negative readiness, expiry and cancellation do not execute the tool batch.
  Capture resumes on preparation/playback failure. Successful silent completion
  keeps capture closed and retains the existing playback-end monitoring.
- Automatic reply language is anchored to the current request in both system
  guidance and the current provider message. Chinese/English request grammar is
  distinguished from a Japanese song title. Explicit saved language and explicit
  translation requests retain priority. Stored conversation content is unchanged.
- Supported OpenAI transcription models receive original-language, non-translation
  guidance; no previous-turn language is forced and no STT model was changed.
  Prompt support was checked against the installed SDK and official documentation:
  https://developers.openai.com/api/docs/guides/speech-to-text
- Complete common farewells, including `Finish. See you later.` and
  `I'm heading out now; let's leave our chat here for the moment.`, enter standby
  in the client before chat generation. Negations, quotations, song titles and
  compound action requests are excluded from this shortcut.
- `end_voice_conversation` is visible only to capable active voice sessions. Its
  verified success emits `voice_standby`, with no further model round or TTS.
  Wake detection remains available; this differs from releasing the microphone
  for music. A focused lifecycle instruction explains this effect to the model.

## Verification

286 focused agent tests (285 before the final extra farewell regression) and
12 enterprise route-permission tests passed. Ruff, focused Pyright and diff
whitespace checks passed. Coverage includes owner isolation, stale/duplicate
acknowledgements, timeouts, cancellation, route failure, capture restoration,
no TTS over music, voice-only tool visibility, and farewell false positives.

A real SRS-XB13 / Nexus / Room Control run began with native 8 kHz input/output.
The voice client observed native 44.1 kHz BEFORE posting speaker readiness. Only
then did the server invoke music playback. The playback monitor reported playing,
output stayed at 44.1 kHz, and no TTS was requested. Test playback was stopped and
its queue cleared; lights were disabled. Fixed text drove this test, with no
microphone recording uploaded. This verifies ordering on this Mac/speaker, not
an acoustic guarantee for every Bluetooth device.

Live language tests switched Japanese -> English -> Chinese with a Japanese
song title. Replies followed the respective current request languages. A known
English audio fixture transcribed as `Hello, how are you today?`. The reported
original greeting was consistently retranscribed as `Hello, 你好吗?` by both mini
and full transcription models. The user could not recall whether it was spoken
in English or mixed languages, so this is not treated as proof of an ASR defect
or as proof that arbitrary ASR errors are resolved.

Live Nexus requests `Please stop this voice conversation now and return to
standby.` and `先聊到这儿吧，我去忙点别的，不用继续听我说了。` invoked the end tool
and emitted standby. Current DeepSeek sometimes answers an indirect English
farewell without invoking the tool, even when the schema/instruction is present;
common unambiguous forms therefore use the deterministic client shortcut.
Semantic tool selection for arbitrary phrasing is still model-dependent.

## Deployment and limits

The local editable CLI and Docker Nexus services contain the fixes. r9, r10 and
r11 images/source snapshots and compose backups are retained for rollback.
The readiness rendezvous is worker-local, like existing chat cancellation;
multiple API workers require routing affinity or shared rendezvous storage.
Non-macOS devices without native route verification keep the prior behavior.
No PyPI publication or Room Control application change was needed for this patch.
