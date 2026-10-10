"""Offline Hey Yumi detection using a sherpa-onnx KWS model.

Model weights are intentionally not distributed with yumi-agent: the selected
model's commercial and redistribution license must be checked separately.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


class SherpaHeyYumiWake:
    sample_rate = 16000
    frame_length = 1600  # 100 ms, matching sherpa-onnx's microphone example

    def __init__(self, model_dir: str, keywords_file: str | None = None, *, sensitivity: str = "balanced") -> None:
        try:
            import numpy as np
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("Reinstall voice dependencies: pip install --upgrade yumi-agent") from exc

        thresholds = {"low": 0.35, "balanced": 0.25, "high": 0.18}
        if sensitivity not in thresholds:
            raise ValueError("Wake sensitivity must be low, balanced, or high")
        root = Path(model_dir).expanduser()
        files = {}
        for part in ("encoder", "decoder", "joiner"):
            choices = sorted(root.glob(f"{part}*.onnx"))
            preferred = [path for path in choices if "chunk-16" in path.name and ".int8." not in path.name]
            if preferred:
                files[part] = preferred[0]
            elif len(choices) == 1:
                files[part] = choices[0]
            else:
                raise RuntimeError(f"Select a sherpa-onnx model with one {part} ONNX file (prefer chunk-16 fp32)")
        files["tokens"] = root / "tokens.txt"
        self._temporary_keywords = None
        if keywords_file:
            words = Path(keywords_file).expanduser()
        else:
            self._temporary_keywords = tempfile.TemporaryDirectory(prefix="yumi-hey-yumi-")
            raw = Path(self._temporary_keywords.name) / "raw.txt"
            words = Path(self._temporary_keywords.name) / "keywords.txt"
            bpe = root / "bpe.model"
            lexicon = root / "en.phone"
            if bpe.is_file():
                command = [
                    sys.executable,
                    "-c",
                    "from sherpa_onnx.cli import cli; cli()",
                    "text2token",
                    "--tokens",
                    str(files["tokens"]),
                    "--tokens-type",
                    "bpe",
                    "--bpe-model",
                    str(bpe),
                ]
                # GigaSpeech's Y/UM/I spelling path often misses the name and
                # confuses "yummy". Encode its spoken /juː miː/ pronunciation;
                # the displayed and accepted wake phrase remains Hey Yumi.
                raw.write_text("HEY YOU ME @HEY_YUMI\n")
            elif lexicon.is_file():
                command = [
                    sys.executable,
                    "-c",
                    "from sherpa_onnx.cli import cli; cli()",
                    "text2token",
                    "--tokens",
                    str(files["tokens"]),
                    "--tokens-type",
                    "phone+ppinyin",
                    "--lexicon",
                    str(lexicon),
                ]
                raw.write_text("HEY YOU ME @HEY_YUMI\n")
            else:
                raise RuntimeError(
                    "Model needs bpe.model or en.phone to prepare Hey Yumi; supply --voice-keywords-file"
                )
            try:
                subprocess.run([*command, str(raw), str(words)], check=True, capture_output=True)
            except (OSError, subprocess.CalledProcessError) as exc:
                raise RuntimeError("Could not prepare Hey Yumi tokens with sherpa-onnx-cli") from exc
        missing = [str(path) for path in (*files.values(), words) if not path.is_file()]
        if missing:
            raise RuntimeError("Missing sherpa-onnx wake-word model files: " + ", ".join(missing))
        self._np = np
        self._spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(files["tokens"]),
            encoder=str(files["encoder"]),
            decoder=str(files["decoder"]),
            joiner=str(files["joiner"]),
            keywords_file=str(words),
            num_threads=1,
            keywords_score=1.0,
            keywords_threshold=thresholds[sensitivity],
            provider="cpu",
        )
        self._stream = self._spotter.create_stream()

    def process(self, frame: bytes) -> bool:
        if len(frame) != self.frame_length * 2:
            raise ValueError("Expected a 100 ms mono 16 kHz int16 microphone frame")
        samples = self._np.frombuffer(frame, dtype="<i2").astype(self._np.float32) / 32768.0
        self._stream.accept_waveform(self.sample_rate, samples)
        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
            # sherpa-onnx clears a hit as later chunks are decoded. Inspect
            # every decoded chunk, not just the last result for this frame.
            result = self._spotter.get_result(self._stream)
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except ValueError:
                    result = {"keyword": result}
            keyword = (
                str(result.get("keyword") or "").casefold().replace("_", " ").strip()
                if isinstance(result, dict)
                else ""
            )
            if keyword == "hey yumi":
                self._spotter.reset_stream(self._stream)
                return True
        return False

    def reset(self) -> None:
        self._stream = self._spotter.create_stream()

    def close(self) -> None:
        self._stream = None
        self._spotter = None
        if self._temporary_keywords is not None:
            self._temporary_keywords.cleanup()
