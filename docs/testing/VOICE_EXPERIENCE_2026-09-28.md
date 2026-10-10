# Voice experience follow-up — 2026-09-28

## Findings and changes

- Live Nexus configuration: Gemini `gemini-3.1-flash-tts-preview`, Aoede, auto
  language. A global bright/playful/brisk delivery prompt and a Mandarin override
  existed; there was no Japanese-specific delivery instruction.
- Add Japanese standard pitch-accent, connected phrasing, natural sentence endings,
  and restrained persona guidance. Keep the chosen voice/general style. Lock
  delivery-language context across a reply's parts; quoted Japanese titles do not
  change surrounding Chinese/English delivery. Optional `tts_style_ja` /
  `YUMI_TTS_STYLE_JA` customizes it. Existing cached speech is not regenerated.
- Change the default KWS tokenization from the written Y/UM/I path to the spoken
  YOU/ME path, still returning only the canonical HEY_YUMI keyword. Keep score 1.0
  and threshold 0.25. Optional low/high sensitivity changes confidence, not the
  user's wake phrase. Custom keyword files remain unchanged.
- Wake tone: 340 ms, peak about 5250 (int16) at default volume 70, compared with
  180 ms/2600 before. Add startup, submitted, and follow-up feedback. Expose local
  cue volume. Display separate listening/recording/processing/speaking states.
- Preserve up to 1.2 s of echo-processed input during wake/follow-up/retry cues;
  previously input during cues was discarded except for a short history window.
- Enter wakes locally without authorizing tools. Reader cleanup happens before
  the pause-mode Enter prompt. Warn once when sustained input is nearly silent;
  level analysis is local and does not save/upload ambient recordings.

## Verification

180 targeted unit/integration tests pass; Ruff, focused Pyright and diff checks
pass. Tests cover speech beginning during the wake cue, manual activation without
keyword detection, confirmation isolation, terminal reader removal, per-language
style isolation, full-reply context, bounded cue gain, cancellation and music silence.

Run `python tools/evaluate_voice_wake.py --output /tmp/report.json` with the
repository environment on macOS. It synthesizes fixed phrases using 8 installed
system voices, tests 16 kHz and 8 kHz round-tripped audio at full/15% amplitude,
and feeds the actual old/current keyword paths through the same implementation.
No microphone is used; generated WAVs are temporary. Detailed results are in
`VOICE_WAKE_2026-09-28.json`.

| Synthetic sample set | Old keyword tokens | Updated tokens |
| --- | ---: | ---: |
| Positive clips triggering | 19 / 64 | 53 / 64 |
| Negative clips triggering | 16 / 256 | 2 / 256 |

The two remaining false triggers are near-homophone “Hey yummy” samples. Eleven
positives still miss, especially one system voice/accent and some quiet/narrowband
clips. This is a small synthetic regression set, **not** a measured population
wake rate or false alarms/hour. Do not call wake universally reliable based on it.
Human accents, distance, background music and real-room echo remain acceptance work.

## Sources

- sherpa-onnx keyword formatting and score/threshold semantics:
  https://github.com/k2-fsa/sherpa/blob/master/docs/source/onnx/kws/index.rst
- Gemini speech style prompting:
  https://ai.google.dev/gemini-api/docs/speech-generation?authuser=50&hl=en

These sources describe controls, not a guarantee of improved Japanese quality.
A same-text before/after Japanese sample is generated with the actual configured
provider for listening comparison. Synthesis success and transcription checks do
not establish natural pitch accent; a Japanese listener still needs to compare it.

## Live verification and deployment

Same-text Japanese sample: old synthesis 7.04 s with 7.04 s audio; updated
synthesis 6.89 s with 7.48 s audio. Both transcribed back to the intended Japanese
sentence (minor orthography differences). This is not an accent-quality score.
Samples are at `/Users/wenxijiao/Downloads/yumi-voice-20260928/`.

A short physical playback test completed with the current iPhone microphone and
Mac mini speaker at 48 kHz; 4 capture frames arrived during the cue. No microphone
recording was saved or uploaded. The stream was closed afterward. This verifies
device operation, not perceived loudness or human wake recognition.

Deployed `yumi-nexus:macmini-20260928-voice-r5` on this Mac. All six application
services are running, API healthy. Local/public health and authenticated voice
capabilities pass; a container-side assertion verifies the Japanese delivery
profile and full-reply context. Previous r4 image/release and compose backup remain
available for rollback. The editable local `yumi` command uses the new client after
restart. This is not a PyPI release.
