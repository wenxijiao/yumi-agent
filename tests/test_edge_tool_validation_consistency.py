"""Tool-name validation is enforced at every entry point (follow-up review).

Covers: the shared edge mount helper (register + update_tools), the combined
prefix+name length budget, the FlatEdgeScope prefix reusing the canonical
sanitizer, and local server-tool registration.
"""

import pytest
from yumi.core.features.edge import api as edge_api
from yumi.core.platform.plugins.single_user import FlatEdgeScope
from yumi.core.platform.tools.tool import TOOL_REGISTRY, register_tool


def test_mount_edge_tools_skips_invalid_and_reports_them():
    edge_api.EDGE_TOOLS_REGISTRY.pop("ck1", None)
    tools = [
        {"function": {"name": "good_tool"}},
        {"function": {"name": "bad name"}},  # space -> provider-invalid
    ]
    skipped = edge_api._mount_edge_tools("ck1", "edge_x__", tools)
    reg = edge_api.EDGE_TOOLS_REGISTRY["ck1"]
    assert "edge_x__good_tool" in reg
    assert skipped == ["bad name"]
    assert not any("bad name" in k for k in reg)
    edge_api.EDGE_TOOLS_REGISTRY.pop("ck1", None)


def test_mount_edge_tools_enforces_combined_length_budget():
    edge_api.EDGE_TOOLS_REGISTRY.pop("ck2", None)
    long_tool = "t" * 60  # "edge_x__" (8) + 60 = 68 > 64
    skipped = edge_api._mount_edge_tools("ck2", "edge_x__", [{"function": {"name": long_tool}}])
    assert skipped == [long_tool]
    assert edge_api.EDGE_TOOLS_REGISTRY["ck2"] == {}
    edge_api.EDGE_TOOLS_REGISTRY.pop("ck2", None)


def test_flat_edge_scope_prefix_is_provider_safe_and_collision_free():
    scope = FlatEdgeScope()
    p1 = scope.tool_register_prefix(None, "my.device")
    p2 = scope.tool_register_prefix(None, "my device")
    # provider-safe ('.' normalized like the canonical helper)
    assert p1.startswith("edge_my_device_") and p1.endswith("__")
    assert "." not in p1
    # two names that sanitize the same still get DISTINCT prefixes (hash), so
    # they can't expose duplicate provider function names
    assert p1 != p2


def test_register_tool_rejects_invalid_local_name():
    with pytest.raises(ValueError):
        register_tool(lambda: 1, "desc", name="bad name")
    with pytest.raises(ValueError):
        register_tool(lambda: 1, "desc", name="dot.name")
    register_tool(lambda: 1, "desc", name="valid_local_tool_xyz")
    assert "valid_local_tool_xyz" in TOOL_REGISTRY
    TOOL_REGISTRY.pop("valid_local_tool_xyz", None)
