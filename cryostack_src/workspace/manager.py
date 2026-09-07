from __future__ import annotations

import base64
import html
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from IPython.display import HTML, Image, display

from .files import EDITABLE_SUFFIXES, list_editable_files
from .identity import WorkspaceUser, resolve_workspace_user
from .manifest import MANIFEST_NAME, read_manifest, write_manifest
from .models import RunInfo
from .roots import WORKSPACE_ROOT_ENV  # noqa: F401 -- re-exported for callers

_SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SAFE_EXAMPLE_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _file_source_materializer(suffix: str):
    """Resolve the materializer for a single-FILE example source, dispatched
    by file TYPE (never by filename) -- ``None`` for an unsupported type.

    Lazily imported so this generic, model-neutral module carries no
    top-level dependency on any one model adapter (same pattern already used
    for the result-reader/visualizer dispatch below).
    """
    if suffix.lower() == ".ipynb":
        from cryostack_src.models.icepack.notebook import materialize_notebook_workspace

        return materialize_notebook_workspace
    return None


class WorkspacePermissionError(RuntimeError):
    """A file operation was attempted outside the caller's managed workspace."""


class _FixedChoice:
    """Adapts a fixed model *string* to the ``value`` / ``options`` / ``observe``
    shape :class:`WorkspaceManager` expects from a model-selector widget.

    IceSheets passes a real dropdown (the user picks ISSM / Icepack). An app
    with a single model (ICESEE) passes the model name as a plain string and
    this stands in -- no dropdown, nothing to observe.
    """

    def __init__(self, value: str) -> None:
        self.value = value
        self.options = ((value, value),)

    def observe(self, *_a, **_k) -> None:  # pragma: no cover - inert
        pass


# ── model-adapter dispatch for result reading / visualization ──────────────
# The generic workspace layer never imports a model directly: it asks the
# adapter for its result reader / visualizer. Models that have not implemented
# these yet (Icepack, for now) simply return nothing and the Results tab
# degrades gracefully.
def _result_reader_for(model: str):
    # P2: the model-neutral result contract owns this dispatch now.
    from cryostack_src.models.results_common import resolve_result_reader
    return resolve_result_reader(model)


def _visualizer_for(model: str):
    from cryostack_src.models.results_common import resolve_visualizer
    return resolve_visualizer(model)


class StagedExample:
    """A user-owned working copy of an example, staged for a run.

    The canonical example is never touched: when ``source`` is a bundled
    (canonical) example a fresh copy is made under the authenticated user's
    workspace; when ``source`` is already user-owned it is used in place.
    """

    __slots__ = ("path", "source", "from_canonical", "provenance")

    def __init__(self, *, path: Path, source: str, from_canonical: bool, provenance: dict) -> None:
        self.path = path
        self.source = source
        self.from_canonical = from_canonical
        self.provenance = provenance


class WorkspaceManager:
    """Own CryoLauncher workspace and result filesystem operations."""

    def __init__(
        self,
        *,
        status,
        session,
        example_dir,
        model,
        backend,
        file_picker,
        file_editor,
        log_output,
        results_output,
        cluster_host,
        cluster_user,
        cluster_port,
        access_mode,
        normalize_remote_path,
        connector_fetch_archive,
        should_use_connector,
        connector_ssh,
        ssh_run,
        cluster_name,
        owner: WorkspaceUser | None = None,
        workspace_root: str | Path | None = None,
        require_authenticated: bool = True,
    ) -> None:
        self.status = status
        self.session = session
        self.example_dir = example_dir
        #: ``model`` may be a selector widget (IceSheets) or a fixed model name
        #: string (single-model apps like ICESEE).
        self.model = _FixedChoice(model) if isinstance(model, str) else model
        self.backend = backend
        self.file_picker = file_picker
        self.file_editor = file_editor
        self.log_output = log_output
        self.results_output = results_output
        self.cluster_host = cluster_host
        self.cluster_user = cluster_user
        self.cluster_port = cluster_port
        self.access_mode = access_mode
        self.normalize_remote_path = normalize_remote_path
        self.connector_fetch_archive = connector_fetch_archive
        self.should_use_connector = should_use_connector
        self.connector_ssh = connector_ssh
        self.ssh_run = ssh_run
        self.cluster_name = cluster_name

        # ---- per-user Workspace isolation -------------------------------
        # The run history is confined to <workspace-root>/users/<safe-id>/...
        # for exactly one authenticated CryoStack user. All discovery and all
        # per-run operations stay inside this subtree; a run id owned by
        # another user is simply absent from self._runs and every method
        # short-circuits.
        self.owner: WorkspaceUser = (
            owner
            if owner is not None
            else resolve_workspace_user(require_authenticated=require_authenticated)
        )
        if workspace_root is not None:
            root = Path(workspace_root).resolve()
        else:
            env_root = (os.environ.get(WORKSPACE_ROOT_ENV) or "").strip()
            root = Path(env_root).resolve() if env_root else Path.cwd().resolve()
        self._workspace_root = root
        self._owner_root = (root / "users" / self.owner.safe_id).resolve()
        self.manifest_root = (self._owner_root / ".cryostack" / "runs").resolve()
        #: derived, rebuildable working copies of examples staged for a run
        self._working_root = (self._owner_root / ".cryostack" / "working").resolve()
        #: user-owned example checkouts:  <owner>/examples/<model>/<name>
        self._examples_root = (self._owner_root / "examples").resolve()
        #: user-owned reusable datasets:  <owner>/datasets/...
        self._datasets_root = (self._owner_root / "datasets").resolve()
        if not self.manifest_root.is_relative_to(self._owner_root):
            raise RuntimeError("Workspace namespace escaped its user root.")

        self._runs: dict[str, RunInfo] = {}
        self._selected_run_id: str | None = None
        self._tail_handler = None
        self._status_resolver = None
        #: per-run ResultPackage cache -- run_id -> (signature, package). This
        #: manager instance belongs to exactly one authenticated user, so the
        #: cache is inherently user-isolated. Keyed by the resolved outputs
        #: path + its metadata.json mtime so a re-fetched run is re-read.
        self._result_pkg_cache: dict[str, tuple] = {}
        #: run keys with an in-flight results transfer -- prevents duplicate
        #: concurrent rsync / connector pulls for the same run.
        self._fetch_in_flight: set[str] = set()

    def _owns(self, path: Path | None) -> bool:
        """True when ``path`` resolves inside this user's managed run root."""
        if path is None:
            return False
        try:
            return path.resolve().is_relative_to(self.manifest_root)
        except (OSError, ValueError):
            return False

    def set_tail_handler(self, handler) -> None:
        self._tail_handler = handler

    def set_status_resolver(self, resolver) -> None:
        self._status_resolver = resolver

    def reconcile_run(self, run_id: str) -> RunInfo | None:
        run = self._runs.get(run_id)
        if not run or not run.jobid or self._status_resolver is None:
            return run
        if run.status in {"completed", "failed", "cancelled"}:
            return run
        try:
            state = self._status_resolver(run)
        except Exception:
            return run
        return self.update_run_status(run_id, state)

    def update_run_status(self, run_id: str, state: str | None) -> RunInfo | None:
        run = self._runs.get(run_id)
        normalized = str(state or "").strip().lower()
        if not run or normalized not in {"submitted", "queued", "running", "completed", "failed", "cancelled"}:
            return run
        if run.status != normalized:
            run.status = normalized
            run.finished = datetime.now() if normalized in {"completed", "failed", "cancelled"} else None
            if run.workspace_directory:
                write_manifest(run, run.workspace_directory)
        return run

    def update_run_status_by_job(self, job_id: str, state: str | None) -> RunInfo | None:
        run = next((item for item in self._runs.values() if str(item.jobid) == str(job_id)), None)
        return self.update_run_status(run.id, state) if run else None

    def merge_run_metadata_by_job(self, job_id: str, patch: dict) -> RunInfo | None:
        """Shallow-merge ``patch`` into a run's ``metadata`` and persist the
        manifest. One level deep: a dict value is itself merged (used for the
        incrementally-grown ``aws_resources`` snapshot), a scalar replaces.
        Never touches run status. The caller is responsible for ``patch``
        carrying only non-secret data."""
        run = next((r for r in self._runs.values() if str(r.jobid) == str(job_id)), None)
        if not run or not isinstance(patch, dict) or not patch:
            return run
        changed = False
        md = dict(run.metadata or {})
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(md.get(key), dict):
                merged = {**md[key], **value}
                if merged != md[key]:
                    md[key] = merged
                    changed = True
            elif md.get(key) != value:
                md[key] = value
                changed = True
        if changed:
            run.metadata = md
            if run.workspace_directory:
                write_manifest(run, run.workspace_directory)
            self.invalidate_result_package_cache(run.id)
        return run

    def tail(self, run_id: str):
        run = self.select_run(run_id)
        if not run:
            return None
        if self._tail_handler is None:
            raise RuntimeError("Workspace log routing is not configured.")
        return self._tail_handler()

    def list_editable_files(self, example_path: str) -> list[tuple[str, str]]:
        return list_editable_files(example_path)

    # ------------------------------------------------------------------
    # Generic, model-neutral file operations (containment enforced here)
    # ------------------------------------------------------------------
    _SAFE_SEGMENT = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z")

    def _safe_segment(self, name: str) -> str:
        name = (name or "").strip()
        if name in {".", ".."} or "/" in name or "\\" in name \
                or not self._SAFE_SEGMENT.match(name):
            raise ValueError(f"Unsafe name: {name!r}")
        return name

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        try:
            return path.resolve().is_relative_to(root.resolve())
        except (OSError, ValueError, RuntimeError):
            return False

    def is_user_owned(self, path: str | Path | None) -> bool:
        """True when ``path`` resolves inside this authenticated user's workspace."""
        return self._is_user_owned_path(Path(path)) if path not in (None, "") else False

    def resolve_user_file(self, path: str | Path, *, must_exist: bool = False) -> Path:
        """Resolve ``path`` and require it to sit inside this user's workspace."""
        try:
            rp = Path(path).expanduser().resolve()
        except (OSError, RuntimeError):
            raise WorkspacePermissionError(f"Cannot resolve path: {path!r}")
        if not rp.is_relative_to(self._owner_root):
            raise WorkspacePermissionError(
                "This file is outside your workspace and cannot be modified. "
                "Clone the example to your workspace first."
            )
        if must_exist and not rp.is_file():
            raise FileNotFoundError(f"No such file: {rp}")
        return rp

    #: files larger than this are not loaded into the editor buffer
    MAX_EDITABLE_BYTES = 2 * 1024 * 1024

    def read_text_file(self, path: str | Path) -> str:
        """Read a text file the user is allowed to view: their own workspace, or
        the selected example tree -- but never another user's namespace."""
        p = Path(path).expanduser().resolve()
        if not p.is_relative_to(self._owner_root):
            example = self.example_root()
            if example is None or not self._within(p, example.resolve()):
                raise WorkspacePermissionError(
                    "File is outside the current workspace/example."
                )
            users_root = (self._workspace_root / "users").resolve()
            if self._within(p, users_root):
                raise WorkspacePermissionError(
                    "File belongs to another user's workspace."
                )
        if not p.is_file():
            raise FileNotFoundError(str(p))
        if p.stat().st_size > self.MAX_EDITABLE_BYTES:
            raise WorkspacePermissionError(
                f"File is too large to edit here ({p.stat().st_size // 1024} KB)."
            )
        return p.read_text(encoding="utf-8")

    def save_text_file(self, path: str | Path, text: str) -> Path:
        rp = self.resolve_user_file(path)
        if rp.exists() and not rp.is_file():
            raise WorkspacePermissionError("Target is not a regular file.")
        if not rp.parent.is_dir():
            raise FileNotFoundError(f"Directory does not exist: {rp.parent}")
        rp.write_text(text, encoding="utf-8")
        return rp

    def create_text_file(self, directory: str | Path, name: str, text: str = "") -> Path:
        d = self.resolve_user_file(directory)
        if not d.is_dir():
            raise FileNotFoundError(f"Directory does not exist: {d}")
        target = self.resolve_user_file(d / self._safe_segment(name))
        if target.exists():
            raise FileExistsError(f"Already exists: {target.name}")
        target.write_text(text, encoding="utf-8")
        return target

    def delete_user_file(self, path: str | Path) -> Path:
        rp = self.resolve_user_file(path, must_exist=True)
        if not rp.is_file():
            raise WorkspacePermissionError("Only regular files can be deleted here.")
        rp.unlink()
        return rp

    def user_examples_root(self, model: str | None = None) -> Path:
        root = self._examples_root
        if model:
            root = (root / self._safe_segment(str(model).strip().lower())).resolve()
        return root

    # ── one generic copy-into-workspace primitive ─────────────────────────
    def _copy_example_tree(self, src: Path, dest: Path, *, overwrite: bool) -> None:
        """Copy an example directory to ``dest`` inside this user's workspace."""
        dest = dest.resolve()
        if not dest.is_relative_to(self._owner_root):
            raise WorkspacePermissionError("Destination escaped the workspace.")
        if dest.exists():
            if not overwrite:
                raise FileExistsError(f"Already exists: {dest.name}")
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)

    def _example_provenance(self, path: Path) -> dict:
        prov = path / ".cryostack-example.json"
        if prov.is_file():
            try:
                return json.loads(prov.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
        return {}

    def _write_example_provenance(self, path: Path, data: dict) -> None:
        (path / ".cryostack-example.json").write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )

    # ── user example lifecycle ───────────────────────────────────────────
    def clone_example_to_workspace(
        self, *, source: str | Path, model: str | None, name: str | None = None
    ) -> Path:
        """Copy an example into this user's workspace as an editable copy.

        Result: ``<owner>/examples/<model>/<name>``. The source is never modified.
        """
        try:
            src = Path(source).expanduser().resolve()
        except (OSError, RuntimeError):
            raise ValueError(f"Cannot resolve example path: {source!r}")
        if not src.is_dir():
            raise ValueError(f"Not an example directory: {src}")

        dest = (self.user_examples_root(model)
                / self._safe_example_name(name or src.name)).resolve()
        self._copy_example_tree(src, dest, overwrite=False)
        self._write_example_provenance(dest, {
            "kind": "cryostack-user-example",
            "model": (str(model).strip().lower() or None) if model else None,
            "name": dest.name,
            "owner": self.owner.safe_id,
            "created": datetime.now().isoformat(timespec="seconds"),
            "source": str(src),
            "source_name": src.name,
            "source_type": "user-clone" if self._is_user_owned_path(src) else "canonical-clone",
            "datasets": [],
        })
        return dest

    def create_user_example(
        self, *, model: str, name: str, template: dict[str, str] | None = None
    ) -> Path:
        """Create a minimal user-owned example directory. ``template`` (if any)
        is supplied by the model adapter -- the generic layer knows no filenames."""
        dest = (self.user_examples_root(model)
                / self._safe_example_name(name)).resolve()
        if not dest.is_relative_to(self._examples_root):
            raise WorkspacePermissionError("Example target escaped the workspace.")
        if dest.exists():
            raise FileExistsError(f"A workspace example named {dest.name!r} already exists.")
        dest.mkdir(parents=True)
        for fname, body in (template or {}).items():
            (dest / self._safe_segment(fname)).write_text(str(body), encoding="utf-8")
        self._write_example_provenance(dest, {
            "kind": "cryostack-user-example",
            "model": (model or "").strip().lower() or None,
            "name": dest.name,
            "owner": self.owner.safe_id,
            "created": datetime.now().isoformat(timespec="seconds"),
            "source": None,
            "source_name": None,
            "source_type": "new-template" if template else "new-empty",
            "datasets": [],
        })
        return dest

    def _user_example_dir(self, model: str, name: str) -> Path:
        d = (self.user_examples_root(model) / self._safe_example_name(name)).resolve()
        if not d.is_relative_to(self._examples_root):
            raise WorkspacePermissionError("Example escaped the workspace.")
        if not (d.is_dir() and (d / ".cryostack-example.json").is_file()):
            raise FileNotFoundError(f"No such workspace example: {name}")
        return d

    def rename_user_example(self, *, model: str, old: str, new: str) -> Path:
        src = self._user_example_dir(model, old)
        dest = (self.user_examples_root(model) / self._safe_example_name(new)).resolve()
        if not dest.is_relative_to(self._examples_root):
            raise WorkspacePermissionError("Rename target escaped the workspace.")
        if dest.exists():
            raise FileExistsError(f"A workspace example named {dest.name!r} already exists.")
        src.rename(dest)
        prov = self._example_provenance(dest)
        prov["name"] = dest.name
        self._write_example_provenance(dest, prov)
        return dest

    def delete_user_example(self, *, model: str, name: str) -> Path:
        d = self._user_example_dir(model, name)
        shutil.rmtree(d)              # datasets live in <owner>/datasets/, never here
        return d

    def list_user_examples(self, model: str | None = None) -> list[dict]:
        root = self.user_examples_root(model) if model else self._examples_root
        out: list[dict] = []
        if not root.is_dir():
            return out
        candidates = (
            sorted(root.iterdir()) if model
            else [p for m in sorted(root.iterdir()) if m.is_dir()
                  for p in sorted(m.iterdir())]
        )
        for d in candidates:
            if not d.is_dir() or not (d / ".cryostack-example.json").is_file():
                continue
            prov = self._example_provenance(d)
            out.append({
                "name": d.name, "path": str(d),
                "model": prov.get("model"),
                "source_type": prov.get("source_type"),
                "source_name": prov.get("source_name"),
                "datasets": prov.get("datasets", []),
            })
        return out

    # ── dataset references (metadata only -- no copy until run staging) ───
    def example_dataset_references(self, example_path: str | Path) -> list[dict]:
        p = Path(example_path).expanduser().resolve()
        return list(self._example_provenance(p).get("datasets", []))

    def reference_dataset(
        self, *, example_path: str | Path, dataset_name: str, as_path: str | None = None
    ) -> list[dict]:
        d = self.resolve_user_file(example_path).parent \
            if Path(example_path).is_file() else self.resolve_user_file(example_path)
        if not d.is_dir():
            raise FileNotFoundError(f"Not a workspace example: {d}")
        ds = self._resolve_dataset(dataset_name)             # ownership + existence
        rel = self._safe_relpath(as_path or ds.name)
        prov = self._example_provenance(d)
        refs = [r for r in prov.get("datasets", []) if r.get("name") != ds.name]
        refs.append({"name": ds.name, "as": rel})
        prov["datasets"] = refs
        self._write_example_provenance(d, prov)
        return refs

    def unreference_dataset(self, *, example_path: str | Path, dataset_name: str) -> list[dict]:
        d = self.resolve_user_file(example_path)
        prov = self._example_provenance(d)
        prov["datasets"] = [r for r in prov.get("datasets", []) if r.get("name") != dataset_name]
        self._write_example_provenance(d, prov)
        return prov["datasets"]

    def examples_referencing_dataset(self, dataset_name: str) -> list[str]:
        hits: list[str] = []
        if not self._examples_root.is_dir():
            return hits
        for prov_file in self._examples_root.glob("*/*/.cryostack-example.json"):
            try:
                data = json.loads(prov_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if any(r.get("name") == dataset_name for r in data.get("datasets", [])):
                hits.append(prov_file.parent.name)
        return hits

    def example_root(self) -> Path | None:
        path = Path(self.example_dir.value).expanduser()
        if path.exists():
            return path if path.is_dir() else path.parent
        return None

    # ------------------------------------------------------------------
    # Per-user example staging (canonical examples are read-only)
    # ------------------------------------------------------------------
    def _is_user_owned_path(self, path: Path | None) -> bool:
        """True when ``path`` resolves inside this authenticated user's workspace."""
        if path is None:
            return False
        try:
            return path.resolve().is_relative_to(self._owner_root)
        except (OSError, ValueError):
            return False

    @staticmethod
    def _safe_example_name(name: str) -> str:
        name = (name or "").strip()
        if name in {".", ".."} or not _SAFE_EXAMPLE_NAME.match(name):
            raise ValueError(f"Unsafe example name: {name!r}")
        return name

    def stage_example_for_run(
        self,
        *,
        source_example: str | Path,
        extra_files: dict[str, str] | None = None,
        entrypoint: str = "runme.m",
        entrypoint_transform=None,
        overrides: dict | None = None,
    ) -> StagedExample:
        """Materialise a user-owned working copy of ``source_example`` for a run.

        Generic, model-neutral filesystem staging. ``source_example`` is
        either:

        * a **directory** (every model's usual shape) --
          canonical example  -> a fresh copy under
          ``<owner_root>/.cryostack/working/<name>`` (rebuilt each run);
          user-owned example -> operated on in place; or
        * a **single file** whose type has a registered materializer (today:
          ``.ipynb`` -- an Icepack canonical notebook, which ships as one
          loose file rather than a directory). The materializer builds a
          fresh directory-shaped working copy under
          ``<owner_root>/.cryostack/working/<stem>`` and returns the
          entrypoint filename it produced (e.g. ``run.py``), which OVERRIDES
          the caller's ``entrypoint`` argument -- there is no generic
          default entrypoint for a bare single-file source. An unsupported
          file type raises the same "Example directory not found" a caller
          already gets for a bad path -- this is a file-TYPE dispatch, never
          a per-filename special case.

        ``extra_files`` are written into the copy and any datasets the example
        references are copied into ``data/<as>``. ``entrypoint_transform`` (an
        opaque callable -- the ISSM md-override injector, for instance) may
        rewrite the entrypoint. The canonical example is never modified.
        """
        src = Path(source_example).expanduser().resolve()

        if src.is_file():
            materializer = _file_source_materializer(src.suffix)
            if materializer is None:
                raise ValueError(f"Example directory not found: {src}")
            target = (self._working_root / self._safe_example_name(src.stem)).resolve()
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(parents=True, exist_ok=True)
            entrypoint = materializer(src, dest_dir=target)
            from_canonical = True
        elif not src.exists() or not src.is_dir():
            raise ValueError(f"Example directory not found: {src}")
        elif self._is_user_owned_path(src):
            target, from_canonical = src, False
        else:
            target = (self._working_root / self._safe_example_name(src.name)).resolve()
            self._copy_example_tree(src, target, overwrite=True)
            from_canonical = True

        for fname, body in (extra_files or {}).items():
            (target / self._safe_segment(fname)).write_text(str(body), encoding="utf-8")

        entry = target / entrypoint
        if entrypoint_transform is not None and entry.is_file():
            entry.write_text(
                entrypoint_transform(entry.read_text(encoding="utf-8")), encoding="utf-8"
            )

        staged_datasets = self._stage_referenced_datasets(src, target)

        provenance = {
            "kind": "cryostack-working-copy",
            "source": str(src),
            "source_name": src.name,
            "from_canonical": from_canonical,
            "owner": self.owner.safe_id,
            "created": datetime.now().isoformat(timespec="seconds"),
            "entrypoint": entrypoint,
            "md_overrides": dict(overrides or {}),
            "staged_datasets": staged_datasets,
        }
        # A fresh working copy has no user identity of its own -- record the
        # staging provenance. An in-place user example keeps its own
        # .cryostack-example.json (name / source_type / dataset references).
        if from_canonical:
            self._write_example_provenance(target, provenance)
        return StagedExample(
            path=target, source=str(src), from_canonical=from_canonical, provenance=provenance
        )

    def stage_example_for_md_overrides(
        self,
        *,
        source_example: str | Path,
        override_script: str,
        overrides: dict,
        entrypoint: str = "runme.m",
        entrypoint_transform=None,
    ) -> StagedExample:
        """Basic-mode ISSM path: stage a working copy with the override script
        (``cryostack_md_overrides.m``) written and injected before the first
        ``solve(...)``. Thin wrapper over :meth:`stage_example_for_run`."""
        return self.stage_example_for_run(
            source_example=source_example,
            extra_files={"cryostack_md_overrides.m": override_script},
            entrypoint=entrypoint, entrypoint_transform=entrypoint_transform,
            overrides=overrides,
        )

    # ------------------------------------------------------------------
    # Reusable user datasets:  <owner_root>/datasets/
    # ------------------------------------------------------------------
    #: per-file cap for the widget-based uploader (kernel memory + comm limits)
    MAX_DATASET_UPLOAD_BYTES = 50 * 1024 * 1024

    def datasets_root(self) -> Path:
        self._datasets_root.mkdir(parents=True, exist_ok=True)
        return self._datasets_root

    @staticmethod
    def _safe_dataset_name(raw: str) -> str:
        name = str(raw or "").strip()
        if (not name or "\x00" in name or "/" in name or "\\" in name
                or ".." in name or name.startswith(".")
                or Path(name).is_absolute() or len(name) > 200):
            raise ValueError(
                f"Unsafe dataset filename: {raw!r} "
                "(no paths, no '..', no leading dot)"
            )
        return name

    @staticmethod
    def _safe_relpath(raw: str) -> str:
        parts = [p for p in str(raw or "").replace("\\", "/").split("/") if p]
        if not parts:
            raise ValueError("empty reference path")
        for p in parts:
            if p in {".", ".."} or "\x00" in p or len(p) > 128:
                raise ValueError(f"Unsafe reference path segment: {p!r}")
        return "/".join(parts)

    def _resolve_dataset(self, name: str) -> Path:
        p = (self._datasets_root / self._safe_dataset_name(name)).resolve()
        if not p.is_relative_to(self._datasets_root):
            raise WorkspacePermissionError("Dataset escaped the datasets root.")
        if not p.is_file():
            raise FileNotFoundError(f"No such dataset: {name}")
        return p

    def list_datasets(self) -> list[dict]:
        root = self._datasets_root
        if not root.is_dir():
            return []
        out: list[dict] = []
        for p in sorted(root.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue
            out.append({
                "name": p.name,
                "path": str(p),
                "size": p.stat().st_size,
                "suffix": p.suffix.lower(),
                "editable": p.suffix.lower() in EDITABLE_SUFFIXES,
                "referenced_by": self.examples_referencing_dataset(p.name),
            })
        return out

    def save_datasets(self, uploads, *, overwrite: bool = False) -> dict:
        """Persist ``ipywidgets.FileUpload.value`` into ``<owner>/datasets/``.

        Returns ``{"saved": [...], "skipped": [...], "errors": [...]}``. No
        extension restriction (scientific data); traversal-proof; overwrite
        needs ``overwrite=True``; oversized files are rejected with a clear
        message.
        """
        root = self.datasets_root()
        items = uploads.values() if isinstance(uploads, dict) else (uploads or [])
        saved, skipped, errors = [], [], []
        for item in items:
            raw_name = (item.get("name") if isinstance(item, dict)
                        else getattr(item, "name", "upload"))
            try:
                name = self._safe_dataset_name(raw_name)
                content = item["content"] if isinstance(item, dict) else item.content
                content = bytes(content)
            except (KeyError, AttributeError, TypeError, ValueError) as err:
                errors.append(f"{raw_name}: {err}")
                continue
            if len(content) > self.MAX_DATASET_UPLOAD_BYTES:
                errors.append(
                    f"{name}: {len(content) // (1024 * 1024)} MB exceeds the "
                    f"{self.MAX_DATASET_UPLOAD_BYTES // (1024 * 1024)} MB browser "
                    "upload limit -- stage large data on the compute resource instead."
                )
                continue
            target = (root / name).resolve()
            if not target.is_relative_to(self._datasets_root):
                errors.append(f"{name}: rejected")
                continue
            if target.exists() and not overwrite:
                skipped.append(name)
                continue
            target.write_bytes(content)
            saved.append(name)
        return {"saved": saved, "skipped": skipped, "errors": errors}

    def delete_dataset(self, name: str) -> Path:
        p = self._resolve_dataset(name)
        p.unlink()
        return p

    def rename_dataset(self, old: str, new: str) -> Path:
        src = self._resolve_dataset(old)
        dest = (self._datasets_root / self._safe_dataset_name(new)).resolve()
        if not dest.is_relative_to(self._datasets_root):
            raise WorkspacePermissionError("Rename target escaped the datasets root.")
        if dest.exists():
            raise FileExistsError(f"A dataset named {dest.name!r} already exists.")
        src.rename(dest)
        return dest

    def _stage_referenced_datasets(self, source: Path, working_copy: Path) -> list[dict]:
        """Copy the datasets the source example references into ``working_copy/data``."""
        refs = self._example_provenance(source).get("datasets", [])
        staged: list[dict] = []
        for ref in refs:
            try:
                ds = self._resolve_dataset(ref.get("name", ""))
            except (FileNotFoundError, WorkspacePermissionError, ValueError):
                continue
            try:
                rel = self._safe_relpath(ref.get("as") or ds.name)
            except ValueError:
                continue
            dest = (working_copy / "data" / rel).resolve()
            if not dest.is_relative_to(working_copy.resolve()):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ds, dest)
            staged.append({"name": ds.name, "as": f"data/{rel}"})
        return staged

    def delete(self, path: Path) -> None:
        """Delete one explicitly resolved workspace path."""
        path = Path(path)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    def register_run(self, run: RunInfo) -> RunInfo:
        if not _SAFE_RUN_ID.match(run.id or ""):
            raise ValueError(f"Unsafe run id: {run.id!r}")
        workspace = (self.manifest_root / run.id).resolve()
        if not workspace.is_relative_to(self.manifest_root):
            raise ValueError(f"Run id escapes the managed workspace: {run.id!r}")
        run.workspace_directory = workspace
        write_manifest(run, workspace)
        self._runs[run.id] = run
        return run

    def refresh(self) -> list[RunInfo]:
        discovered: dict[str, RunInfo] = {}
        if self.manifest_root.exists():
            for path in sorted(self.manifest_root.glob(f"*/{MANIFEST_NAME}")):
                try:
                    run = read_manifest(path)
                    if run.id not in discovered or run.created > discovered[run.id].created:
                        discovered[run.id] = run
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        self._runs = discovered
        if self._selected_run_id not in discovered:
            self._selected_run_id = None
        for run in tuple(discovered.values()):
            self.reconcile_run(run.id)
        return self.list_runs()

    def list_runs(self) -> list[RunInfo]:
        return sorted(self._runs.values(), key=lambda run: run.created, reverse=True)

    def select_run(self, run_id: str) -> RunInfo | None:
        run = self._runs.get(run_id)
        self._selected_run_id = run.id if run else None
        if run:
            self.status.update(
                jobid=run.jobid,
                remote_dir=str(run.remote_directory) if run.remote_directory else None,
                log_file=str(run.log_file) if run.log_file else None,
                batch_job_id=run.jobid if run.execution_mode == "cloud" else self.status.get("batch_job_id"),
                cloud_run=run.metadata.get("cloud_run"),
            )
            for widget, key in (
                (self.cluster_host, "host"),
                (self.cluster_user, "user"),
                (self.cluster_port, "port"),
                (self.access_mode, "access_mode"),
                (self.cluster_name, "cluster_name"),
            ):
                if run.metadata.get(key) not in (None, ""):
                    widget.value = run.metadata[key]
            model_values = [item[1] if isinstance(item, tuple) else item for item in self.model.options]
            backend_values = [item[1] if isinstance(item, tuple) else item for item in self.backend.options]
            if run.model in model_values:
                self.model.value = run.model
            if run.backend in backend_values:
                self.backend.value = run.backend
        return run

    def selected_run(self) -> RunInfo | None:
        return self._runs.get(self._selected_run_id or "")

    def files(self, run_id: str) -> list[Path]:
        run = self._runs.get(run_id)
        if not run or not self._owns(run.workspace_directory) or not run.workspace_directory.exists():
            return []
        return sorted(path for path in run.workspace_directory.rglob("*") if path.is_file())

    def delete_run(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if not run or not run.workspace_directory:
            return False
        workspace = run.workspace_directory.resolve()
        if not self._owns(workspace):
            return False
        manifest = workspace / MANIFEST_NAME
        try:
            verified = read_manifest(manifest)
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if verified.id != run_id or workspace == self.manifest_root:
            return False
        shutil.rmtree(workspace)
        self._runs.pop(run_id, None)
        self.invalidate_result_package_cache(run_id)
        if self._selected_run_id == run_id:
            self._selected_run_id = None
        return True

    def preview_results_for_run(self, run_id: str) -> None:
        if self.select_run(run_id):
            self.preview_results()

    def download_results_for_run(self, run_id: str) -> None:
        if self.select_run(run_id):
            self.download_results()

    def download_figures_for_run(self, run_id: str) -> None:
        if self.select_run(run_id):
            self.download_figures()

    def result_package_for_run(self, run_id: str):
        """Return a read-only :class:`ResultPackage` for a run's already-fetched
        outputs -- data only, no fetching and no rendering.

        Looks only at what is present locally (a run retrieved from Remote,
        Container or Cloud all land in the same ``outputs/`` shape), so the
        Workspace Results tab can enumerate solutions/fields without MATLAB.
        Legacy runs (only ``md_final.mat`` / figures) come back with
        ``status == "legacy"`` rather than raising.
        """
        run = self._runs.get(run_id)
        discover_results = _result_reader_for(run.model if run else "issm")

        if not run or not self._owns(run.workspace_directory):
            return discover_results(self.manifest_root / (run_id or "_missing"))
        base = run.workspace_directory
        candidates = [
            base / "cache" / "outputs",
            base / "cache" / "cloud_outputs",
            base / "outputs",
            base,
        ]
        chosen = next((c for c in candidates if c.exists()), base)

        # cheap freshness signature: which dir + its metadata.json mtime. A
        # re-fetch rewrites metadata.json, so a stale package is never served.
        meta = chosen / "outputs" / "metadata.json"
        if not meta.is_file():
            meta = chosen / "metadata.json"
        try:
            sig = (str(chosen), meta.stat().st_mtime_ns if meta.is_file() else 0)
        except OSError:
            sig = (str(chosen), -1)

        cached = self._result_pkg_cache.get(run_id)
        if cached is not None and cached[0] == sig:
            return cached[1]

        for candidate in candidates:
            if candidate.exists():
                package = discover_results(candidate)
                if package.outputs is not None:
                    self._result_pkg_cache[run_id] = (sig, package)
                    return package
        package = discover_results(base)
        self._result_pkg_cache[run_id] = (sig, package)
        return package

    def invalidate_result_package_cache(self, run_id: str | None = None) -> None:
        """Drop the cached ResultPackage for one run (or all runs)."""
        if run_id is None:
            self._result_pkg_cache.clear()
        else:
            self._result_pkg_cache.pop(run_id, None)

    def recommended_plots_for_run(self, run_id: str) -> list[dict]:
        """Metadata-driven plot descriptions for a run (renders nothing)."""
        run = self._runs.get(run_id)
        viz = _visualizer_for(run.model if run else "issm")
        if viz is None:
            return []
        return viz.recommended_plots(self.result_package_for_run(run_id))

    def render_run_plot(self, run_id: str, *, solution: str, field: str,
                        timestep=None, kind: str = "map"):
        """Deterministic render of one field / series for a run the caller owns.

        Figures are cached inside that run's owned directory. A user can only
        render from -- and write figures into -- their own runs; this never
        raises into the UI (unsupported selections come back with ``ok=False``).
        """
        run = self._runs.get(run_id)
        _viz = _visualizer_for(run.model if run else "issm")
        if _viz is None:
            from cryostack_src.visualization.issm import RenderResult
            return RenderResult.unsupported(
                solution or "", field or "",
                f"visualization is not available yet for model "
                f"{(run.model if run else '?')!r}", kind=kind)
        if not run or not self._owns(run.workspace_directory):
            return _viz.RenderResult.unsupported(
                solution or "", field or "",
                "run not found in your workspace", kind=kind)
        package = self.result_package_for_run(run_id)
        if kind == "timeseries":
            return _viz.render_timeseries(package, solution, field)
        return _viz.render_field(package, solution, field, timestep=timestep)

    def clone_example(self, new_name: str) -> Path | None:
        self.log_output.clear_output()
        source = Path(self.example_dir.value).expanduser()
        if not source.exists():
            with self.log_output:
                print("[advanced][ERROR] Source example path does not exist.")
            return None
        if not new_name:
            with self.log_output:
                print("[advanced][ERROR] Provide a new example name first.")
            return None
        try:
            if source.is_file():
                destination = source.parent / new_name
                if destination.suffix == "":
                    destination = destination.with_suffix(source.suffix)
                destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                destination = source.parent / new_name
                if destination.exists():
                    with self.log_output:
                        print(f"[advanced][ERROR] Target already exists: {destination}")
                    return None
                shutil.copytree(source, destination)
            with self.log_output:
                print(f"[advanced] New example created: {destination}")
            return destination
        except Exception as error:
            with self.log_output:
                print("[advanced][ERROR]", type(error).__name__, error)
            return None

    def local_run_cache_dir(self) -> Path:
        selected = self.selected_run()
        if selected and selected.workspace_directory:
            cache = selected.workspace_directory / "cache"
            cache.mkdir(parents=True, exist_ok=True)
            return cache
        root = self.example_root()
        return root / "_icesee_remote_runs" / f"{self.model.value}_{self.backend.value}"

    def sync_cloud_results(
        self,
        *,
        s3_uri: str,
        region: str | None = None,
        profile: str | None = None,
        credentials: dict | None = None,
        aws=None,
    ) -> Path:
        """Pull a cloud run's ``outputs/`` into this user's local run cache in
        the same ``outputs/{metadata.json,mesh,fields,model,figures}`` shape the
        Remote path produces, so the Results UI needs no cloud-specific reader.

        ``aws`` is an injectable ``callable(args) -> CompletedProcess`` (tests
        mock the transfer). The write target is per-``WorkspaceManager`` (=per
        authenticated user); a cloud result never lands in another user's cache.
        """
        run_uri = str(s3_uri or "").strip().rstrip("/")
        if not run_uri.lower().startswith("s3://") or "/" not in run_uri[5:]:
            raise RuntimeError(
                f"cloud result location must be a full s3://bucket/... URI, "
                f"got {s3_uri!r}")
        self.invalidate_result_package_cache(self._selected_run_id)
        outputs_dir = self.local_run_cache_dir() / "cloud_outputs"
        if outputs_dir.exists():
            self.delete(outputs_dir)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        args = []
        # assumed-role temporary credentials (BYO-AWS) win over a profile and
        # the ambient environment -- exactly as cloud.drivers.aws.auth.run_aws.
        if profile and not credentials:
            args.extend(["--profile", profile])
        if region:
            args.extend(["--region", region])
        args.extend([
            "s3", "sync",
            f"{run_uri}/outputs/",
            f"{outputs_dir}/",
        ])
        if aws is not None:
            result = aws(args)
            code = result[0] if isinstance(result, tuple) else getattr(result, "returncode", 0)
            err = (result[2] if isinstance(result, tuple) else getattr(result, "stderr", "")) or ""
            out = (result[1] if isinstance(result, tuple) else getattr(result, "stdout", "")) or ""
        else:
            env = None
            if credentials:
                _drop = ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                         "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN")
                env = {k: v for k, v in os.environ.items() if k not in _drop}
                for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
                    if credentials.get(k):
                        env[k] = credentials[k]
            proc = subprocess.run(["aws", *args], capture_output=True, text=True, env=env)
            code, err, out = proc.returncode, proc.stderr, proc.stdout
        if code != 0:
            raise RuntimeError((err or out).strip() or "cloud results sync failed")
        return outputs_dir

    def remote_outputs_dir(self) -> str:
        remote_dir = self.normalize_remote_path(self.status.get("remote_dir") or "")
        return f"{remote_dir}/outputs"

    def refresh_results(self) -> Path | None:
        # One transfer at a time per run: a user clicking Preview / Download
        # repeatedly must not launch several concurrent rsync / connector
        # pulls for the same outputs.
        run_key = self._selected_run_id or "_current"
        if run_key in self._fetch_in_flight:
            with self.results_output:
                print("[results] A fetch for this run is already in progress…")
            return None
        self._fetch_in_flight.add(run_key)
        try:
            return self._refresh_results_locked()
        finally:
            self._fetch_in_flight.discard(run_key)

    def _refresh_results_locked(self) -> Path | None:
        # a fetch is about to overwrite this run's local outputs
        self.invalidate_result_package_cache(self._selected_run_id)
        remote_dir = self.normalize_remote_path(self.status.get("remote_dir") or "")
        if not remote_dir:
            with self.results_output:
                print("[results] No remote run directory found. Submit a job first.")
            return None
        host = self.cluster_host.value.strip()
        user = self.cluster_user.value.strip()
        port = int(self.cluster_port.value)
        outputs_dir = self.local_run_cache_dir() / "outputs"
        if outputs_dir.exists():
            self.delete(outputs_dir)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        remote_outputs = self.remote_outputs_dir()
        if self.access_mode.value == "connector":
            result = self.connector_fetch_archive(
                self.session["id"], host, user, port,
                f"{remote_outputs.rstrip('/')}/", timeout=600,
            )
            if not result.get("ok"):
                with self.results_output:
                    print("[results][ERROR] Could not fetch remote outputs through connector.")
                    print("Remote source:", remote_outputs)
                    print("FULL RESPONSE:")
                    print(result)
                    print("--- stdout ---")
                    print(result.get("stdout", ""))
                    print("--- stderr ---")
                    print(result.get("stderr", ""))
                return None
            try:
                archive_b64 = result.get("archive_b64")
                if not archive_b64:
                    raise RuntimeError("Connector response did not include archive_b64.")
                with tempfile.TemporaryDirectory() as temp_dir:
                    archive_path = Path(temp_dir) / "outputs.tar.gz"
                    archive_path.write_bytes(base64.b64decode(archive_b64))
                    if outputs_dir.exists():
                        self.delete(outputs_dir)
                    outputs_dir.mkdir(parents=True, exist_ok=True)
                    with tarfile.open(archive_path, "r:gz") as archive:
                        archive.extractall(outputs_dir)
                return outputs_dir
            except Exception as error:
                with self.results_output:
                    print("[results][ERROR] Could not unpack connector archive.")
                    print(type(error).__name__, error)
                return None
        command = [
            "rsync", "-az", "-e", f"ssh -p {port}",
            f"{user}@{host}:{remote_outputs.rstrip('/')}/", f"{outputs_dir}/",
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            with self.results_output:
                print("[results][ERROR] Could not fetch remote outputs.")
                print("Remote source:", remote_outputs)
                print("--- stdout ---")
                print(result.stdout)
                print("--- stderr ---")
                print(result.stderr)
            return None
        return outputs_dir

    @staticmethod
    def _make_zip(source: Path, destination: Path) -> None:
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=path.relative_to(source))

    @staticmethod
    def _auto_download(path: Path, filename: str | None = None) -> None:
        path = Path(path).resolve()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        filename = filename or path.name
        stem = Path(filename).stem
        suffix = Path(filename).suffix or ".zip"
        download_name = f"{stem}_{stamp}{suffix}"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        element_id = f"icesee_download_{uuid.uuid4().hex}"
        display(HTML(f'''<div id="{element_id}"></div><script>
        (function() {{ const a = document.createElement("a");
        a.href = "data:application/zip;base64,{data}";
        a.download = "{html.escape(download_name)}"; a.style.display = "none";
        document.body.appendChild(a); setTimeout(() => {{ a.click();
        document.body.removeChild(a); }}, 100); }})();</script>'''))

    def download_results(self, _=None) -> None:
        if isinstance(_, str) and not self.select_run(_):
            return
        self.results_output.clear_output()
        with self.results_output:
            print("Fetching results…")
        outputs_dir = self.refresh_results()
        if outputs_dir is None:
            return
        zip_path = self.local_run_cache_dir() / "results_bundle.zip"
        try:
            if zip_path.exists():
                self.delete(zip_path)
            self._make_zip(outputs_dir, zip_path)
            if not zipfile.is_zipfile(zip_path):
                raise RuntimeError(f"Created file is not a valid zip: {zip_path}")
            with self.results_output:
                print(f"Preparing download: {zip_path.name}")
                print("If the browser blocks repeated downloads, allow multiple downloads for this page.")
                self._auto_download(zip_path, "results_bundle.zip")
        except Exception as error:
            with self.results_output:
                print("[download][ERROR]", type(error).__name__, error)

    def download_figures(self, _=None) -> None:
        if isinstance(_, str) and not self.select_run(_):
            return
        self.results_output.clear_output()
        with self.results_output:
            print("Fetching figures…")
        outputs_dir = self.refresh_results()
        if outputs_dir is None:
            return
        pngs = sorted(outputs_dir.rglob("*.png"))
        if not pngs:
            with self.results_output:
                print("[download] No PNG figures found.")
                print("Checked recursively under:", outputs_dir)
            return
        figures_dir = self.local_run_cache_dir() / "_figures_only"
        if figures_dir.exists():
            self.delete(figures_dir)
        figures_dir.mkdir(parents=True, exist_ok=True)
        for path in pngs:
            shutil.copy2(path, figures_dir / path.name)
        zip_path = self.local_run_cache_dir() / "figures_bundle.zip"
        try:
            if zip_path.exists():
                self.delete(zip_path)
            self._make_zip(figures_dir, zip_path)
            if not zipfile.is_zipfile(zip_path):
                raise RuntimeError(f"Created file is not a valid zip: {zip_path}")
            with self.results_output:
                print(f"Preparing download: {zip_path.name}")
                print("If the browser blocks repeated downloads, allow multiple downloads for this page.")
                self._auto_download(zip_path, "figures_bundle.zip")
        except Exception as error:
            with self.results_output:
                print("[download][ERROR]", type(error).__name__, error)

    def preview_results(self, _=None) -> None:
        if isinstance(_, str) and not self.select_run(_):
            return
        self.results_output.clear_output()
        remote_check = self.inspect_remote_results()
        outputs_dir = self.refresh_results()
        if outputs_dir is None:
            return
        pngs = sorted(outputs_dir.rglob("*.png"))
        mats = sorted(outputs_dir.rglob("*.mat"))
        h5s = sorted(outputs_dir.rglob("*.h5"))
        all_files = sorted(path for path in outputs_dir.rglob("*") if path.is_file())
        structured = (outputs_dir / "metadata.json").is_file()
        with self.results_output:
            print("Fetched outputs:", outputs_dir)
            print(f"Figures: {len(pngs)}")
            print(f"Model files: {len(mats)}")
            print(f"H5 files: {len(h5s)}\n")
            if all_files:
                print("Output tree:")
                for path in all_files[:40]:
                    print(" -", path.relative_to(outputs_dir))
                print()
            if pngs:
                print("Preview figures:")
                for path in pngs:
                    print("\n", path.name)
                    display(Image(filename=str(path)))
            elif structured:
                # Commit 4 makes figures/ initially empty on purpose -- an "ok"
                # structured package is available, not "nothing to preview".
                print("Structured results are available "
                      "(no pre-rendered PNGs -- figures/ is written on demand).")
                print("The Field visualization panel below has been populated; "
                      "an initial recommended plot is rendered there.")
                print("Use it to render any Solution / Field / Timestep.")
            else:
                print("No structured results and no PNG figures after fetch.\n")
                print("--- Remote inspection ---")
                print((remote_check.stdout or "").strip())
                if (remote_check.stderr or "").strip():
                    print("--- stderr ---")
                    print(remote_check.stderr.strip())

    def inspect_remote_results(self):
        remote_dir = self.normalize_remote_path(self.status.get("remote_dir") or "")
        outputs = f"{remote_dir}/outputs"
        host = self.cluster_host.value.strip()
        user = self.cluster_user.value.strip()
        port = int(self.cluster_port.value)
        command = f'''
        set -e
        echo "[remote] run dir : {remote_dir}"
        echo "[remote] outputs : {outputs}"
        echo

        echo "[remote] output tree:"
        find "{outputs}" -maxdepth 5 -print || true

        echo
        echo "[remote] png/mat/h5 files:"
        find "{outputs}" -maxdepth 6 -type f \\( -name "*.png" -o -name "*.mat" -o -name "*.h5" \\) -print || true
        '''
        if self.should_use_connector():
            payload = self.connector_ssh(
                self.session["id"], host, user, port, command,
                timeout=300,
                cluster_name=self.cluster_name.value or "pace",
            )

            class Result:
                returncode = 0 if payload.get("ok") else 1
                stdout = payload.get("stdout", "")
                stderr = payload.get("stderr", "")

            return Result()
        return self.ssh_run(host, user, port, command, timeout=30)
