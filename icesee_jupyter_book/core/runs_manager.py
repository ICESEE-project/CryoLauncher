"""A thin ICESEE-side adapter over :mod:`run_records`, exposing exactly the
manager protocol CryoLauncher's shared
``cryostack_src.frontend.cryolauncher.workspace.run_history.build_workspace_history_panel``
expects (refresh / list_runs / select_run / selected_run / reconcile_run /
files / tail / delete_run).

This is deliberately NOT a re-implementation of
:class:`cryostack_src.workspace.manager.WorkspaceManager` -- that class also
owns example staging, dataset management, and the Advanced Editor, none of
which ICESEE has or needs. ICESEE only needs the narrow "list of runs, with
their local outputs" surface, backed by the same
``.cryostack-run.json`` manifests :mod:`run_records` already writes.
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from cryostack_src.workspace import RunInfo

from . import run_records


class IceseeRunsManager:
    """Read/write access to one user's ICESEE run history, for the shared
    Workspace history panel. Pure local filesystem state -- no SSH, no AWS."""

    def __init__(self, root: "Path | str | None" = None):
        self.root = Path(root) if root is not None else None
        self._runs: dict[str, RunInfo] = {}
        self._selected_run_id: str | None = None

    # -- discovery / selection --------------------------------------------
    def refresh(self) -> list[RunInfo]:
        discovered = run_records.discover_runs(self.root)
        self._runs = {run.id: run for run in discovered}
        if self._selected_run_id not in self._runs:
            self._selected_run_id = None
        return self.list_runs()

    def list_runs(self) -> list[RunInfo]:
        return sorted(self._runs.values(), key=lambda run: run.created, reverse=True)

    def select_run(self, run_id: str) -> "RunInfo | None":
        run = self._runs.get(run_id)
        self._selected_run_id = run.id if run else None
        return run

    def selected_run(self) -> "RunInfo | None":
        return self._runs.get(self._selected_run_id or "")

    def reconcile_run(self, run_id: str) -> "RunInfo | None":
        """ICESEE has no generic live-status resolver (yet): Remote's status
        check and Cloud's batch-status check already update the manifest
        directly from the gateway, on their own schedule. Reconcile is a
        pass-through -- never a fabricated status."""
        return self.select_run(run_id)

    # -- outputs -------------------------------------------------------
    def files(self, run_id: str) -> list[Path]:
        run = self._runs.get(run_id)
        if not run or not run.workspace_directory or not run.workspace_directory.exists():
            return []
        return sorted(p for p in run.workspace_directory.rglob("*") if p.is_file())

    def tail(self, run_id: str) -> str:
        run = self._runs.get(run_id)
        if not run or not run.workspace_directory:
            return "No run selected."
        log_path = run.workspace_directory / "run.log"
        if log_path.is_file():
            return log_path.read_text(encoding="utf-8", errors="replace")
        return "(no local log captured for this run yet)"

    def _zip_subdir(self, run_id: str, subdir: str, zip_name: str) -> "Path | None":
        run = self._runs.get(run_id)
        if not run or not run.workspace_directory:
            return None
        src = run.workspace_directory / subdir
        if not src.is_dir() or not any(src.iterdir()):
            return None
        zip_path = run.workspace_directory / zip_name
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(src.rglob("*")):
                if path.is_file():
                    zf.write(path, arcname=path.relative_to(src))
        return zip_path

    def download_results(self, run_id: str) -> "Path | None":
        return self._zip_subdir(run_id, "results", "results_bundle.zip")

    def download_figures(self, run_id: str) -> "Path | None":
        return self._zip_subdir(run_id, "figures", "figures_bundle.zip")

    # -- lifecycle -------------------------------------------------------
    def _owns(self, workspace: Path) -> bool:
        try:
            base = self.root if self.root is not None else run_records.runs_root()
            return workspace.resolve().is_relative_to(Path(base).resolve())
        except (OSError, ValueError, RuntimeError):
            return False

    def delete_run(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if not run or not run.workspace_directory:
            return False
        if not self._owns(run.workspace_directory):
            return False
        shutil.rmtree(run.workspace_directory, ignore_errors=True)
        self._runs.pop(run_id, None)
        if self._selected_run_id == run_id:
            self._selected_run_id = None
        return True
