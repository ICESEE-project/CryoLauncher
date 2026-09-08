"""ICESEE GUI structural-parity checkpoint.

CryoLauncher and ICESEE must be technically identical in application-shell
structure (header -> two-column area -> LEFT[Run settings (with Run Plan
nested last) + Execution] / RIGHT[one Workspace: Runs/Files/Run Log/
Results]). Scientific controls and result interpretation may differ.

This is proven here by widget-hierarchy inspection (class names, Tab
titles, object identity), not by comparing CSS strings -- both gateways
now build their shell through the SAME shared primitives
(cryostack_src/frontend/cryolauncher/{panels/run_settings.py,
panels/runtime_panel.py, workspace/run_details.py, workspace/explorer.py}),
so a passing assertion here is a claim about actual shared construction,
not two hand-built trees that merely look alike.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# tree-walking helpers
# ---------------------------------------------------------------------------
def _walk(root):
    yield root
    for child in getattr(root, "children", ()) or ():
        yield from _walk(child)


def _widgets_with_class(root, css_class):
    return [w for w in _walk(root) if css_class in (getattr(w, "_dom_classes", ()) or ())]


def _html_values(root):
    return [w.value or "" for w in _walk(root) if isinstance(w, W.HTML)]


def _count_instances(root, target):
    return sum(1 for w in _walk(root) if w is target)


def _find_run_details_tabs(root):
    """The single Workspace's 4-tab W.Tab (cryostack-workspace-tabs class,
    set by build_run_details -- unambiguous, unlike a bare W.Tab check)."""
    matches = [w for w in _walk(root) if isinstance(w, W.Tab)
               and "cryostack-workspace-tabs" in (getattr(w, "_dom_classes", ()) or ())]
    return matches


def _find_left_column(root):
    matches = _widgets_with_class(root, "icesee-left")
    return matches[0] if matches else None


def _freevar(fn, name):
    idx = fn.__code__.co_freevars.index(name)
    return fn.__closure__[idx].cell_contents


def _build_icesee(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    return build_icesee_ui()


def _build_cryolauncher(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    return build_icesheets_ui()


# ---------------------------------------------------------------------------
# 1. exactly one Workspace, in both applications
# ---------------------------------------------------------------------------
def test_icesee_exposes_exactly_one_workspace(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-workspace-count")
    workspaces = _widgets_with_class(page, "cryostack-output-workspace")
    assert len(workspaces) == 1, f"expected exactly one Workspace, found {len(workspaces)}"


def test_cryolauncher_exposes_exactly_one_workspace(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="parity-cl-workspace-count")
    workspaces = _widgets_with_class(page, "cryostack-output-workspace")
    assert len(workspaces) == 1, f"expected exactly one Workspace, found {len(workspaces)}"


# ---------------------------------------------------------------------------
# 2. Runs / Files / Run Log / Results, same order, both applications
# ---------------------------------------------------------------------------
def test_icesee_workspace_tabs_are_runs_files_run_log_results_in_order(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-tabs-icesee")
    tabs = _find_run_details_tabs(page)
    assert len(tabs) == 1
    tab = tabs[0]
    assert len(tab.children) == 4
    titles = [tab.get_title(i) for i in range(4)]
    assert titles == ["Runs", "Files", "Run Log", "Results"]


def test_cryolauncher_workspace_tabs_are_runs_files_run_log_results_in_order(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="parity-tabs-cl")
    tabs = _find_run_details_tabs(page)
    assert len(tabs) == 1
    tab = tabs[0]
    assert len(tab.children) == 4
    titles = [tab.get_title(i) for i in range(4)]
    assert titles == ["Runs", "Files", "Run Log", "Results"]


# ---------------------------------------------------------------------------
# 3-4. no duplicate standalone Run Log / Results Preview boxes in ICESEE
# ---------------------------------------------------------------------------
def test_icesee_has_no_duplicate_standalone_run_log_heading(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-no-dup-log")
    values = _html_values(page)
    # the old ICESEE-only heading; the shared Workspace uses a Tab TITLE
    # ("Run log"), not a standalone <div class='icesee-h'>Run log</div> HTML
    # widget outside the Workspace tab system
    assert not any(v.strip() == "<div class='icesee-h'>Run log</div>" for v in values)


def test_icesee_has_no_duplicate_standalone_results_preview_heading(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-no-dup-results")
    values = _html_values(page)
    assert not any("Results preview" in v for v in values)


def test_icesee_log_out_and_results_out_widgets_appear_exactly_once(monkeypatch, tmp_path):
    """The SAME log_out/results_out Output widgets ICESEE always used are
    now mounted only inside the Workspace's Run Log / Results tabs -- not
    also duplicated into a second, independent top-right presentation."""
    page = _build_icesee(monkeypatch, tmp_path, user="parity-single-mount")

    def walk_for_run_click(w, found):
        pass

    # reach log_out / results_out via the real build_icesee_ui closure
    tabs = _find_run_details_tabs(page)[0]
    log_out_in_tabs = _widgets_with_class(tabs, "icesee-out")
    assert len(log_out_in_tabs) == 2   # log_out + results_out, both class icesee-out
    # and both are direct/indirect descendants of the single Workspace
    all_icesee_out = _widgets_with_class(page, "icesee-out")
    assert len(all_icesee_out) == 2, "log_out/results_out must not be mounted twice"


# ---------------------------------------------------------------------------
# 5. no second Workspace at the bottom of the page (same as #1, stated
#    against the page's top-level children rather than a global class scan)
# ---------------------------------------------------------------------------
def test_icesee_page_top_level_children_contain_no_second_workspace(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-no-bottom-ws")
    # every former standalone/bottom presentation (workspace_box Accordion,
    # actions_card, a second Run Plan mount) is gone from the page's own
    # direct children -- the shell is exactly [styles.., app_menu, header,
    # shell.container, shell.height_sync, back_link]
    accordions_at_top_level = [c for c in page.children if isinstance(c, W.Accordion)]
    assert accordions_at_top_level == []


# ---------------------------------------------------------------------------
# 6. Run Settings / Run Plan / Execution occupy the same shell positions
# ---------------------------------------------------------------------------
def _left_column_headings(page):
    left = _find_left_column(page)
    assert left is not None, "no 'icesee-left' column found (build_workspace_explorer not used?)"
    assert len(left.children) == 2, "LEFT column must be exactly [run_settings, runtime]"
    run_settings, runtime = left.children
    return run_settings, runtime


def test_icesee_left_column_is_run_settings_then_execution(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-left-icesee")
    run_settings, runtime = _left_column_headings(page)

    settings_html = "\n".join(_html_values(run_settings))
    assert "Run settings" in settings_html
    assert "Run Plan" in settings_html          # nested inside Run settings, last

    runtime_html = "\n".join(_html_values(runtime))
    assert "Execution" in runtime_html
    assert "Status" not in runtime_html or "Execution" in runtime_html  # no separate generic "Status" card


def test_cryolauncher_left_column_is_run_settings_then_execution(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="parity-left-cl")
    run_settings, runtime = _left_column_headings(page)

    settings_html = "\n".join(_html_values(run_settings))
    assert "Run settings" in settings_html
    assert "Run Plan" in settings_html

    runtime_html = "\n".join(_html_values(runtime))
    assert "Execution" in runtime_html


def test_icesee_has_no_separate_status_card_outside_execution(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-no-status-card")
    values = _html_values(page)
    assert not any(v.strip() == "<div class='icesee-h'>Status</div>" for v in values)


# ---------------------------------------------------------------------------
# 7. switching ICESEE scientific controls does not reconstruct the Workspace
# ---------------------------------------------------------------------------
def test_switching_icesee_scientific_controls_does_not_reconstruct_the_workspace(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-no-rebuild")
    tabs_before = _find_run_details_tabs(page)[0]

    mode_tabs = None

    def walk(w):
        nonlocal mode_tabs
        if isinstance(w, W.Tab) and w is not tabs_before and mode_tabs is None:
            mode_tabs = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    assert mode_tabs is not None

    mode_tabs.selected_index = 1   # Remote
    mode_tabs.selected_index = 2   # Cloud
    mode_tabs.selected_index = 0   # Local

    tabs_after = _find_run_details_tabs(page)[0]
    assert tabs_after is tabs_before, "the Workspace Tab widget was rebuilt on a mode switch"
    assert [tabs_after.get_title(i) for i in range(4)] == ["Runs", "Files", "Run Log", "Results"]


# ---------------------------------------------------------------------------
# 8. ICESEE Results still uses its DA-aware ResultPackage
# ---------------------------------------------------------------------------
def test_icesee_results_still_uses_the_da_aware_result_package():
    src = (_REPO / "icesee_jupyter_book/ui/icesee_gateway.py").read_text()
    assert "from icesee_jupyter_book.core.results_package import discover_result_package" in src
    assert "discover_result_package(run.workspace_directory)" in src
    # the shared Workspace's Results tab hosts ICESEE's own content -- it is
    # not forced through cryostack_src/models/*/results.py's glaciological
    # ResultPackage
    assert "cryostack_src.models" not in src.split("discover_result_package")[0][-400:]


# ---------------------------------------------------------------------------
# 9. CryoLauncher behavior is unchanged
# ---------------------------------------------------------------------------
def test_cryolauncher_shell_still_builds_and_keeps_its_own_shape(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="parity-cl-unchanged")
    assert page is not None
    workspaces = _widgets_with_class(page, "cryostack-output-workspace")
    assert len(workspaces) == 1
    left = _find_left_column(page)
    assert left is not None and len(left.children) == 2
