"""Microphone voice session for ``kumi --server --voice``.

Submodules:

* :mod:`kumi.voice.audio_source` – pluggable mic capture (real / fake).
* :mod:`kumi.voice.wake` – wake-word detection (Picovoice Porcupine).
* :mod:`kumi.voice.segmenter` – VAD-based utterance collection.
* :mod:`kumi.voice.runtime` – the asyncio loop wiring everything together.
* :mod:`kumi.voice.dispatch` – send transcribed prompts into ``generate_chat_events``.

Optional dependency: ``pip install kumi-agent[voice,stt]``.
"""
