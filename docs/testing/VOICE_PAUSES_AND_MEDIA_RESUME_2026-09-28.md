# Speech pauses and automatic music recovery — 2026-09-28

## Behavior

The standalone voice client now defaults to 2500 ms of trailing silence instead
of 800 ms. `--voice-silence-ms` accepts 800–10000 ms. Recognized explicit hesitation
endings get four extra seconds after STT; this is a small deterministic heuristic,
not a general semantic turn detector. Speech resumed before submission to chat
retains and retranscribes the preceding audio instead of losing the first phrase.
The continuous segment limit is 60 seconds and retained PCM is bounded to 90.

Terminal Room Control music playback binds a read-only monitor to the exact
device in the server's durable turn trace. The client closes the microphone,
queries playback every two seconds, then recreates audio and opens an awake
follow-up window when the queue ends. No model or TTS call is needed for monitoring.
Enter can resume early, including during a slow status request. An initial paused
snapshot alone, an unknown state, or disconnection never proves completion.
There is a 10-second startup grace plus repeated inactive-sample checks. Ended
queues require two samples; pausing after observed playback requires three.

The monitor is owner-bound, expires after 24 hours, and rechecks tool visibility
and confirmation requirements before every read. Clients cannot choose a tool,
device or URL. The voice credential only gains the specific playback-status route.
Other terminal tools retain manual recovery. The microphone remains unavailable
for Hey Yumi during music when the same Bluetooth speaker supplies input/output.

## Checks

- 247 focused agent tests and 10 enterprise route-permission tests passed.
- Tests exercise paused starts, unknown states, real RPC dispatch, ownership and
  permission changes, persisted monitor binding, early Enter cancellation, audio
  recreation, a thinking pause in one recording, and resuming during pending STT
  without sending a partial chat request.
- Ruff, focused Pyright (zero warnings), and `git diff --check` passed.

## SRS-XB13 hardware

A controlled HTTP stream and a real external player exercised `run_client` with
the actual HalfDuplexAudio devices. Capture started at 8 kHz; after streams closed,
native output stayed at 44.1 kHz during playback. When the 7.5-second sample ended,
the monitor completed after its grace/debounce interval, audio was recreated,
and the client entered its awake follow-up state automatically. Reopened capture
returned to the expected 8 kHz Bluetooth input/output profile. No TTS was requested.
The test then closed capture. Microphone frames were discarded, not uploaded.

## Live Nexus and Room Control

An isolated session first confirmed an empty, stopped queue. Real `music_play`
then succeeded with lighting disabled and returned a monitor ID. The authenticated
status endpoint reported `playing`; the client wait remained pending throughout
15 seconds of real playback. A cleanup `music_stop` restored the original stopped,
empty queue. Status became `ended` and the client wait returned automatically.

This live test used explicit stop; the separate physical-player test used natural
completion. A full Apple Music track was not played through to natural completion
in this acceptance run. Combined checks cover real server/bridge status and actual
audio-device recovery; they do not establish far-field or accent accuracy.

## Deployment

All six local Nexus application services run `yumi-nexus:macmini-20260928-voice-r8`.
API health is healthy and authenticated capabilities advertise
`media_playback_watch: true`. The previous r7 image and compose snapshot remain
available. Source snapshot:
`/Users/wenxijiao/Services/nexus/releases/release-20260928-215915-voice-resume`.

The old local `yumi --voice` process was stopped for testing. Restart that command
to load the editable client. No PyPI release or Room Control app rebuild was needed.
