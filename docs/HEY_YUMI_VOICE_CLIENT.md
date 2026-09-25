# Hey Yumi voice

`yumi --voice` runs on the computer with the microphone. It offers two choices: a local Yumi model through the local server, or sign in to Yumi Nexus. It detects **Hey Yumi** locally with sherpa-onnx, then sends the next utterance to the existing Yumi speech-to-text, chat, and spoken-reply APIs. Only the utterance after a wake is uploaded; the wake-word audio stays on this computer.

Install the optional engine in the same Python environment as `yumi`:

```bash
pip install 'yumi-agent[voice-sherpa]'
```

Supply a sherpa-onnx keyword-spotting model directory containing `tokens.txt`, `encoder*.onnx`, `decoder*.onnx`, `joiner*.onnx`, and either `bpe.model` or `en.phone`. The [sherpa-onnx model catalog](https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html) lists models and downloads. Yumi does not distribute model weights; check the license of the model you select before commercial use or redistribution. The English GigaSpeech 3.3M keyword-spotting model is a starting point for testing. You can provide a pre-tokenized `HEY YUMI` keyword file with `--voice-keywords-file` instead of relying on automatic tokenization.

Set the wake-word model path once using `voice_sherpa_model_dir` in `~/.yumi/config.json`, `YUMI_VOICE_MODEL_DIR`, or `--voice-model-dir`. Then run:

```bash
yumi --server
yumi --voice
```

Choose **1** for the running local server or **2** to sign in to Nexus. For scripts or terminals without input, pass `--voice-mode local` or `--voice-mode nexus`.

The first Nexus run opens a browser for account sign-in and device approval. The terminal displays a code to compare with the browser. The resulting device credential is stored at `~/.yumi/voice-client.json` with private file permissions; later runs reuse it. `yumi --voice --voice-logout` revokes it on Nexus and removes the local copy. To use a self-hosted or development API, pass `--voice-server URL`; remote Nexus URLs require HTTPS. Use `--voice-input-device INDEX` to select a microphone.

The client stops microphone capture while processing and playing an answer, so it does not wake itself. A tool action that needs explicit confirmation is denied for that voice turn; approve such actions in the Yumi app instead. A working speech-to-text and text-to-speech provider must be configured on the server. Wake accuracy depends on the selected model, microphone and room noise; test the exact “Hey Yumi” phrase with real speakers before relying on it.
