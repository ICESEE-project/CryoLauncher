"""Icepack structured export -- shell wiring around :mod:`_export_core`.

The container-side logic lives in ``_export_core.py`` (written verbatim to the
run directory as ``cryostack_icepack_export.py``). Keeping the wiring separate
means the written module never contains this file's heredoc delimiters.
"""
from __future__ import annotations

from pathlib import Path

from cryostack_src.models.icepack._export_core import (  # noqa: F401
    EXPORT_VERSION, SCHEMA, export,
)


# ---------------------------------------------------------------------------
# shell wiring (used by submission.py)
# ---------------------------------------------------------------------------
EXPORT_MODULE_NAME = "cryostack_icepack_export.py"
RUNNER_MODULE_NAME = "cryostack_icepack_runner.py"

#: the tiny runner written next to the export module. It:
#:  1. forces a headless Matplotlib backend (Agg) BEFORE the script imports
#:     matplotlib -- the tutorials call plt.subplots()/tricontourf() and rely
#:     on Jupyter's inline display, which does nothing in a plain script;
#:  2. runs the example script ONCE as ``__main__`` (exceptions propagate ->
#:     the job fails, as it must);
#:  3. persists every still-open Matplotlib figure the script produced but
#:     never saved, to ``outputs/figures/figure-NN.png`` -- deterministic,
#:     de-duplicated against figures the script saved itself, and NEVER by
#:     injecting savefig() into the science script. For each captured figure
#:     it records what the figure ITSELF carries (suptitle, axes titles, x/y
#:     labels) into ``outputs/figures/_captured.json`` -- never inferred from
#:     a variable name, figure order, or the tutorial's identity;
#:  4. runs :func:`export` on the resulting namespace (allow-list only,
#:     never guesses a field).
#: Steps 1, 3 and 4 are all non-fatal: a good science run is never turned
#: into a failed one by figure capture or export.
_RUNNER_SOURCE = '''# cryostack-icepack-runner (auto-generated -- do not edit)
import json
import os
import runpy
import sys

os.environ.setdefault("MPLBACKEND", "Agg")
try:
    import matplotlib
    matplotlib.use("Agg", force=True)
except Exception:
    pass

script, run_dir = sys.argv[1], sys.argv[2]
figures_dir = os.path.join(run_dir, "outputs", "figures")
os.makedirs(figures_dir, exist_ok=True)

# Note which figures the script saves itself, so the post-run sweep does not
# emit a duplicate copy of the same figure under a generic name.
_saved_fignums = set()
_plt = None
try:
    import matplotlib.pyplot as _plt
    _orig_savefig = _plt.Figure.savefig

    def _tracking_savefig(self, *a, **k):
        try:
            _saved_fignums.add(self.number)
        except Exception:
            pass
        return _orig_savefig(self, *a, **k)

    _plt.Figure.savefig = _tracking_savefig
except Exception:
    _plt = None

sys.path.insert(0, run_dir)
_ns = runpy.run_path(script, run_name="__main__")   # science: errors propagate

# Persist any still-open figures the script drew but never saved, and record
# each figure's OWN metadata (title / labels) -- never inferred.
def _text(obj):
    try:
        t = obj.get_text() if obj is not None else ""
        return t.strip() if isinstance(t, str) else ""
    except Exception:
        return ""

_captured = []
try:
    if _plt is not None:
        _plt.Figure.savefig = _orig_savefig            # restore
        _idx = 0
        for _num in _plt.get_fignums():
            if _num in _saved_fignums:
                continue
            _idx += 1
            _fig = _plt.figure(_num)
            _name = "figure-%02d.png" % _idx
            try:
                _fig.savefig(os.path.join(figures_dir, _name),
                             dpi=120, bbox_inches="tight")
            except Exception as _fe:
                print("[cryostack][warn] figure capture failed:",
                      type(_fe).__name__, _fe)
                continue
            _entry = {"file": _name}
            try:
                _st = _text(getattr(_fig, "_suptitle", None))
                if _st:
                    _entry["suptitle"] = _st
                _axt, _xl, _yl = [], "", ""
                for _ax in _fig.get_axes():
                    _t = _text(getattr(_ax, "title", None)) or (
                        _ax.get_title().strip() if hasattr(_ax, "get_title") else "")
                    if _t:
                        _axt.append(_t)
                    if not _xl and hasattr(_ax, "get_xlabel"):
                        _xl = (_ax.get_xlabel() or "").strip()
                    if not _yl and hasattr(_ax, "get_ylabel"):
                        _yl = (_ax.get_ylabel() or "").strip()
                if _axt:
                    _entry["axes_titles"] = _axt
                if _xl:
                    _entry["xlabel"] = _xl
                if _yl:
                    _entry["ylabel"] = _yl
            except Exception:
                pass
            _captured.append(_entry)
        if _idx:
            print("[cryostack] captured %d live matplotlib figure(s)" % _idx)
        if _captured:
            with open(os.path.join(figures_dir, "_captured.json"),
                      "w", encoding="utf-8") as _fh:
                json.dump(_captured, _fh)
except Exception as _err:
    print("[cryostack][warn] matplotlib figure capture failed:",
          type(_err).__name__, _err)

try:
    import cryostack_icepack_export as _e
    _e.export(_ns, run_dir)
except Exception as _err:  # export is best-effort only
    print("[cryostack][warn] icepack structured export failed:",
          type(_err).__name__, _err)
'''


def export_module_source() -> str:
    """Text for ``<run_dir>/cryostack_icepack_export.py`` -- the container-side
    core, which must not contain this file's heredoc delimiters."""
    return (Path(__file__).with_name("_export_core.py")).read_text(encoding="utf-8")


def runner_module_source() -> str:
    """Text for ``<run_dir>/cryostack_icepack_runner.py``."""
    return _RUNNER_SOURCE


def run_command(*, script: str, run_dir: str) -> str:
    """The command that replaces a bare ``python <script>`` for an Icepack run:
    run the script once, then structured-export its namespace."""
    return f'python {run_dir}/{RUNNER_MODULE_NAME} "{script}" "{run_dir}"'


def _heredoc(path: str, text: str, tag: str) -> str:
    return f"cat > {path!r} <<'{tag}'\n{text}\n{tag}"


def build_export_shell_block(
    *,
    run_dir: str,
    example_dir: str,
    backend: str,
    sif_path: str = "",
    spack_path: str = "",
    stack_binds: str = "",
    run_file_name: str,
    run_file_py: str = "",
) -> str:
    """A **non-fatal** sbatch block, appended after the Icepack run, that runs
    the structured exporter in the ``with-icepack`` Firedrake environment.

    v1 re-runs the example script once inside the runner to capture its final
    ``Function`` namespace (deterministic; the tutorial spin-ups are
    idempotent). Folding this into the run block itself to avoid the second run
    is a tracked optimisation (see AGENT_TRAIL / MORNING_REPORT P2).
    """
    script_in_example = run_file_py if run_file_name.endswith(".ipynb") else run_file_name
    if not script_in_example or not script_in_example.endswith(".py"):
        return "\n# (no Python entrypoint for Icepack structured export)\n"

    export_path = f"{run_dir}/{EXPORT_MODULE_NAME}"
    runner_path = f"{run_dir}/{RUNNER_MODULE_NAME}"
    inner = (
        f'cd "{example_dir}" && '
        f'python "{runner_path}" "{example_dir}/{script_in_example}" "{run_dir}"'
    )

    if backend == "spack":
        run_line = (
            f'( source "{spack_path}/scripts/activate.sh" && {inner} ) '
            '|| echo "[cryostack][warn] icepack structured export step failed (non-fatal)"'
        )
    else:
        run_line = (
            f'apptainer exec '
            f'-B "{example_dir}":"{example_dir}","{run_dir}":"{run_dir}"{stack_binds} '
            f'"{sif_path}" with-icepack bash -lc \'{inner}\' '
            '|| echo "[cryostack][warn] icepack structured export step failed (non-fatal)"'
        )

    return f'''
# --- CryoStack Icepack structured export (non-fatal) ------------------
mkdir -p "{run_dir}/outputs"
{_heredoc(export_path, export_module_source(), "CRYOSTACK_ICEPACK_EXPORT_EOF")}
{_heredoc(runner_path, runner_module_source(), "CRYOSTACK_ICEPACK_RUNNER_EOF")}
{run_line}
'''
