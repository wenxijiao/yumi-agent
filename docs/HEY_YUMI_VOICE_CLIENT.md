# Hey Yumi voice client

`yumi --voice-client` runs on the computer with the microphone. It detects **Hey Yumi** locally with sherpa-onnx, then sends the next utterance to the existing Yumi speech-to-text, chat, and spoken-reply APIs. It can use a local Yumi server or a signed-in Yumi Nexus account. Only the utterance after a wake is uploaded; the wake-word audio stays on this computer.

Install the optional engine in the same Python environment as `yumi`:

```bash
pip install 'yumi-agent[voice-sherpa]'
```

Supply a sherpa-onnx keyword-spotting model directory containing `tokens.txt`, `encoder*.onnx`, `decoder*.onnx`, `joiner*.onnx`, and either `bpe.model` or `en.phone`. The [sherpa-onnx model catalog](https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html) lists models and downloads. Yumi does not distribute model weights; check the license of the model you select before commercial use or redistribution. The English GigaSpeech 3.3M keyword-spotting model is a starting point for testing. You can provide a pre-tokenized `HEY YUMI` keyword file with `--voice-keywords-file` instead of relying on automatic tokenization.

For a local Yumi server:

```bash
yumi --server
yumi --voice-client --voice-mode local --voice-model-dir /path/to/kws-model
```

For Nexus, on the computer with the microphone:

```bash
yumi --voice-client --voice-mode nexus --voice-model-dir /path/to/kws-model
```

The first Nexus run opens a browser for account sign-in and device approval. The terminal displays a code to compare with the browser. The resulting device credential is stored at `~/.yumi/voice-client.json` with private file permissions; later runs reuse it. `yumi --voice-client --voice-logout` revokes it on Nexus and removes the local copy. To use a self-hosted or development API, pass `--voice-server URL`; remote Nexus URLs require HTTPS. Use `--voice-input-device INDEX` to select a microphone.

The client stops microphone capture while processing and playing an answer, so it does not wake itself. A tool action that needs explicit confirmation is denied for that voice turn; approve such actions in the Yumi app instead. A working speech-to-text and text-to-speech provider must be configured on the server. Wake accuracy depends on the selected model, microphone and room noise; test the exact “Hey Yumi” phrase with real speakers before relying on it.
