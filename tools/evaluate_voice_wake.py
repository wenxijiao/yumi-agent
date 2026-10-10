"""Reproducible macOS synthetic wake regression; no microphone or cloud requests.

Run with the repository's Python environment:
  python tools/evaluate_voice_wake.py --output /tmp/yumi-wake-report.json

This is not a real-speaker accuracy benchmark. Temporary synthesized WAVs are
removed when finished. Near-homophones are deliberately included as negatives.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
import sentencepiece
from yumi.voice.duplex import decode_audio
from yumi.voice.models import ensure_model
from yumi.voice.sherpa_wake import SherpaHeyYumiWake

VOICES = ["Samantha", "Eddy (English (US))", "Karen", "Daniel", "Tessa", "Rishi", "Tingting", "Kyoko"]
PHRASES = {
    "wake": "Hey Yumi.",
    "command": "Hey Yumi, tell me the time.",
    "siri": "Hey Siri.",
    "hello": "Hello Yumi.",
    "music": "Play some music.",
    "yummy": "Hey yummy.",
    "hear": "Can you hear me?",
    "you": "Hey you.",
    "amy": "Hey Amy.",
    "weather": "The weather is nice today.",
}


def narrowband(audio: bytes, rate: int) -> bytes:
    pcm = decode_audio(audio, rate)
    if rate == 16000:
        return pcm
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)
    return decode_audio(out.getvalue(), 16000)


def evaluate(output: Path):
    root = Path(ensure_model())
    rows = []
    with tempfile.TemporaryDirectory(prefix="yumi-wake-eval-") as folder:
        folder = Path(folder)
        baseline = folder / "baseline.txt"
        sp = sentencepiece.SentencePieceProcessor(model_file=str(root / "bpe.model"))
        baseline.write_text(" ".join(sp.encode("HEY YUMI", out_type=str)) + "\n")
        detectors = {
            "baseline": SherpaHeyYumiWake(str(root), str(baseline)),
            "updated": SherpaHeyYumiWake(str(root)),
        }
        try:
            for voice in VOICES:
                for label, text in PHRASES.items():
                    wav = folder / "sample.wav"
                    subprocess.run(
                        ["say", "-v", voice, "-o", str(wav), "--file-format=WAVE", "--data-format=LEI16@16000", text],
                        check=True,
                        capture_output=True,
                    )
                    for rate in (16000, 8000):
                        raw = narrowband(wav.read_bytes(), rate)
                        for volume in (1.0, 0.15):
                            pcm = (np.frombuffer(raw, dtype="<i2").astype(np.float32) * volume).astype("<i2").tobytes()
                            pcm = bytes(16000) + pcm + bytes(32000)
                            for variant, detector in detectors.items():
                                detector.reset()
                                hits = []
                                for i in range(0, len(pcm), 3200):
                                    if detector.process(pcm[i : i + 3200].ljust(3200, b"\0")):
                                        hits.append(round(i / 32000, 2))
                                rows.append(
                                    dict(
                                        variant=variant,
                                        voice=voice,
                                        text=text,
                                        label=label,
                                        rate=rate,
                                        volume=volume,
                                        positive=label in {"wake", "command"},
                                        hits=hits,
                                    )
                                )
                print("Evaluated", voice, flush=True)
        finally:
            for detector in detectors.values():
                detector.close()
    summary = {}
    for variant in ("baseline", "updated"):
        selected = [r for r in rows if r["variant"] == variant]
        positive = [r for r in selected if r["positive"]]
        negative = [r for r in selected if not r["positive"]]
        summary[variant] = dict(
            hits=sum(bool(r["hits"]) for r in positive),
            positives=len(positive),
            false_hits=sum(bool(r["hits"]) for r in negative),
            negatives=len(negative),
        )
    output.write_text(
        json.dumps({"method": "macOS say synthetic speech; no microphone", "summary": summary, "rows": rows}, indent=2)
    )
    print(json.dumps(summary, indent=2))
    print("Saved", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    evaluate(parser.parse_args().output)
