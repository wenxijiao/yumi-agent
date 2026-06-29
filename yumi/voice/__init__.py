"""Microphone voice session for ``yumi --server --voice``.

Submodules:

* :mod:`yumi.voice.audio_source` – pluggable mic capture (real / fake).
* :mod:`yumi.voice.wake` – wake-word detection (Picovoice Porcupine).
* :mod:`yumi.voice.segmenter` – VAD-based utterance collection.
* :mod:`yumi.voice.runtime` – the asyncio loop wiring everything together.
* :mod:`yumi.voice.dispatch` – send transcribed prompts into ``generate_chat_events``.

Python dependencies ship with ``pip install yumi-agent``; a Picovoice access
key, a wake-word file, microphone permission, and STT configuration are still
runtime setup steps.
"""
