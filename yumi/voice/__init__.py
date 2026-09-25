"""Microphone voice session for ``yumi --voice``.

Submodules:

* :mod:`yumi.voice.audio_source` – pluggable mic capture (real / fake).
* :mod:`yumi.voice.sherpa_wake` – offline Hey Yumi wake-word detection.
* :mod:`yumi.voice.segmenter` – VAD-based utterance collection.
* :mod:`yumi.voice.runtime` – the asyncio loop wiring everything together.
* :mod:`yumi.voice.dispatch` – send transcribed prompts into ``generate_chat_events``.

The wake engine requires ``yumi-agent[voice-sherpa]``; a compatible model,
microphone permission, and STT configuration are runtime setup steps.
"""
