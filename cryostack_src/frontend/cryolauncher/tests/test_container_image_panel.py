"""The container image selector: tested dropdown + advanced custom image."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.frontend.cryolauncher.container_image import (
    build_container_image_panel,
)

# v1.0.1 is the current default tested image (adds the AWS CLI for cloud
# S3 sync); v1.0.0 stays a selectable option (never removed), just no
# longer the default -- see cryostack_src/models/stack/images.py.
_REF = "bkyanjo/icesee-combined:v1.0.1"
_OLD_KEY = "icesee-combined-v1.0.0"
_CUSTOM = "__custom__"


def _option_values(panel):
    return [v for _l, v in panel._state["dropdown"].options]


def test_docker_oci_defaults_to_the_combined_tested_image():
    p = build_container_image_panel()          # defaults to issm / tested
    sel = p.selection()
    assert sel.mode == "tested"
    assert sel.tested_key == "icesee-combined-v1.0.1"
    assert sel.image_uri == _REF
    assert p.validate() is None


def test_tested_issm_shows_only_compatible_tested_images():
    p = build_container_image_panel()
    p.set_model("issm")
    # tested profile => curated list only, no "Custom image…" -- both
    # tested releases are offered, the current default (v1.0.1) first
    assert _option_values(p) == ["icesee-combined-v1.0.1", _OLD_KEY]


def test_tested_icepack_also_sees_the_combined_image():
    p = build_container_image_panel()
    p.set_model("icepack")
    assert _option_values(p) == ["icesee-combined-v1.0.1", _OLD_KEY]
    assert p.selection().image_uri == _REF


def test_tested_selection_hides_the_custom_uri_field():
    p = build_container_image_panel()
    assert p._state["custom_uri"].layout.display == "none"


def test_custom_profile_exposes_custom_option_and_field():
    p = build_container_image_panel()
    p.set_profile("custom")
    assert _CUSTOM in _option_values(p)
    p._state["dropdown"].value = _CUSTOM
    assert p._state["custom_uri"].layout.display == ""
    assert p.selection().mode == "custom"


def test_empty_custom_uri_blocks_submit():
    p = build_container_image_panel()
    p.set_profile("custom")
    p._state["dropdown"].value = _CUSTOM
    assert p.validate() is not None
    p._state["custom_uri"].value = "  "
    assert p.validate() is not None
    p._state["custom_uri"].value = "ghcr.io/my-org/icesee:dev"
    assert p.validate() is None


def test_custom_uri_must_look_like_an_oci_reference():
    p = build_container_image_panel()
    p.set_profile("custom")
    p._state["dropdown"].value = _CUSTOM
    p._state["custom_uri"].value = "not a ref"
    assert p.validate() is not None


def test_switching_back_to_tested_restores_a_tested_default():
    p = build_container_image_panel()
    p.set_profile("custom")
    p._state["dropdown"].value = _CUSTOM
    p.set_profile("tested")
    assert _CUSTOM not in _option_values(p)
    assert p.selection().mode == "tested"
    assert p.selection().image_uri == _REF


def test_on_change_fires_for_dropdown_and_custom_text():
    p = build_container_image_panel()
    hits = []
    p.on_change(lambda: hits.append(1))
    p.set_profile("custom")
    p._state["dropdown"].value = _CUSTOM
    p._state["custom_uri"].value = "ghcr.io/x/y:1"
    assert len(hits) >= 2
