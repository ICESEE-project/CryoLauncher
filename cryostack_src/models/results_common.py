"""Model-neutral primitives for reading a CryoStack result package.

Every model's structured results land in the same on-disk shape regardless of
the execution backend (Remote / Container / Cloud)::

    <run>/outputs/
        metadata.json            # schema + what the run ACTUALLY produced
        figures/*.png            # deterministic or example-produced figures
        model/                   # native model artifacts (md_final.mat, *.h5, *.pvd, ...)
        fields/ mesh/            # structured field data (model-specific readers)

This module only owns the parts that carry no model science: locating the
``outputs/`` directory, reading ``metadata.json`` defensively, and enumerating
the figure / native-artifact files. The field / mesh / solution vocabulary is
model-specific and lives in each model's ``results.py``
(:mod:`cryostack_src.models.issm.results`, :mod:`cryostack_src.models.icepack.results`).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

METADATA_NAME = "metadata.json"

#: files treated as "figures" (shown directly) vs "native model artifacts"
FIGURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".svg", ".pdf", ".gif")
NATIVE_ARTIFACT_SUFFIXES = (
    ".mat", ".h5", ".hdf5", ".pvd", ".vtu", ".vtk", ".pvtu", ".xdmf",
    ".nc", ".npz", ".npy", ".pkl", ".msh", ".exo", ".geo",
)


def find_outputs_dir(root: str | Path) -> Path | None:
    """Return the ``outputs/`` directory for a run, or ``None`` if absent.

    Accepts the run directory, the ``outputs`` directory itself, or a directory
    that already looks like an unpacked package (has ``metadata.json`` or one of
    the standard subdirs).
    """
    root = Path(root).expanduser()
    if not root.is_dir():
        return None
    if root.name == "outputs":
        return root
    if (root / "outputs").is_dir():
        return root / "outputs"
    if any((root / m).exists() for m in
           (METADATA_NAME, "model", "fields", "mesh", "figures")):
        return root
    return None


def read_metadata(outputs: Path | None) -> dict:
    """Read ``outputs/metadata.json`` as a dict. Never raises: a missing or
    malformed file yields ``{}``."""
    if outputs is None:
        return {}
    meta_file = Path(outputs) / METADATA_NAME
    if not meta_file.is_file():
        return {}
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def list_figures(outputs: Path | None) -> list[Path]:
    """Figure files under ``outputs/`` (``figures/`` first, then any elsewhere)."""
    if outputs is None:
        return []
    outputs = Path(outputs)
    figdir = outputs / "figures"
    figs = sorted(p for p in figdir.glob("*") if p.suffix.lower() in FIGURE_SUFFIXES) \
        if figdir.is_dir() else []
    seen = {p.name for p in figs}
    extra = sorted(
        p for p in outputs.rglob("*")
        if p.is_file() and p.suffix.lower() in FIGURE_SUFFIXES and p.name not in seen
        and figdir not in p.parents
    )
    return figs + extra


def legacy_artifacts(outputs: Path | None, *, model_mat_name: str | None = None) -> dict:
    """A model-neutral inventory of a package's raw files, in the shape the
    Results panel's legacy view expects: ``{model_mat, figures, mats, other}``.

    ``model_mat_name`` names the model's "full state" artifact if it has one
    (ISSM: ``md_final.mat``); ``None`` for models that don't.
    """
    if outputs is None:
        return {"model_mat": None, "figures": [], "mats": [], "other": []}
    outputs = Path(outputs)
    model_mat = None
    if model_mat_name:
        cand = outputs / "model" / model_mat_name
        model_mat = str(cand) if cand.is_file() else None

    figures = [str(p) for p in list_figures(outputs)]
    mats = sorted(str(p) for p in outputs.rglob("*.mat"))
    native = sorted(
        str(p) for p in outputs.rglob("*")
        if p.is_file() and p.suffix.lower() in NATIVE_ARTIFACT_SUFFIXES
        and p.suffix.lower() != ".mat"
    )
    other = sorted(
        str(p) for p in outputs.rglob("*")
        if p.is_file() and p.suffix.lower() not in
        (*FIGURE_SUFFIXES, *NATIVE_ARTIFACT_SUFFIXES, ".json")
    )
    return {"model_mat": model_mat, "figures": figures, "mats": mats,
            "native": native, "other": other}


# ── the shared result contract (P2) ──────────────────────────────────
@runtime_checkable
class ResultPackageProtocol(Protocol):
    """The model-neutral surface every model's result package implements.

    ISSM (:class:`cryostack_src.models.issm.results.ResultPackage`) and Icepack
    (:class:`cryostack_src.models.icepack.results.IcepackResultPackage`) both
    satisfy this. The workspace layer and the agent tools depend on *this*, not
    on a concrete class."""

    @property
    def status(self) -> str: ...
    def is_readable(self) -> bool: ...
    def available_solutions(self) -> list[str]: ...
    def available_fields(self, solution: str, *, preferred: bool = True) -> list[str]: ...
    def field_metadata(self, solution: str, field: str) -> Any: ...
    def recommended_plots(self, solution: str | None = None) -> list[dict]: ...
    def figures(self) -> list[Path]: ...
    def figure_captions(self) -> dict: ...
    def legacy_artifacts(self) -> dict: ...


@runtime_checkable
class VisualizerProtocol(Protocol):
    """The deterministic-plotting surface. ``cryostack_src.visualization.issm``
    and ``.icepack`` both satisfy it."""

    def recommended_plots(self, pkg: Any, solution: str | None = None) -> list[dict]: ...
    def render_field(self, pkg: Any, solution: str, field: str,
                     timestep: int | None = None, *, outdir: Any = None) -> Any: ...
    def render_timeseries(self, pkg: Any, solution: str, field: str, *,
                          outdir: Any = None) -> Any: ...


#: callables a package must expose to be contract-conformant (checked by tests).
#: ``status`` is a property, checked separately.
RESULT_CONTRACT_METHODS = (
    "is_readable", "available_solutions", "available_fields",
    "field_metadata", "recommended_plots", "figures", "legacy_artifacts",
)


def describe_package(pkg: ResultPackageProtocol) -> dict:
    """A model-neutral summary of any conformant result package."""
    readable = bool(getattr(pkg, "is_readable", lambda: False)())
    out: dict[str, Any] = {
        "status": getattr(pkg, "status", "unknown"),
        "readable": readable,
        "schema": getattr(pkg, "schema", None),
        "model": getattr(pkg, "model", None),
        "figure_count": len(_call(pkg, "figures") or []),
        "solutions": [],
    }
    if readable:
        for sol in _call(pkg, "available_solutions") or []:
            try:
                fields = pkg.available_fields(sol)
            except Exception:
                fields = []
            out["solutions"].append({"name": sol, "fields": list(fields)})
    return out


def _call(obj: Any, name: str):
    fn = getattr(obj, name, None)
    if not callable(fn):
        return None
    try:
        return fn()
    except Exception:
        return None


def resolve_result_reader(model: str):
    """Return the ``discover_results`` callable for ``model``. Falls back to the
    ISSM reader, which reports *legacy / missing* rather than crashing on an
    unknown layout."""
    from cryostack_src.models import get_model_adapter

    try:
        adapter = get_model_adapter(model or "issm")
    except ValueError:
        adapter = get_model_adapter("issm")
    reader = getattr(adapter, "discover_results", None)
    if reader is not None:
        return reader
    from cryostack_src.models.issm.results import discover_results
    return discover_results


def resolve_visualizer(model: str):
    """Return the visualization module for ``model`` if the capabilities
    registry says it has a deterministic visualizer, else ``None``."""
    from cryostack_src.models.capabilities import MODEL_CAPABILITIES

    name = (model or "").strip().lower()
    cap = MODEL_CAPABILITIES.get(name)
    if cap is None or not cap.visualization:
        return None
    from importlib import import_module

    try:
        return import_module(f"cryostack_src.visualization.{name}")
    except ImportError:
        return None
