"""ICESEE/CryoLauncher naming + Run Plan layout cleanup.

1. Browser/tab naming: icesheets_voila (CryoLauncher's gateway) must present
   as "CryoLauncher"; run_center_voila (ICESEE's gateway) must present as
   "ICESEE". Both the warmup "starting" page label (bin/icesee_app.py) and
   the actual running app's own document.title are covered.
2. ICESEE no longer runs on GHUB -- no active ICESEE UI/vocabulary may
   still say so.
3. The Run Plan's execution-summary rows use the SAME shared row markup
   (icesee-summary / icesee-summary-k) in both gateways, with a shared CSS
   rule giving the label column consistent width/spacing instead of the
   label and value running together.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_ICESEE_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"
_CRYOLAUNCHER_GW = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"
_APP_PY = _REPO / "bin/icesee_app.py"
_STYLES = _REPO / "icesee_jupyter_book/ui/shared_app_styles.py"


# ── 1. browser/tab naming ──────────────────────────────────────────────
def test_warmup_labels_match_the_actual_applications():
    src = _APP_PY.read_text()
    assert 'return await _proxy_application(request, state.run_center, "ICESEE")' in src
    assert 'return await _proxy_application(request, state.icesheets, "CryoLauncher")' in src
    assert '"IceSheets"' not in src


def test_running_apps_set_their_own_document_title():
    icesee_src = _ICESEE_GW.read_text()
    cryolauncher_src = _CRYOLAUNCHER_GW.read_text()
    assert "document.title = 'ICESEE'" in icesee_src
    assert "document.title = 'CryoLauncher'" in cryolauncher_src


def test_notebook_routing_is_unchanged():
    """Display-name fix only -- routes/filenames are untouched."""
    src = _APP_PY.read_text()
    assert '"run_center_voila.ipynb"' in src
    assert '"icesheets_voila.ipynb"' in src
    assert '"/icesheets/"' in src or "--Voila.base_url=/icesheets/" in src


# ── 2. no GHUB in active ICESEE UI ─────────────────────────────────────
def test_icesee_gateway_has_no_ghub_reference():
    assert "GHUB" not in _ICESEE_GW.read_text()


def test_icesee_example_registry_has_no_ghub_reference():
    src = (_REPO / "icesee_jupyter_book/core/example_registry.py").read_text()
    assert "GHUB" not in src


def _build_icesee(monkeypatch, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    return build_icesee_ui()


def test_built_icesee_page_never_renders_ghub(monkeypatch):
    page = _build_icesee(monkeypatch, user="no-ghub-user")
    texts = []

    def walk(w):
        if isinstance(w, W.HTML):
            texts.append(w.value or "")
        if isinstance(w, W.Tab):
            for i in range(len(w.children)):
                texts.append(w.get_title(i) or "")
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    blob = "\n".join(texts)
    assert "GHUB" not in blob


def test_local_mode_tab_and_run_plan_backend_label_are_ghub_free(monkeypatch):
    page = _build_icesee(monkeypatch, user="local-label-user")

    mode_tabs = None

    def walk(w):
        nonlocal mode_tabs
        if isinstance(w, W.Tab) and mode_tabs is None:
            mode_tabs = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    assert mode_tabs is not None
    assert mode_tabs.get_title(0) == "Local"


# ── 3. shared Run Plan row layout ──────────────────────────────────────
def test_icesee_run_plan_reuses_cryolaunchers_summary_row_markup():
    icesee_src = _ICESEE_GW.read_text()
    cryolauncher_src = _CRYOLAUNCHER_GW.read_text()
    assert "class='icesee-summary'" in icesee_src
    assert "class='icesee-summary-k'" in icesee_src
    assert 'class="icesee-summary-k"' in cryolauncher_src
    # no second, ICESEE-only row convention left behind for Run Plan
    assert "cryostack-selected-run-card" not in icesee_src.split(
        "_update_icesee_run_plan_summary"
    )[1].split("def ")[0]


def test_shared_summary_css_gives_labels_a_consistent_column_and_gap():
    css = _STYLES.read_text()
    assert ".cryostack-summary > div" in css and ".icesee-summary > div" in css
    block = css[css.index(".cryostack-summary > div"):]
    block = block[:block.index("}") + 1]
    assert "display: flex" in block
    assert "gap:" in block
    key_block = css[css.index(".cryostack-summary-key"):]
    key_block = key_block[:key_block.index("}", key_block.index("min-width"))]
    assert "min-width:" in key_block


def test_run_plan_rows_render_with_the_shared_markup_and_a_colon(monkeypatch):
    page = _build_icesee(monkeypatch, user="run-plan-markup-user")
    summary = None

    def walk(w):
        nonlocal summary
        if isinstance(w, W.HTML) and "Execution mode" in (w.value or "") and summary is None:
            summary = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    assert summary is not None
    assert "class='icesee-summary'" in summary.value
    assert "Execution mode:</span>" in summary.value
    assert "Compute backend:</span> Local" in summary.value
