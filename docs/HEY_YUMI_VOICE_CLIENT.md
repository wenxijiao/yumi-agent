# Hey Yumi voice

`yumi --voice` runs on the computer with the microphone. Choose **1: Local model**
or **2: Sign in to Yumi Nexus**. The fixed wake phrase is **Hey Yumi**.

## Try the current source

```sh
pip install -e .
yumi --voice
```

Voice dependencies are included in the base package. On first use Yumi downloads
and verifies a pinned 17 MB sherpa-onnx wake model into `~/.yumi/models/wake/`.
No access key or manually generated keyword file is needed. The normal device
input/output sample rates are negotiated and converted automatically.

The `packaging/yumi` install alias is prepared for `pip install yumi`. Both it and
`yumi-agent` 0.0.5 must be published before that command works for new users; the
previous PyPI 0.0.4 does **not** contain this voice client. `release-alias.yml`
requires separate PyPI project ownership and Trusted Publisher setup. The alias
contains no Python modules: only `yumi-agent` owns the `yumi` command.

## Conversation

Terminal prompts and default program copy are English. Speech recognition and
conversation controls still accept supported languages, and assistant replies
follow the account's language preference/current utterance. A fresh named-song
request takes precedence over an earlier choice; history remains available for
references such as "that one". Historical music tool messages retain candidate
IDs and order but omit artwork URLs and verbose device snapshots from voice
model context. Stored conversation history is unchanged.

Room Control's `music_play_request(title, artist, with_lights)` combines catalog
search and playback in one model call. Only a unique exact title/artist match is
played automatically. Ambiguous versions or spelling differences return
candidates for selection, and playback failures remain visible. This reduces
model round trips without changing the thinking-pause timeout.

- Say **Hey Yumi** or press **Enter**, then speak. After waking, Yumi waits up to ten
  seconds for speech; silence alone is never uploaded. A short rising local tone
  confirms wake-up; a falling tone marks the end of the conversation. Wake feedback
  is 340 ms at a higher default level; speech received during the wake tone is
  buffered rather than dropped. A short tone acknowledges submission, and another
  marks the follow-up listening window after a spoken reply. The terminal labels
  listening, recording, processing and speaking separately.
- A pause of **2.5 seconds** submits the utterance; shorter thinking pauses stay in
  one recording. `--voice-silence-ms 3500` allows longer pauses (range 800–10000).
  Explicit hesitation endings such as “嗯 / 让我想想 / えっと / let me think” get
  four extra seconds after transcription. Speech resumed before submission to chat
  retains the preceding audio and transcribes the combined recording. Continuous
  speech is capped at 60 seconds; retained audio is bounded to 90 seconds.
- After each answer there is a **20-second follow-up window** without another
  wake phrase. `--voice-followup-seconds 0` disables follow-ups; range is 0–120.
- In the default full-duplex mode, speak during a response to interrupt. The microphone stays open. WebRTC AEC3
  receives the actual speaker PCM to reduce echo; sustained speech stops playback
  and cancels that specific chat request before starting a replacement.
- Tool confirmations are read aloud with their arguments. Say **yes / 确认** or
  **no / 取消**. Ambiguous answers are repeated once, then denied. Voice never
  grants permanent permission. Very large confirmations require the app.
- Say **晚安 / 先这样 / 结束对话 / good night / goodbye** to end follow-ups
  immediately and return to Hey Yumi standby. This keeps the microphone open
  for wake detection. Embedded phrases such as “帮我给妈妈说晚安” do not end it.
- Say **暂停麦克风 / pause microphone** to release the microphone and speaker
  streams. Voice wake is then unavailable; press **Enter** in the terminal to resume.
- After a Room Control music action confirms `ok: true` and `playback.state: playing`,
  Yumi skips spoken commentary and returns silently to wake-only standby. Failed or
  unverified playback still receives feedback. Merely asking for music status does
  not silence the answer. Automatic resume below applies to terminal `music_play`.
- Tools registered with `reply_on_success=False` use explicit silent completion.
  On confirmed tool success the server skips further model generation, and the
  voice client immediately closes audio streams and skips TTS, including any
  pre-tool preamble. This works in both audio modes. Room Control `music_play` opts in; a momentarily
  `paused` player snapshot no longer prevents this handoff. Failures still receive
  feedback. The server, voice client, and edge registration all need this update.
- After terminal Room Control playback, the client queries that player's read-only
  status every two seconds with the microphone closed and no model requests. A
  confirmed empty/stopped queue automatically reopens capture, plays a rising cue,
  and opens a follow-up window; later Hey Yumi works normally. Startup and repeated
  inactive-sample checks protect against transient paused snapshots. A paused
  initial snapshot alone never proves completion. Unknown/offline status keeps
  capture closed and retries; Enter resumes immediately. Other terminal tools or
  older servers without a playback monitor retain manual Enter recovery.
- Press **Ctrl+C** to stop. A local server started by this voice process is stopped
  too; an existing server is left running.

Playback decodes WAV, MP3, and Ogg with PyAV and sends PCM to sounddevice. It does
not require a shell audio player. Replies use the account's streaming TTS endpoint;
a new audio segment plays when it arrives, without waiting for all segments.

## Local and Nexus modes

**Local:** Yumi reuses a running server at `http://127.0.0.1:8000`. If absent, it
runs model setup/preflight and starts a loopback server automatically. When speech
is disabled, the newly started server uses local Whisper base and system TTS.
Whisper downloads weights on first transcription. The local LLM provider still
needs to be installed/configured (for example Ollama). Server startup logs are
at `~/.yumi/voice-server.log`. An existing server needs STT/TTS enabled already.

**Nexus:** The browser opens account login/device approval. Compare its code with
the terminal. The device credential is saved privately in
`~/.yumi/voice-client.json`; subsequent runs reuse it. Voice uses the same personal
conversation, tools, speech providers, and quotas as the app. Use
`yumi --voice --voice-logout` to revoke this device. Nexus needs the matching core
and enterprise update, including `/chat/cancel`, `/chat/capabilities`, and voice
credential access to streaming replies and TTS. Old servers fail preflight.

For a non-interactive terminal pass `--voice-mode local` or `--voice-mode nexus`.
`--voice-server URL` selects a custom API (it is not automatically started).
`--voice-cue-volume 0–100` controls local tones (default 70; 0 mutes them).
`--voice-wake-sensitivity low|balanced|high` controls keyword confidence; balanced
is the default. High can increase false wakes; try the default pronunciation fix
before lowering the threshold. Enter is never a tool confirmation or approval.

Remote Nexus endpoints require HTTPS. `--voice-no-browser` prints the login link.

## Audio devices and platform support

```sh
yumi --voice --voice-list-devices
yumi --voice --voice-input-device 0 --voice-output-device 1
```

Allow microphone access in OS privacy settings. Linux may require the system
PortAudio package (`libportaudio2` on Debian/Ubuntu); local system TTS needs
`espeak-ng`. macOS and Windows sounddevice wheels include PortAudio. A headset
improves interruption accuracy in echo-heavy rooms. Bluetooth hands-free profiles
may reduce audio quality to 8/16 kHz; different devices may have no common rate.
Device disconnection requires restarting the client.

If the default input and output appear to be the same low-rate hands-free device,
Yumi prefers a single available independent built-in/USB microphone. Explicit
`--voice-input-device` choices are preserved. If there is no unambiguous alternative,
Yumi prints a quality notice. Raising the PCM sample rate does not restore Bluetooth
music quality while its microphone remains open: use a separate microphone, or pause
the microphone while listening to music. Standby alone does not release the device.

### Bluetooth speaker microphone: playback with capture closed

```sh
yumi --voice --voice-audio-mode half-duplex
```

This opt-in mode closes both capture and output streams before a spoken reply,
then opens output alone. On macOS it checks the selected speaker's actual CoreAudio
rate and waits up to four seconds for Bluetooth to leave its low-rate profile.
Starting output too early can keep it in call quality. The input remains closed
across all reply parts; it reopens after the reply, playback failure, or interruption.
The follow-up tone tells you when you can speak again. **While Yumi is speaking,
use Enter to stop it; voice interruption is unavailable with the microphone closed.**
Enter still never approves a pending tool action.

After terminal Room Control playback begins, this mode releases the microphone
and monitors the player as described above. It cannot hear Hey Yumi during music;
Enter can resume early. After playback ends it restores capture automatically,
without an unsolicited spoken reply. It does not guess completion from song length.

Close System Settings' Sound/input-level page and other apps using the speaker's
microphone when testing: they can keep the device in call mode even after Yumi
releases it. The client reports when native playback quality could not be verified;
requesting 44.1/48 kHz PCM alone does not prove the Bluetooth profile changed.
Native format detection is currently macOS-only; other platforms get a bounded
release interval and still need hardware acceptance testing. The selected device
must remain uniquely identifiable by name and host API after a profile change.

The saved `voice_audio_mode` setting accepts `full-duplex` (default) or `half-duplex`;
the command-line flag overrides it. Return to voice interruption with
`yumi --voice --voice-audio-mode full-duplex`. A separate USB/built-in microphone
remains the way to keep high-quality Bluetooth playback and voice interruption
at the same time without switching profiles.

Wake, sleep, pause, and retry tones are generated locally and pass through the same
echo-cancellation reference as speech. Empty transcription gets a short retry cue;
other HTTP 422 errors retain their server explanation.

Continuous listening is local. Only segmented speech after waking, during an
active conversation, or in response to a confirmation is uploaded. Ambient speech
can count as a follow-up or interruption; this is not speaker authentication.

## Verification and limits

Automated tests cover segmentation, follow-ups, interruption, targeted cancellation,
confirmation decisions, streaming playback, archive verification and account route
permissions. Mac hardware capture and synthetic Hey Yumi / negative-phrase tests
have been exercised. Real-speaker accents, far-field double talk, Bluetooth delay,
and Windows/Linux hardware still need acceptance testing. AEC reduces echo but is
not a guarantee against self-interruption on every device.

Cancellation is scoped by account and client request UUID. It stops generation
and pending confirmations; already executed tool actions cannot be undone. If the
server cannot confirm cancellation, the client blocks new commands until restart.
The cancellation registry, like the existing edge and active-chat registry, is
process-local: deploy a single API worker (the supplied Docker default). Multiple
workers would require shared request routing. TTS generation may finish caching an
interrupted reply for history replay, but the client does not play its later parts.

Wake code is sherpa-onnx; default weights are the upstream English GigaSpeech 3.3M
2024-01-01 model. The default keyword file encodes the spoken “you-me” pronunciation and maps it
back to the single canonical phrase “Hey Yumi”; it does not add another product
wake phrase. Custom `--voice-keywords-file` contents remain untouched. A synthetic
macOS benchmark is available in `tools/evaluate_voice_wake.py`; its results do not
establish real-speaker accuracy or a false-alarm rate in music/noise.

The archive SHA-256 is pinned in `yumi/voice/models.py`. Weights are
downloaded from upstream, not bundled in the wheel. **Do not infer the model's
commercial/redistribution rights from sherpa-onnx's code license**: upstream model
license clarification is still tracked in
[sherpa-onnx #3802](https://github.com/k2-fsa/sherpa-onnx/issues/3802).
Use a separately licensed model for commercial distribution if necessary via
`--voice-model-dir`, `YUMI_VOICE_MODEL_DIR`, or `voice_sherpa_model_dir`.

The NDJSON `tool_status` event may include optional `media_playback` feedback
(`playing`, `paused`, `stopped`, or `unknown`) derived from the Room Control action
result. It is not inferred from assistant text or transport success alone.

## Japanese delivery

Gemini keeps the chosen voice and general style, with additional native Japanese
pitch-accent, phrasing and sentence-ending guidance. It avoids exaggerated
high-pitched acting and English stress patterns. `tts_style_ja` (or
`YUMI_TTS_STYLE_JA`) can override this guidance. Full-reply language context is
shared across synthesized parts so a foreign name alone does not change delivery.
Quoted Japanese song titles do not change the delivery of surrounding Chinese or
English prose. This is delivery guidance, not a guarantee of native pronunciation;
compare real samples with a Japanese listener before calling it resolved.

### Music startup on a shared Bluetooth device

On macOS, the half-duplex client now prepares a shared Bluetooth speaker before
Nexus starts a terminal music tool. It closes both audio streams and waits for
two consecutive native output-rate readings of at least 32 kHz. Only then does
it acknowledge readiness; there is no fixed delay on ordinary turns or separate
microphones. The terminal shows `Preparing speaker for music…` during this step.
If the route remains in call mode, playback is not started and capture resumes.
Enter cancels preparation. Playback failure also restores capture. Successful
playback keeps capture released until the existing playback monitor resumes it.
Both the server and the restarted client must support the readiness handshake.
Other platforms keep their existing behavior until native route checks exist.

### Ending a conversation and switching languages

Common complete farewells (including `Finish. See you later.`) return immediately
to wake-word standby with a closing tone, without chat generation or TTS. Quoted
farewells, song titles and compound action requests do not trigger this shortcut.
A capable voice session also exposes `end_voice_conversation` for less formulaic
farewells; the server sends `voice_standby` only after that tool succeeds. This
ends the follow-up window while leaving Hey Yumi available. It does not exit the
process, clear history or stop music. The tool is hidden outside capable sessions.

With automatic reply language, the current request's conversational language is
anchored in both the per-turn instruction and the current model request. Foreign
song titles retain their spelling without switching the reply language. Explicit
saved language settings and explicit translation requests still take priority.
Supported OpenAI transcription models receive an original-language transcription
instruction, without pinning automatic recognition to the previous turn's language.
