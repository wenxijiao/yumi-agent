"""Microphone voice session for ``yumi --server --voice``.

Submodules:

* :mod:`yumi.voice.audio_source` – pluggable mic capture (real / fake).
* :mod:`yumi.voice.wake` – wake-word detection (Picovoice Porcupine).
* :mod:`yumi.voice.segmenter` – VAD-based utterance collection.
* :mod:`yumi.voice.runtime` – the asyncio loop wiring everything together.
* :mod:`yumi.voice.dispatch` – send transcribed prompts into ``generate_chat_events``.

Optional dependency: ``pip install yumi-agent[voice,stt]``.
"""
