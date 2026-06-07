"""Edge workspace scaffolding (``yumi --edge``) helpers."""

import os
import tempfile

import pytest
import yumi.cli as cli
from yumi.edge.client import init_workspace


def test_parse_edge_langs_none():
    assert cli._parse_edge_langs(None) is None


def test_parse_edge_langs_single():
    assert cli._parse_edge_langs(["python"]) == ["python"]


def test_parse_edge_langs_repeatable_dedupes():
    assert cli._parse_edge_langs(["rust", "python", "rust"]) == ["rust", "python"]


def test_parse_edge_langs_comma_separated():
    assert cli._parse_edge_langs(["rust,python"]) == ["rust", "python"]


def test_parse_edge_langs_mixed():
    assert cli._parse_edge_langs(["rust,go", "python"]) == ["rust", "go", "python"]


def test_init_workspace_multi_lang_creates_both_trees():
    with tempfile.TemporaryDirectory() as tmp:
        init_workspace(tmp, lang=["python", "rust"])
        assert os.path.isfile(os.path.join(tmp, "yumi_tools", "python", "yumi_setup.py"))
        assert os.path.isfile(os.path.join(tmp, "yumi_tools", "rust", "Cargo.toml"))


def test_init_workspace_creates_root_agent_guide():
    with tempfile.TemporaryDirectory() as tmp:
        created = init_workspace(tmp, lang=["python"])
        guide_path = os.path.join(tmp, "AGENTS.md")

        assert "AGENTS.md" in created
        assert os.path.isfile(guide_path)
        with open(guide_path, encoding="utf-8") as fh:
            guide = fh.read()

        assert "Yumi Edge Agent Guide" in guide
        assert "yumi_tools/python/yumi_setup.py" in guide
        assert "yumi/sdk/AGENTS.md" in guide


def test_init_workspace_creates_agent_guide_when_target_dir_is_missing():
    with tempfile.TemporaryDirectory() as tmp:
        workspace = os.path.join(tmp, "new-edge-project")
        init_workspace(workspace, lang=["python"])

        assert os.path.isfile(os.path.join(workspace, "AGENTS.md"))
        assert os.path.isfile(os.path.join(workspace, "yumi_tools", "python", "yumi_setup.py"))


def test_init_workspace_does_not_overwrite_existing_agent_guide():
    with tempfile.TemporaryDirectory() as tmp:
        guide_path = os.path.join(tmp, "AGENTS.md")
        with open(guide_path, "w", encoding="utf-8") as fh:
            fh.write("custom project instructions\n")

        created = init_workspace(tmp, lang=["python"])

        assert "AGENTS.md" not in created
        with open(guide_path, encoding="utf-8") as fh:
            assert fh.read() == "custom project instructions\n"


def test_init_workspace_rejects_unknown_lang():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match="Unsupported language"):
            init_workspace(tmp, lang=["python", "not-a-lang"])
