"""Local Whisper STT via ``faster-whisper`` (bundled with yumi)."""

from __future__ import annotations

import asyncio
import tempfile
import threading
from pathlib import Path

from yumi.core.features.config.paths import WHISPER_MODELS_DIR
from yumi.core.features.stt.base import SpeechToTextProvider, SttError
from yumi.core.features.stt.types import WHISPER_MULTILINGUAL_MODELS, TranscriptionResult

_FASTER_WHISPER_MODEL_IDS = {
    "tiny": "tiny",
    "base": "base",
    "small": "small",
    "medium": "medium",
    "large": "large-v3",
    "turbo": "large-v3-turbo",
}


_FASTER_WHISPER_REPO_IDS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large": "Systran/faster-whisper-large-v3",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}


_WHISPER_HF_FILE_PATTERNS = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


def _whisper_loads_from_disk(
    *,
    root: Path,
    fw_id: str,
    hf_token: str | None,
) -> bool:
    """True if faster-whisper can open this model from *root* without downloading."""
    try:
        from faster_whisper import WhisperModel

        WhisperModel(
            fw_id,
            device="cpu",
            compute_type="int8",
            download_root=str(root),
            local_files_only=True,
            use_auth_token=hf_token,
        )
        return True
    except Exception:
        return False


def ensure_whisper_weights_cached(*, model: str, model_dir: str | None = None) -> None:
    """Download Whisper weight files to disk if missing (via faster-whisper).

    Uses :func:`huggingface_hub.snapshot_download` with a visible tqdm bar (faster-whisper's
    own ``download_model`` disables the bar). The same path applies to every built-in size,
    each mapped to a public Hugging Face CTranslate2 model.

    If weights are already present under *model_dir* / default cache, skips download and
    progress output (``yumi --setup`` stays quiet on repeat runs).

    Uses CPU + int8 for this pass to reduce peak RAM during setup; runtime inference
    may still use ``device=auto`` from :class:`WhisperSttProvider`.
    """
    model_name = (model or "").strip()
    if model_name not in WHISPER_MULTILINGUAL_MODELS:
        raise ValueError(f"Unsupported Whisper model: {model_name!r}")
    root = Path(model_dir).expanduser() if model_dir else WHISPER_MODELS_DIR
    root.mkdir(parents=True, exist_ok=True)
    try:
        from faster_whisper import WhisperModel
        from huggingface_hub import get_token, snapshot_download
        from tqdm.auto import tqdm
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is required for STT and ships with yumi. "
            "Reinstall with: pip install --force-reinstall yumi"
        ) from exc
    fw_id = _FASTER_WHISPER_MODEL_IDS.get(model_name, model_name)
    repo_id = _FASTER_WHISPER_REPO_IDS.get(model_name)
    if not repo_id:
        raise ValueError(
            f"Internal error: no Hugging Face repo for Whisper model {model_name!r}. Update yumi for this STT size."
        )
    hf_token = get_token()
    if _whisper_loads_from_disk(root=root, fw_id=fw_id, hf_token=hf_token):
        return

    print()
    print("  Optional: put HF_TOKEN in ~/.yumi/.env for Hugging Face rate limits (see docs/CONFIGURATION.md).")
    print("  Downloading Whisper weights (Hugging Face progress bar; first install can take several minutes)...")
    snapshot_download(
        repo_id,
        cache_dir=str(root),
        allow_patterns=_WHISPER_HF_FILE_PATTERNS,
        tqdm_class=tqdm,
        token=hf_token,
    )
    WhisperModel(
        fw_id,
        device="cpu",
        compute_type="int8",
        download_root=str(root),
        local_files_only=True,
        use_auth_token=hf_token,
    )
    print("  Whisper model files are ready.")


class WhisperSttProvider(SpeechToTextProvider):
    def __init__(self, *, model: str, model_dir: str | None = None, language: str = "auto"):
        model_name = (model or "").strip()
        if model_name not in WHISPER_MULTILINGUAL_MODELS:
            raise SttError(
                f"Unsupported Whisper model '{model_name}'. "
                f"Supported multilingual models: {', '.join(WHISPER_MULTILINGUAL_MODELS)}"
            )
        self.model_name = model_name
        self.model_dir = Path(model_dir).expanduser() if model_dir else WHISPER_MODELS_DIR
        self.language = (language or "auto").strip()
        self._model = None
        # Guard concurrent first-time loads — otherwise two transcriptions racing
        # the cold path would each run the download/load and double RAM.
        self._load_lock = threading.Lock()

    def _load_model(self):
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
                from huggingface_hub import get_token
            except ImportError as exc:
                raise SttError(
                    "faster-whisper is not importable. Reinstall with: "
                    "pip install --force-reinstall yumi"
                ) from exc
            self.model_dir.mkdir(parents=True, exist_ok=True)
            try:
                hf_token = get_token()
                self._model = WhisperModel(
                    _FASTER_WHISPER_MODEL_IDS.get(self.model_name, self.model_name),
                    device="auto",
                    compute_type="auto",
                    download_root=str(self.model_dir),
                    use_auth_token=hf_token,
                )
            except Exception as exc:
                raise SttError(f"Failed to load Whisper model '{self.model_name}': {exc}") from exc
            return self._model

    def _transcribe_sync(self, audio: bytes, *, filename: str, language: str | None) -> TranscriptionResult:
        # Allowlist suffixes so a user-controlled filename can't put arbitrary
        # text in the temp file name (e.g. ".exe").
        raw_suffix = Path(filename or "audio").suffix.lower()
        allowed = {".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aac", ".webm"}
        suffix = raw_suffix if raw_suffix in allowed else ".bin"
        tmp_path = ""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio)
            tmp.flush()
            tmp_path = tmp.name
        try:
            model = self._load_model()
            lang = (language or self.language or "auto").strip()
            lang_arg = None if lang == "auto" else lang
            try:
                segments, info = model.transcribe(tmp_path, language=lang_arg)
                text = "".join(segment.text for segment in segments).strip()
            except Exception as exc:
                raise SttError(f"Whisper transcription failed: {exc}") from exc
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink()
                except OSError:
                    pass
        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            duration_seconds=getattr(info, "duration", None),
        )

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_sync, audio, filename=filename, language=language)
