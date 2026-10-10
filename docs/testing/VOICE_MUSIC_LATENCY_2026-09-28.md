# Named-song latency, history and English defaults — 2026-09-28

## Observed baseline

The reported Japanese request ("それ、夜にかけるを聞きたい。") took 12,764 ms
server-side: model rounds of 3155, 3224 and 2909 ms; catalog search 849 ms;
playback 256 ms. Playback returned Apple Music error 6, and the third model round
explained the failure. This total excludes speech endpointing and transcription.
The model selected the requested YOASOBI track, despite unnecessarily mentioning
an older song. The first tool schema selection was empty after semantic retrieval
timed out; the offline capability vocabulary covered one Japanese spelling of
"want to listen", but missed the spelling in this transcript.

## Changes

- Room Control registers `music_play_request(title, artist, with_lights)`: search
  and play in one tool invocation only when there is one exact normalized
  title/artist match. Width, case and punctuation are normalized. Multiple catalog
  IDs, artists/versions, missing matches and spelling differences return candidates
  without playing. Existing `music_play` handles subsequent explicit selection.
- Both playback entry points use silent completion and automatic playback-status
  monitoring. Errors are not hidden. No automatic retry of native playback errors
  was added.
- Offline Japanese music routing includes the observed spelling and common
  playback requests. Large-catalog regressions cover the original utterance.
- Prompt catalog 1.3.1 prioritizes the latest explicit action, treats old guesses
  and device snapshots as historical, and favors a combined tool when exposed.
- Voice context retains all previous song IDs and candidate order but removes
  artwork URLs and verbose music-device dumps. Stored history and current-turn
  results are unchanged; pronouns such as "that one" still have context.
- Default terminal copy and built-in conversation examples are English. Input
  aliases for supported languages remain. Assistant reply-language settings are
  separate from terminal copy. The 2.5-second thinking-pause default is unchanged.

## Validation

208 focused agent tests and 16 music bridge tests passed. Ruff and focused
Pyright passed. The real SDK registration test confirms all 14 tools and both
terminal playback policies. Candidate tests reject ambiguous artists, versions,
misspellings, absent results and search failures without starting playback.

Two isolated live conversations first discussed an older song, then requested
YOASOBI in Japanese with lights disabled. Both used one model round and only
`music_play_request`; neither referenced the older song in its output.

| Microphone | HTTP request to tool-complete response | Server turn | Model | Combined tool |
| --- | ---: | ---: | ---: | ---: |
| Closed | 5.252 s | 5.118 s | 3.367 s | 1.112 s |
| SRS-XB13 open at 8 kHz | 4.477 s | 4.363 s | 2.982 s | 0.170 s |

These are two warm-path observations, not a latency guarantee or a controlled
speedup ratio. The original failed turn included an extra error-explanation round.
The table does not measure speech recognition, the user's pause, or audible onset.
MusicKit returned a transitional `paused` snapshot at tool completion.

A third test exercised the actual voice client, real Nexus and SRS-XB13 together
using fixed text (no microphone upload). Terminal completion closed capture,
native output changed from 8 kHz to 44.1 kHz after about two seconds, and the
authenticated monitor then confirmed `playing`. No TTS request was made. Test
playback was stopped and its queue cleared afterward; lights were disabled.

An initial status-only query in the same acceptance run had a 104.105-second model
round, while its tool took 84 ms. Removing a model round reduces ordinary latency
but does not eliminate provider stalls. Apple Music error 6 was not reproduced
in these successful tests and is not claimed fixed.

## Deployment

All six local Nexus application services use `yumi-nexus:macmini-20260928-voice-r9`.
Prompt catalog hash: `b58f160486dc0102`. Release snapshot:
`/Users/wenxijiao/Services/nexus/releases/release-20260928-222716-voice-music-latency`.
The Room Control Python adapter was updated and its original signing identity
preserved; deep signature verification passed. App backup:
`/Users/wenxijiao/Services/nexus/backups/roomcontrol-music-latency-20260928-222757`.

The previous image/source and compose file remain available for rollback. The
old voice process was stopped for testing; rerun `yumi --voice` to load the local
editable client. No PyPI publication was performed.
