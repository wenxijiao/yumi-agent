# Silent tool completion — 2026-09-28

## Contract and cause

Music playback previously depended on a snapshot reporting `state: playing`.
The real music bridge can return `ok: true` with a transitional `paused` snapshot
before playback starts. That missed the old heuristic, allowed a spoken reply,
and reopened the Bluetooth microphone afterward, restoring the 8 kHz profile.

Python SDK registration and local tools now accept `reply_on_success=False`.
This is trusted registration metadata, removed from the model-facing schema.
After every call in a batch succeeds with this policy and a JSON object containing
`ok: true` without an error, the server emits `turn_complete` and skips the next
model round. Missing results, denied calls, exceptions, unsuccessful payloads,
or batches containing ordinary tools keep the normal feedback path.

The voice client closes capture immediately on the matching completion event,
drains the remaining stream, skips TTS, and waits for Enter. This applies to both
audio modes. It also handles capture reads already pending when streams close.
The music bridge opts in only `music_play`; search, queue and status retain their
normal responses. Terminal tools should be called after other requested work.

## Verification

- 224 focused agent tests passed, including actual dispatch/SDK registration,
  structured result serialization, batch policy, failures, stream completion,
  capture-close races, voice, prompt and cancellation regressions.
- 12 music backend tests passed, including the actual registration payload.
- Ruff, focused Pyright and changed-file formatting checks passed.
- A real authenticated Nexus request through the installed music bridge returned
  Apple Music error 6 on the first attempt. It was not silently treated as success.
- A second real request successfully invoked `music_play` and emitted
  `turn_complete` with `reply: none` and `voice_capture: pause`. There was no
  subsequent model phase or assistant text. The transitional playback snapshot
  still said `paused`, demonstrating that the explicit policy handles this case.
- The test restored the initial stopped/empty music queue afterward; music-linked
  lighting was disabled during the probe.

## Physical Bluetooth check

Using SRS-XB13 for both input and output, a controlled completion event closed
the real Yumi streams while an external player continued the existing Japanese
audio sample. Native CoreAudio output changed from 8 kHz to 44.1 kHz after about
two seconds, with zero TTS requests. Capture stayed closed during and after
playback. Microphone frames were discarded, not saved or uploaded.

The controlled hardware check and real Nexus/Apple Music check were separate;
the successful real MusicKit call was performed with the microphone closed.
This verifies the two integration boundaries, not every device or platform.
There is no music-end event yet: Enter resumes capture, and wake words cannot
work while the microphone is closed. Apple Music's intermittent error 6 remains
an upstream playback failure, reported through the normal error path.

## Deployment

The local Nexus Docker application services run
`yumi-nexus:macmini-20260928-voice-r7`. Local/public health checks and authenticated
capabilities passed, including `silent_tool_completion: true`. The installed
Room Control app received the music registration and Python SDK updates; its
original signing identity was preserved and signature verification passed.

- Release: `/Users/wenxijiao/Services/nexus/releases/release-20260928-211151-silent-tool-completion`
- App backup: `/Users/wenxijiao/Services/nexus/backups/roomcontrol-silent-tool-20260928-211237/Room Control.app`

The local editable voice client also includes a fix for reporting an unbuffered
HTTP error from the TTS stream. That client-only follow-up was made after the r7
image build. Restart `yumi --voice` to load the current local client. This is a
local source/Docker deployment, not a PyPI publication.
