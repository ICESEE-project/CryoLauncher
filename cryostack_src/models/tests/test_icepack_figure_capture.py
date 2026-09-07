"""Generalized Matplotlib figure capture for converted Icepack notebook runs.

The upstream tutorials draw figures inline and never save them; run headless
they are computed and thrown away. ``cryostack_icepack_runner.py`` now:

* forces a headless backend (Agg) before the script imports matplotlib;
* persists still-open figures to ``outputs/figures/figure-NN.png``;
* never injects ``savefig()`` into the science script;
* de-duplicates against figures the script saved itself.

Then the stdlib collector merges honestly: ``artifacts`` when figures /
native files exist, ``empty`` only when nothing persistent was produced,
``ok`` left untouched when the structured exporter recognised fields.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cryostack_src.models.icepack.export import runner_module_source
from cryostack_src.models.icepack.postprocess import build_postprocess

pytest.importorskip("matplotlib")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _run_runner(run_dir: Path, script: Path) -> subprocess.CompletedProcess:
    runner = run_dir / "cryostack_icepack_runner.py"
    _write(runner, runner_module_source())
    env = dict(os.environ)
    env.pop("MPLBACKEND", None)          # the runner must set this itself
    # the cloud runner `cd "${WORKDIR}"` before running the model -- so
    # relative paths in the science script resolve against the run dir.
    return subprocess.run(
        [sys.executable, str(runner), str(script), str(run_dir)],
        capture_output=True, text=True, env=env, cwd=str(run_dir),
    )


def _run_collector(run_dir: Path, example_dir: Path, *, started: float) -> dict:
    script = run_dir / "cryostack_icepack_postprocess.py"
    _write(script, build_postprocess())
    env = {
        "CRYOSTACK_RUN_DIR": str(run_dir),
        "CRYOSTACK_EXAMPLE_DIR": str(example_dir),
        "CRYOSTACK_RUN_STARTED": str(started),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    p = subprocess.run([sys.executable, str(script)], capture_output=True,
                       text=True, env=env)
    assert p.returncode == 0, p.stderr
    return json.loads((run_dir / "outputs" / "metadata.json").read_text())


# -- 00-meshes-functions class: figures, no structured fields -------------
_PRIMER_SCRIPT = """
import matplotlib.pyplot as plt
# three inline-only figures, exactly like a converted tutorial
for _ in range(3):
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [2, 1, 3])
print("primer done")
"""


def test_primer_notebook_captures_live_figures_and_reports_artifacts(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    ex = run                                   # cloud: WORKDIR is both
    script = run / "run.py"
    _write(script, _PRIMER_SCRIPT)
    started = time.time()

    r = _run_runner(run, script)
    assert r.returncode == 0, r.stderr
    figs = sorted((run / "outputs" / "figures").glob("figure-*.png"))
    assert [p.name for p in figs] == ["figure-01.png", "figure-02.png", "figure-03.png"]
    assert all(p.stat().st_size > 0 for p in figs)

    meta = _run_collector(run, ex, started=started)
    assert meta["status"] == "artifacts"
    assert meta["fields"] == [] and meta["solutions"] == []      # never guessed
    assert set(meta["figures"]) == {"figure-01.png", "figure-02.png", "figure-03.png"}


# -- explicit savefig is preserved AND not double-captured ---------------
_MIXED_SCRIPT = """
import matplotlib.pyplot as plt
f1, a1 = plt.subplots(); a1.plot([0, 1], [1, 0])
f1.savefig("my-explicit-plot.png")            # the script saves this one itself
f2, a2 = plt.subplots(); a2.plot([0, 1], [0, 1])   # left open -> captured
"""


def test_explicit_savefig_is_kept_and_not_duplicated(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    script = run / "run.py"
    _write(script, _MIXED_SCRIPT)
    started = time.time()

    r = _run_runner(run, script)
    assert r.returncode == 0, r.stderr

    # the script's own file is preserved where it wrote it
    assert (run / "my-explicit-plot.png").is_file()
    # exactly ONE generic capture (the still-open figure), not two
    captured = sorted((run / "outputs" / "figures").glob("figure-*.png"))
    assert [p.name for p in captured] == ["figure-01.png"]

    meta = _run_collector(run, run, started=started)
    assert meta["status"] == "artifacts"
    # collector sweeps the script's own png (fresh, outside outputs/) in too
    assert "my-explicit-plot.png" in meta["figures"]
    assert "figure-01.png" in meta["figures"]


# -- truly empty run stays honestly empty ------------------------------
_EMPTY_SCRIPT = "print('no plots, no files')\n"


def test_run_with_no_figures_or_files_stays_empty(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    script = run / "run.py"
    _write(script, _EMPTY_SCRIPT)
    started = time.time()

    r = _run_runner(run, script)
    assert r.returncode == 0, r.stderr
    assert not list((run / "outputs" / "figures").glob("*.png"))

    meta = _run_collector(run, run, started=started)
    assert meta["status"] == "empty"
    assert meta["figures"] == [] and meta["model_files"] == []


# -- a failing science script still fails the job (capture is non-fatal) -
_FAILING_SCRIPT = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots(); ax.plot([0, 1], [1, 0])
raise SystemExit(7)
"""


def test_runner_propagates_the_science_exit_code(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    script = run / "run.py"
    _write(script, _FAILING_SCRIPT)
    r = _run_runner(run, script)
    assert r.returncode == 7            # the science's own non-zero exit, verbatim


# -- honest merge: the exporter's "ok" is never downgraded --------------
def test_collector_never_downgrades_a_structured_ok_package(tmp_path):
    run = tmp_path / "run"
    (run / "outputs" / "figures").mkdir(parents=True)
    (run / "outputs" / "fields" / "icepack").mkdir(parents=True)
    # a structured exporter already declared ok with a real field
    (run / "outputs" / "metadata.json").write_text(json.dumps({
        "schema": "cryostack.icepack.results", "version": 2, "model": "icepack",
        "status": "ok",
        "fields": [{"name": "thickness", "path": "fields/icepack/thickness.h5"}],
        "figures": [], "model_files": [], "skipped": [],
    }))
    (run / "outputs" / "figures" / "figure-01.png").write_bytes(b"\x89PNG\r\n")

    meta = _run_collector(run, run, started=time.time() - 5)
    assert meta["status"] == "ok"                       # never downgraded
    assert meta["fields"][0]["name"] == "thickness"
    assert "figure-01.png" in meta["figures"]           # folded in honestly


def test_collector_upgrades_empty_to_artifacts_when_figures_exist(tmp_path):
    """The 00-meshes flow: the exporter found no allow-listed field and wrote
    status 'empty'; the collector then sees the captured figures and reports
    'artifacts' -- honest, no fabricated field."""
    run = tmp_path / "run"
    (run / "outputs" / "figures").mkdir(parents=True)
    (run / "outputs" / "metadata.json").write_text(json.dumps({
        "schema": "cryostack.icepack.results", "version": 2, "model": "icepack",
        "status": "empty", "fields": [], "figures": [], "model_files": [],
        "skipped": [],
    }))
    (run / "outputs" / "figures" / "figure-01.png").write_bytes(b"\x89PNG\r\n")
    (run / "outputs" / "figures" / "figure-02.png").write_bytes(b"\x89PNG\r\n")

    meta = _run_collector(run, run, started=time.time() - 5)
    assert meta["status"] == "artifacts"
    assert meta["fields"] == []
    assert set(meta["figures"]) == {"figure-01.png", "figure-02.png"}
