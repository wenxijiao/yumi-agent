"""Optional deployment admission hooks; older plugins keep their behavior."""

from contextlib import nullcontext

from yumi.core.platform.plugins import get_quota_policy


def chat_turn_scope(identity):
    hook = getattr(get_quota_policy(), "chat_turn", None)
    return hook(identity) if hook else nullcontext()


def reserve_speech(identity, *, text=None, audio=None):
    hook = getattr(get_quota_policy(), "reserve_voice", None)
    if hook is None:
        return
    if text is not None:
        hook(identity, kind="speech_characters", units=len(text))
    elif audio is not None:
        from fastapi import HTTPException
        from yumi.core.platform.storage.voice_store import wav_duration

        duration = wav_duration(audio)
        if duration is None:
            import io

            try:
                import av

                with av.open(io.BytesIO(audio)) as container:
                    seconds = 0.0
                    for frame in container.decode(audio=0):
                        seconds += frame.samples / frame.sample_rate
                        if seconds > 65:
                            raise ValueError("Recording too long")
                duration = seconds * 1000
            except Exception as exc:
                raise HTTPException(422, "Use a recording of up to 60 seconds.") from exc
        if not 0 < duration <= 65000:
            raise HTTPException(422, "Use a recording of up to 60 seconds.")
        hook(identity, kind="voice_seconds", units=duration / 1000)
