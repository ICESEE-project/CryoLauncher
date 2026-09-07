"""Icepack postprocessing: collect a run's outputs into the neutral package shape.

Unlike ISSM (whose MATLAB ``md.results`` struct is serialised field-by-field),
Icepack results are Firedrake ``Function`` objects whose neutral, model-aware
export is not yet defined (a deliberate scientific-decision checkpoint -- see
``overnight/AGENT_TRAIL.md`` §B). Until then this step does the part that carries
no model science: it gathers whatever figures / native output files the example
produced into ``outputs/`` and writes an honest ``metadata.json`` that records
exactly what exists -- never a fabricated field or solution.

Runs as plain ``python`` (stdlib only -- no icepack / firedrake import needed) on
whatever resource executed the run:

    CRYOSTACK_RUN_DIR      the run directory (contains outputs/)         [required]
    CRYOSTACK_EXAMPLE_DIR  where the example executed (artifacts land)   [optional]
    CRYOSTACK_RUN_STARTED  epoch seconds; only files touched at/after    [optional]
                           this time are collected (avoids sweeping in
                           example inputs that predate the run)
"""
from __future__ import annotations

SCHEMA = "cryostack.icepack.results"

_SCRIPT = r'''# CryoStack Icepack neutral output collector (auto-generated -- do not edit)
import json, os, shutil, sys, time
from pathlib import Path

FIGURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".svg", ".pdf", ".gif")
NATIVE_SUFFIXES = (".h5", ".hdf5", ".pvd", ".vtu", ".vtk", ".pvtu", ".xdmf",
                   ".nc", ".npz", ".npy", ".pkl", ".mat", ".msh")

run_dir = Path(os.environ.get("CRYOSTACK_RUN_DIR") or ".").expanduser()
example_dir = os.environ.get("CRYOSTACK_EXAMPLE_DIR") or ""
started = float(os.environ.get("CRYOSTACK_RUN_STARTED") or 0.0)

outputs = run_dir / "outputs"
for sub in ("figures", "model", "fields", "mesh"):
    (outputs / sub).mkdir(parents=True, exist_ok=True)

search_roots = []
for cand in (example_dir, str(run_dir)):
    p = Path(cand).expanduser() if cand else None
    if p and p.is_dir() and p not in search_roots:
        search_roots.append(p)

def _fresh(path):
    if started <= 0:
        return True
    try:
        return path.stat().st_mtime >= started - 1
    except OSError:
        return False

figures, model_files, skipped = [], [], []
for root in search_roots:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if outputs in path.parents:            # already collected
            continue
        suffix = path.suffix.lower()
        if suffix in FIGURE_SUFFIXES:
            dest_dir = outputs / "figures"
        elif suffix in NATIVE_SUFFIXES:
            dest_dir = outputs / "model"
        else:
            continue
        if not _fresh(path):
            skipped.append({"name": path.name, "reason": "predates run start"})
            continue
        dest = dest_dir / path.name
        try:
            shutil.copy2(path, dest)
        except OSError as e:
            skipped.append({"name": path.name, "reason": f"copy failed: {e}"})
            continue
        (figures if suffix in FIGURE_SUFFIXES else model_files).append(dest.name)

# Fold in anything ALREADY sitting in outputs/ -- e.g. figures the run
# captured directly (cryostack_icepack_runner's headless-figure sweep) or a
# structured exporter's own native artifacts -- so the reported status
# reflects everything present, not only what this sweep copied in.
def _listdir_names(sub, suffixes=None):
    d = outputs / sub
    if not d.is_dir():
        return []
    return sorted(
        p.name for p in d.iterdir()
        if p.is_file() and (suffixes is None or p.suffix.lower() in suffixes)
    )

all_figures = sorted(set(figures) | set(_listdir_names("figures", FIGURE_SUFFIXES)))
all_model = sorted(set(model_files) | set(_listdir_names("model")))

# Per-figure metadata captured by cryostack_icepack_runner FROM THE FIGURE
# ITSELF (suptitle / axes titles / axis labels). Never inferred from a
# variable name, figure order, or the tutorial's identity -- a figure the
# script gave no title just has no "title" key here, and the UI falls back
# to a neutral "Figure N". Keyed by filename; only figures with real
# extracted text get an entry.
figures_meta = {}
try:
    _cap = json.loads((outputs / "figures" / "_captured.json").read_text(encoding="utf-8"))
    for _e in (_cap if isinstance(_cap, list) else []):
        _f = _e.get("file")
        if not _f:
            continue
        _rec = {}
        _title = (_e.get("suptitle")
                  or next((t for t in (_e.get("axes_titles") or []) if t), "")).strip()
        if _title:
            _rec["title"] = _title
        if _e.get("axes_titles"):
            _rec["axes_titles"] = [t for t in _e["axes_titles"] if t]
        if _e.get("xlabel"):
            _rec["xlabel"] = _e["xlabel"]
        if _e.get("ylabel"):
            _rec["ylabel"] = _e["ylabel"]
        figures_meta[_f] = _rec
except Exception:
    figures_meta = figures_meta or {}

# A structured export (cryostack_icepack_export) may already have written a
# richer metadata.json (fields / mesh / status "ok"). Never clobber that --
# only fold in the figures / native files.
meta_path = outputs / "metadata.json"
existing = {}
try:
    existing = json.loads(meta_path.read_text(encoding="utf-8"))
except Exception:
    existing = {}

merged_fig_meta = dict(existing.get("figures_meta") or {})
merged_fig_meta.update(figures_meta)

if existing.get("fields") or existing.get("status") == "ok":
    existing["figures"] = sorted(set(existing.get("figures", [])) | set(all_figures))
    existing["model_files"] = sorted(set(existing.get("model_files", [])) | set(all_model))
    existing.setdefault("skipped", []).extend(skipped)
    if merged_fig_meta:
        existing["figures_meta"] = merged_fig_meta
    metadata = existing
else:
    metadata = {
        "schema": "%SCHEMA%",
        "version": existing.get("version", 1),
        "model": "icepack",
        # honest, source-agnostic: ok is decided by the exporter (branch
        # above); here it is artifacts when ANY figure / native file is
        # present, and empty only when truly nothing persistent exists.
        "status": "artifacts" if (all_figures or all_model) else existing.get("status", "empty"),
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "solutions": [],
        "fields": [],
        "figures": all_figures,
        "figures_meta": merged_fig_meta,
        "model_files": all_model,
        "skipped": skipped + list(existing.get("skipped", [])),
        "note": ("Icepack structured field export produced no fields; figures "
                 "and native output files are collected here."),
    }
meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

print("[cryostack] icepack outputs collected:",
      len(metadata["figures"]), "figure(s),", len(metadata["model_files"]),
      "model file(s)")
if skipped:
    print("[cryostack] skipped", len(skipped), "file(s) (see metadata.json)")
'''.replace("%SCHEMA%", SCHEMA)


def build_postprocess() -> str:
    """The stdlib-only Python collector script (see module docstring)."""
    return _SCRIPT


_COLLECTOR_FILENAME = "cryostack_icepack_postprocess.py"


def build_collection_shell_block(*, run_dir: str, example_dir: str) -> str:
    """A shell block appended to an Icepack run's sbatch body: write the stdlib
    collector next to the run and execute it with the compute node's ``python3``
    (stdlib only -- no container / icepack import needed). Non-fatal: a
    collection failure warns but never fails the scientific run, which has
    already completed by this point.

    Expects ``CRYOSTACK_RUN_STARTED`` (epoch seconds) to have been exported
    earlier in the script so pre-existing example inputs are not swept in.
    """
    script_path = f"{run_dir}/{_COLLECTOR_FILENAME}"
    heredoc = f"cat > {script_path!r} <<'CRYOSTACK_ICEPACK_PP_EOF'\n{_SCRIPT}\nCRYOSTACK_ICEPACK_PP_EOF"
    return f'''
# --- CryoStack Icepack output collection (non-fatal) -------------------
{heredoc}
if command -v python3 >/dev/null 2>&1; then
    CRYOSTACK_RUN_DIR={run_dir!r} \\
    CRYOSTACK_EXAMPLE_DIR={example_dir!r} \\
    CRYOSTACK_RUN_STARTED="${{CRYOSTACK_RUN_STARTED:-0}}" \\
    python3 {script_path!r} \\
      || echo "[cryostack][warn] Icepack output collection failed (the run itself completed)"
else
    echo "[cryostack][warn] python3 not on the compute node; skipping Icepack output collection"
fi
'''
