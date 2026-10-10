from yumi.voice import coreaudio


def test_non_macos_does_not_load_coreaudio(monkeypatch):
    monkeypatch.setattr(coreaudio.sys, "platform", "linux")
    monkeypatch.setattr(coreaudio, "_libraries", lambda: (_ for _ in ()).throw(AssertionError("must not load")))
    assert coreaudio.output_format("speaker") is None


def test_output_format_uses_native_output_device_not_same_named_microphone(monkeypatch):
    monkeypatch.setattr(coreaudio.sys, "platform", "darwin")
    monkeypatch.setattr(coreaudio, "_name", lambda _: "speaker")
    properties = {
        (1, "dev#"): [2, 3],
        (2, "stm#"): [],
        (3, "stm#"): [4],
        (3, "nsrt"): 44100.0,
        (3, "tran"): coreaudio._fourcc("blue"),
    }
    monkeypatch.setattr(coreaudio, "_property", lambda obj, sel, *a, **kw: properties[(obj, sel)])
    assert coreaudio.output_format("speaker") == coreaudio.OutputFormat(44100.0, True)


def test_ambiguous_output_is_not_treated_as_verified(monkeypatch):
    monkeypatch.setattr(coreaudio.sys, "platform", "darwin")
    monkeypatch.setattr(coreaudio, "_name", lambda _: "speaker")
    monkeypatch.setattr(coreaudio, "_property", lambda obj, sel, **kw: [2, 3] if sel == "dev#" else [4])
    assert coreaudio.output_format("speaker") is None
