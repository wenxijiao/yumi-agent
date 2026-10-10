"""Always-listening voice conversation with bounded follow-ups and barge-in."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import time
import uuid
from collections import deque

import httpx
import numpy as np

from yumi.voice.runtime import pcm_to_wav_bytes
from yumi.voice.segmenter import UtteranceCollector, _VadBackend


class NoSpeechError(Exception):
    """A valid recording contained no transcribable speech."""


class EndVoiceConversation(Exception):
    def __init__(self, pause=False):
        self.pause = pause


def needs_thinking_time(text: str) -> bool:
    """Recognize explicit hesitation, never infer an action or confirmation."""
    text = re.sub(r"[\s，。！？、,.!?…]+$", "", text.casefold())
    return bool(
        re.search(
            r"(?:嗯+|呃+|让我想想|我想一下|我想想|等我想一下|えーと|えっと|ちょっと待って|\b(?:um|uh|let me think))$",
            text,
        )
    )


def conversation_control(text: str) -> str | None:
    # Entire farewell only: never trigger on a quotation, negation, song title,
    # or a compound request such as 'turn off the lights, then good night'.
    english = text.casefold().replace("’", "'").strip()
    if any(c in english for c in '"“”「」《》'):
        return None
    if re.fullmatch(
        r"(?:(?:ok(?:ay)?|alright|thanks|thank you)[ ,.!;]+)*"
        r"(?:(?:i'm|i am) (?:heading|going) (?:out|off|to bed)(?: now)?[ ,.!;]+)?"
        r"(?:let's|let us|we can) (?:leave|end|stop|pause) "
        r"(?:(?:our|this|the) )?(?:chat|conversation|talk)(?: here)?"
        r"(?: for (?:now|the moment|today))?[.! ]*",
        english,
    ):
        return "sleep"
    if re.fullmatch(
        r"(?:(?:hey[ ,]+)?yumi[ ,.!]+)?"
        r"(?:(?:ok(?:ay)?|alright|thanks|thank you|finish(?:ed)?|that's all|we're done)[ ,.!;]+)*"
        r"(?:see (?:you|ya)(?: later| soon| tomorrow)?|talk (?:to you )?later|catch you later|"
        r"good[ -]?night|good[ -]?bye|bye(?: bye)?|that's all(?: for now)?|we're done(?: for now)?)"
        r"(?:[ ,.!]+(?:yumi|thanks|thank you))?[.! ]*",
        english,
    ):
        return "sleep"
    text = "".join(c for c in text.casefold() if c.isalnum())
    if text.startswith("heyyumi"):
        text = text[7:]
    if text in {
        "晚安",
        "晚安yumi",
        "yumi晚安",
        "先这样",
        "先这样吧",
        "好了先这样",
        "结束对话",
        "结束聊天",
        "不聊了",
        "再见",
        "goodnight",
        "goodnightyumi",
        "bye",
        "goodbye",
        "拜拜",
        "回见",
        "回見",
        "下次聊",
        "おやすみ",
        "おやすみなさい",
        "またね",
        "またあとで",
        "さようなら",
        "thatsall",
        "endconversation",
    }:
        return "sleep"
    if text in {
        "暂停麦克风",
        "关闭麦克风",
        "停止监听",
        "暂停监听",
        "pausemicrophone",
        "mutemicrophone",
        "stoplistening",
    }:
        return "pause"
    return None


def confirmation_decision(text: str) -> str | None:
    # Never use a model, substring matching, or a permanent grant for approval.
    text = "".join(c for c in text.casefold() if c.isalnum())
    if text in {
        "yes",
        "yesplease",
        "confirm",
        "allow",
        "是",
        "是的",
        "确认",
        "确认执行",
        "同意",
        "允许",
        "可以",
        "执行吧",
        "好的",
    }:
        return "allow"
    if text in {"no", "cancel", "deny", "stop", "不", "不要", "取消", "拒绝", "不同意", "不允许", "不用了"}:
        return "deny"
    return None


class VoiceSession:
    def __init__(self, connection, audio, wake, *, followup_seconds=20, silence_ms=2500, client=None, vad=None):
        self.audio, self.wake = audio, wake
        self.http = client or httpx.AsyncClient(
            base_url=connection.base_url, headers=connection.headers(), timeout=httpx.Timeout(320, connect=15)
        )
        self.followup_seconds = followup_seconds
        self.vad = vad or _VadBackend(2)
        self.task = None
        self.confirmation = None
        self.deadline = 0.0
        self.collecting = False
        self.speech_frames = 0
        self.history = deque(maxlen=3)
        self.collector = UtteranceCollector(sample_rate=16000, frame_length=1600, silence_ms=silence_ms, max_ms=60000)
        self._pending_pcm = b""
        self.media_watch = None
        self.start_awake = False
        self._cleanups = set()
        self._speech_epoch = 0
        self._cancel_error = None
        self._ended = False
        self._awake = False
        self._quiet_media = False
        self._capture_released = False
        self._cue_active = False
        self._cue_task = None
        self._cue_generation = 0
        self.pause_requested = False
        self._cue_frames = deque(maxlen=12)
        self._capture_during_cue = False
        self._manual_wake = False
        self._level_frames = deque(maxlen=100)
        self._last_input_notice = time.monotonic()
        self._input_notice_shown = False
        self._output_active = False
        self._media_prepare_supported = False
        self._voice_controls_supported = False

    async def request(self, method, path, **kwargs):
        response = await self.http.request(method, path, **kwargs)
        if response.status_code == 422 and path == "/assistant/voice":
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            if detail == "No speech could be transcribed.":
                raise NoSpeechError()
        response.raise_for_status()
        return response

    def cue(self, kind):
        if self._cue_task and not self._cue_task.done():
            self._cue_task.cancel()
            self.audio.interrupt()
        self._cue_active = True
        self._capture_during_cue = kind in {"wake", "followup", "retry"}
        if not self._capture_during_cue:
            self._cue_frames.clear()
        self._cue_generation += 1
        generation = self._cue_generation

        async def play():
            try:
                await self.audio.cue(kind)
            except Exception as exc:
                print(f"Audio cue unavailable: {exc}")
            finally:
                if generation == self._cue_generation:
                    self._cue_active = False

        self._cue_task = asyncio.create_task(play())

    def request_wake(self):
        # Enter can stop output-only speech, but never approves a pending tool.
        if self._output_active:
            self.audio.interrupt()
            if self.confirmation is None and self.task and not self.task.done():
                self.task.cancel()
                self._manual_wake = True
            return
        if self.confirmation is None and not self.collecting and (not self.task or self.task.done()):
            self._manual_wake = True

    def activate(self):
        self._manual_wake = False
        self._ended = False
        self._awake = True
        self.deadline = time.monotonic() + 10
        self.collector.reset()
        self.history.clear()
        self._cue_frames.clear()
        self.speech_frames = 0
        self.wake.reset()
        self.cue("wake")
        print("● Listening — speak now.", flush=True)

    def input_notice(self, frame):
        # Local levels only; no idle audio is uploaded or saved.
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        self._level_frames.append(float(np.sqrt(np.mean(samples * samples))))
        now = time.monotonic()
        if not self._input_notice_shown and now - self._last_input_notice >= 30 and len(self._level_frames) == 100:
            self._last_input_notice = now
            if max(self._level_frames) < 20:
                self._input_notice_shown = True
                print(
                    "Microphone signal is very quiet. Check mute, input device, and distance; press Enter to wake.",
                    flush=True,
                )

    async def standby(self, *, pause=False, audible=True):
        self._ended = True
        self._cue_frames.clear()
        self._manual_wake = False
        self._awake = False
        self.deadline = 0
        self.collecting = False
        self.collector.reset()
        self._pending_pcm = b""
        self.history.clear()
        self.speech_frames = 0
        self.audio.interrupt()
        self.wake.reset()
        if audible:
            self.cue("pause" if pause else "sleep")
            await self._cue_task
        if pause:
            self.pause_requested = True
            if self.media_watch:
                print(
                    "♫ Microphone released during music. Listening resumes when playback ends; press Enter to resume early.",
                    flush=True,
                )
            else:
                print("Microphone paused. Voice wake is unavailable until you press Enter.")
        else:
            print("Standby — say Hey Yumi to start a new conversation.")

    async def transcribe(self, wav, session_id):
        response = await self.request(
            "POST",
            "/assistant/voice",
            json={
                "request_id": str(uuid.uuid4()),
                "session_id": session_id,
                "content_base64": base64.b64encode(wav).decode("ascii"),
            },
        )
        return response.json()

    @contextlib.asynccontextmanager
    async def spoken_output(self):
        half = getattr(self.audio, "half_duplex", False)
        context = self.audio.speech_output() if half else contextlib.nullcontext()
        if half:
            self._output_active = True
            if self._cue_task and not self._cue_task.done():
                self._cue_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._cue_task
            self._cue_frames.clear()
            self.history.clear()
            self.collector.reset()
            self.collecting = False
            self.speech_frames = 0
        try:
            async with context:
                yield
        finally:
            if half:
                self._output_active = False
                self._cue_frames.clear()
                self.history.clear()
                self.collector.reset()
                self.collecting = False
                self.speech_frames = 0
                self.wake.reset()

    async def speak(self, text, session_id):
        epoch = self._speech_epoch
        response = await self.request("POST", "/tts/synthesize", json={"text": text, "session_id": session_id})
        # An answer may arrive while the confirmation prompt is still synthesizing.
        if epoch == self._speech_epoch:
            async with self.spoken_output():
                await self.audio.play(response.content)

    async def confirm(self, event, session_id):
        self._quiet_media = False  # An approval question needs the user's attention.
        try:
            await asyncio.wait_for(self._confirm(event, session_id), timeout=90)
        except asyncio.TimeoutError:
            self.audio.interrupt()
            await self.request("POST", "/tools/confirm", json={"call_id": event["call_id"], "decision": "deny"})
            print("Confirmation timed out; action denied.")

    async def _confirm(self, event, session_id):
        summary = event.get("action_summary") or event.get("tool_name") or "Tool action"
        details = json.dumps(event.get("arguments", {}), ensure_ascii=False)
        if len(details) > 3000:
            raise RuntimeError("This action is too large to confirm by voice. Please use the Yumi app.")
        prompt = f"{summary}. Arguments: {details}. Say yes to confirm, or no to cancel."
        decision = "deny"
        cancelled = False
        try:
            for _ in range(2):
                self.confirmation = asyncio.get_running_loop().create_future()
                print(f"Confirmation: {prompt}")
                await self.speak(prompt, session_id)
                if getattr(self.audio, "half_duplex", False):
                    self.cue("followup")
                wav = await asyncio.wait_for(self.confirmation, timeout=40)
                recording = await self.transcribe(wav, session_id)
                print(f"You: {recording['transcript']}")
                control = conversation_control(recording["transcript"])
                if control:
                    raise EndVoiceConversation(pause=control == "pause")
                answer = confirmation_decision(recording["transcript"])
                if answer:
                    decision = answer
                    break
                prompt = "Please say yes to confirm, or no to cancel."
        except asyncio.CancelledError:
            cancelled = True
            raise
        except asyncio.TimeoutError:
            print("Confirmation timed out; action denied.")
        finally:
            self.confirmation = None
            # On cancellation the chat task is cancelled server-side as well.
            if not cancelled:
                await self.request("POST", "/tools/confirm", json={"call_id": event["call_id"], "decision": decision})

    async def reply_audio(self, turn_id):
        played = set()
        async with contextlib.AsyncExitStack() as output_stack:
            output_started = False
            async with self.http.stream("POST", "/assistant/voice/reply/stream", json={"turn_id": turn_id}) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if event.get("type") == "part":
                        index = event["index"]
                        if index not in played:
                            if not output_started:
                                await output_stack.enter_async_context(self.spoken_output())
                                output_started = True
                            await self.audio.play(base64.b64decode(event["audio"], validate=True))
                            played.add(index)
                    elif event.get("type") == "ready":
                        voice = event["voice"]
                        for index in range(voice["part_count"]):
                            if index not in played:
                                audio = await self.request(
                                    "GET", f"/assistant/voice/{voice['id']}/audio", params={"part": index}
                                )
                                if not output_started:
                                    await output_stack.enter_async_context(self.spoken_output())
                                    output_started = True
                                await self.audio.play(audio.content)
                    elif event.get("type") == "error":
                        raise RuntimeError(
                            str(
                                event.get("content")
                                or event.get("detail")
                                or event.get("message")
                                or "Spoken reply failed"
                            )
                        )

    async def cancel_request(self, request_id):
        try:
            response = await self.request("POST", "/chat/cancel", json={"client_request_id": request_id}, timeout=8)
            if response.json().get("status") != "cancelled":
                raise RuntimeError("The previous action is still stopping")
        except Exception:
            self._cancel_error = "Could not confirm that the previous turn stopped. Restart --voice before sending another command. Executed actions are not undone."
            print(self._cancel_error)

    async def turn(self, wav, previous=None):
        request_id = None
        silent_completion = False
        voice_standby = False
        media_output = contextlib.AsyncExitStack()

        async def release_media():
            await media_output.aclose()
            self._output_active = False

        try:
            if previous:
                # Wait for completion without propagating the old task's cancellation,
                # while preserving cancellation of this new task itself.
                await asyncio.wait([previous])
            for cleanup in list(self._cleanups):
                await asyncio.shield(cleanup)
            if self._cancel_error:
                raise RuntimeError(self._cancel_error)
            snapshot = (await self.request("GET", "/assistant")).json()
            state = snapshot.get("conversation", snapshot)
            session_id = state["session_id"]
            print("◌ Processing…", flush=True)
            recording = await self.transcribe(wav, session_id)
            print(f"You: {recording['transcript']}")
            control = conversation_control(recording["transcript"])
            if control:
                raise EndVoiceConversation(pause=control == "pause")
            if needs_thinking_time(recording["transcript"]):
                print("● Still listening — take your time.", flush=True)
                await asyncio.sleep(4)
            # Until this boundary, resumed speech can replace STT with one
            # combined recording. Once sent, normal cancellation rules apply.
            self._pending_pcm = b""
            request_id = str(uuid.uuid4())
            body = {
                "prompt": recording["transcript"],
                "session_id": session_id,
                "personal": True,
                "voice_id": recording["id"],
                "reply_voice": True,
                "revision": state.get("revision"),
                "channel": "app",
                "client_request_id": request_id,
                "prepare_media_output": self._media_prepare_supported
                and bool(getattr(self.audio, "can_prepare_media", False)),
                "voice_session_controls": self._voice_controls_supported,
            }
            pieces, turn_id = [], None
            async with self.http.stream("POST", "/chat", json=body) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    kind = event.get("type")
                    if kind == "turn_phase":
                        turn_id = event.get("turn_id") or turn_id
                    elif (
                        kind == "voice_standby"
                        and body["voice_session_controls"]
                        and turn_id is not None
                        and event.get("turn_id") == turn_id
                    ):
                        voice_standby = True
                        await release_media()
                        await self.standby()
                    elif kind == "media_prepare" and body["prepare_media_output"]:
                        if event.get("turn_id") != turn_id or not re.fullmatch(
                            r"[a-f0-9]{32}", str(event.get("preparation_id", ""))
                        ):
                            raise RuntimeError("Invalid speaker preparation request.")
                        self._output_active = True
                        if self._cue_task and not self._cue_task.done():
                            self._cue_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await self._cue_task
                        self._cue_frames.clear()
                        self.history.clear()
                        self.collector.reset()
                        self.collecting = False
                        self.speech_frames = 0
                        ready = True
                        try:
                            await media_output.enter_async_context(self.audio.media_output())
                        except RuntimeError as exc:
                            ready = False
                            print(str(exc), flush=True)
                        await self.request(
                            "POST",
                            "/assistant/voice/media-ready",
                            json={"preparation_id": event["preparation_id"], "ready": ready},
                        )
                    elif (
                        kind == "turn_complete"
                        and event.get("reply") == "none"
                        and event.get("reason") == "tool_success"
                        and event.get("voice_capture") == "pause"
                        and turn_id is not None
                        and event.get("turn_id") == turn_id
                    ):
                        silent_completion = True
                        self.media_watch = turn_id if event.get("media_watch") == turn_id else None
                        # Release hardware now; keep draining the HTTP stream for
                        # server timing/persistence instead of cancelling the turn.
                        self._quiet_media = True
                        self._capture_released = True
                        if self._cue_task and not self._cue_task.done():
                            self._cue_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await self._cue_task
                        self.audio.close()
                    elif kind == "text":
                        pieces.append(str(event.get("content") or ""))
                    elif kind == "tool_status":
                        state = event.get("media_playback")
                        if event.get("status") == "error" or state == "unknown":
                            self._quiet_media = False
                        if event.get("status") == "success" and state in {"playing", "paused", "stopped"}:
                            self._quiet_media = state == "playing"
                    elif kind == "tool_confirmation":
                        await release_media()
                        await self.confirm(event, session_id)
                    elif kind == "error":
                        raise RuntimeError(str(event.get("content") or "Chat failed"))
            if not silent_completion and not self._quiet_media:
                await release_media()
            if voice_standby:
                return
            if silent_completion:
                print("✓ Action completed. Microphone released.", flush=True)
                await self.standby(pause=True, audible=False)
            elif self._quiet_media:
                # Only a validated tool result, never the model's own claim,
                # can suppress speech over successfully started music.
                # External players do not yet publish a reliable end event. In
                # half duplex, release the mic until Enter rather than guessing.
                await self.standby(pause=getattr(self.audio, "half_duplex", False), audible=False)
            elif turn_id and pieces:
                print(f"Yumi: {''.join(pieces).strip()}")
                if getattr(self.audio, "half_duplex", False):
                    print("▶ Speaking — press Enter to interrupt; listening resumes afterward.", flush=True)
                else:
                    print("▶ Speaking — speak to interrupt.", flush=True)
                await self.reply_audio(turn_id)
                if self.followup_seconds > 0:
                    self.cue("followup")
                    print(f"● Listening — {self.followup_seconds}s follow-up, no wake phrase needed.", flush=True)
        except EndVoiceConversation as exc:
            if request_id:
                await self.cancel_request(request_id)
            await self.standby(pause=exc.pause)
        except NoSpeechError:
            self._pending_pcm = b""
            print("Didn't catch speech. Please try again.")
            self.cue("retry")
        except asyncio.CancelledError:
            if request_id:
                cleanup = asyncio.create_task(self.cancel_request(request_id))
                self._cleanups.add(cleanup)
                cleanup.add_done_callback(self._cleanups.discard)
                await asyncio.shield(cleanup)
            raise
        except Exception as exc:
            self._pending_pcm = b""
            if request_id:
                await self.cancel_request(request_id)
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    detail = exc.response.json().get("detail")
                except (ValueError, httpx.ResponseNotRead):
                    detail = None
                message = detail if isinstance(detail, str) else "Please retry or check the server configuration."
                print(f"Voice turn failed ({exc.response.status_code}): {message}")
            else:
                print(f"Voice turn failed: {exc}")
            if silent_completion:
                await self.standby(pause=True, audible=False)
            else:
                await release_media()
                self.cue("retry")
        finally:
            # Success has already closed audio permanently; failures/cancellation
            # reopen capture. Keep the device cleanup alive across Ctrl+C.
            restore = asyncio.create_task(release_media())
            try:
                await asyncio.shield(restore)
            except asyncio.CancelledError:
                await restore
                raise
            self._quiet_media = False
            self.deadline = 0 if self._ended else time.monotonic() + self.followup_seconds

    def is_speech(self, frame):
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        # A sustained VAD hit plus an energy floor rejects most residual echo/clicks.
        if np.sqrt(np.mean(samples * samples)) < 100:
            return False
        return sum(self.vad.is_speech(frame[i : i + 640], 16000) for i in range(0, 3200, 640)) >= 3

    async def feed(self, frame):
        now = time.monotonic()
        if self._output_active:
            return
        if self._cue_active:
            if self._capture_during_cue:
                self._cue_frames.append(frame)
            await asyncio.sleep(0)
            return
        if self._manual_wake:
            self.activate()
            return
        if self._cue_frames:
            buffered = list(self._cue_frames)
            self._cue_frames.clear()
            for captured in buffered:
                await self.feed(captured)
        if self._quiet_media or self.pause_requested:
            return
        busy = self.task is not None and not self.task.done()
        confirming = self.confirmation is not None and not self.confirmation.done()
        if self._ended or (not busy and not self.collecting and now > self.deadline):
            if self._awake:
                await self.standby()
                return
            self.history.clear()
            self.speech_frames = 0
            self.input_notice(frame)
            if self.wake.process(frame):
                self.activate()
            return
        speech = self.is_speech(frame)
        if not self.collecting:
            self.history.append(frame)
            self.speech_frames = self.speech_frames + 1 if speech else 0
            required = 2 if confirming or not busy else 5 if getattr(self.audio, "playing", False) else 3
            if self.speech_frames < required:
                return
            self.collecting = True
            print("● Recording…", flush=True)
            self._awake = True
            self._speech_epoch += 1
            self.collector.reset()
            self.audio.interrupt()
            if busy and not confirming:
                self.task.cancel()
                print("Interrupted. Listening…")
            for pre in list(self.history)[:-1]:
                self.collector.feed(pre, is_speech=True)
            self.history.clear()
        utterance = self.collector.feed(frame, is_speech=speech)
        if utterance is not None:
            self.collecting = False
            self.speech_frames = 0
            if confirming:
                wav = pcm_to_wav_bytes(utterance, sample_rate=16000)
                self.confirmation.set_result(wav)
            else:
                # Retain only audio not yet submitted to chat, bounded to 90s.
                self._pending_pcm = (self._pending_pcm + utterance)[-16000 * 2 * 90 :]
                wav = pcm_to_wav_bytes(self._pending_pcm, sample_rate=16000)
                self.cue("submit")
                self.task = asyncio.create_task(self.turn(wav, self.task))

    async def run(self):
        capability = (await self.request("GET", "/chat/capabilities", timeout=15)).json()
        if not capability.get("request_cancellation"):
            raise RuntimeError("Update the Yumi server before using this voice client.")
        self._media_prepare_supported = capability.get("media_output_preparation") is True
        self._voice_controls_supported = capability.get("voice_session_controls") is True
        from yumi.voice.terminal import EnterToWake

        self.audio.start()
        if self.start_awake:
            self.activate()
            self.deadline = time.monotonic() + max(10, self.followup_seconds)
            print("● Listening resumed — you can speak now.", flush=True)
        else:
            self.cue("ready")
            print(
                f"Ready — say Hey Yumi or press Enter. Speak after the rising tone.\n"
                f"Follow-up: {self.followup_seconds}s. "
                + (
                    "Microphone is released during replies; press Enter to interrupt. "
                    if getattr(self.audio, "half_duplex", False)
                    else "Speak to interrupt replies. "
                )
                + "Say good night to end the conversation; Ctrl+C quits.",
                flush=True,
            )
        try:
            async with EnterToWake(self.request_wake):
                while not self.pause_requested:
                    try:
                        frame = await self.audio.read_frame()
                    except RuntimeError:
                        if self._capture_released and self.task:
                            # A terminal success may close capture while a read
                            # is pending. Finish/drain the turn before cleanup.
                            await self.task
                            continue
                        raise
                    if frame is not None:
                        await self.feed(frame)
            return "paused"
        finally:
            self.audio.interrupt()
            if self.task and not self.task.done():
                self.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.task

    async def close(self):
        if self._cue_task and not self._cue_task.done():
            self._cue_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cue_task
        for cleanup in list(self._cleanups):
            await asyncio.shield(cleanup)
        self.audio.close()
        await self.http.aclose()
