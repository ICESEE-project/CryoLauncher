from __future__ import annotations

from pathlib import Path

from .notebook import RUN_SCRIPT_NAME

#: Icepack examples are notebook/script based rather than a fixed entrypoint file
EXAMPLE_ENTRYPOINTS: tuple[str, ...] = ()
_EXAMPLE_GLOBS = ("*.ipynb", "*.py")


def example_runnable(path) -> bool:
    root = Path(path)
    return root.is_dir() and any(next(root.glob(g), None) for g in _EXAMPLE_GLOBS)


def example_template():
    return None


def build_run_command(*, backend, target, example_dir, exec_dir, image_uri, ntasks) -> str:
    """A faithful ONE-LINE preview of what actually runs.

    An Icepack run (Remote or Cloud) is a single step through the shared
    runner (``cryostack_icepack_runner.py`` -- see
    :mod:`cryostack_src.models.icepack.export`): headless Matplotlib, run the
    script once, capture figures + metadata, structured-export. Only the
    provider wrapper differs.
    """
    from .export import RUNNER_MODULE_NAME

    _t = (target or "").strip()
    if not _t or not _t.endswith((".py", ".ipynb")):
        if backend == "spack":
            return f'cd "{example_dir}" && python -c "import icepack"'
        return f'apptainer exec "{image_uri}" with-icepack python -c "import icepack"'

    py = Path(_t).with_suffix(".py").name if _t.endswith(".ipynb") else _t
    nbconvert = (f'jupyter nbconvert --to script "{_t}" && '
                 if _t.endswith(".ipynb") else "")
    inner = f'{nbconvert}python "{RUNNER_MODULE_NAME}" "{py}" <run-dir>'
    if backend == "spack":
        return f'cd "{example_dir}" && {inner}'
    return f'apptainer exec "{image_uri}" with-icepack bash -lc \'cd "{example_dir}" && {inner}\''


def build_activation_check() -> str:
    return 'python -c "import icepack; print(\'Icepack import successful\')"'


#: Icepack examples are notebook/script based rather than a fixed entrypoint file
#: -- notebooks first, then scripts. ``.m`` is only a last resort (an Icepack
#: example directory should not contain one).
_RUN_TARGET_ORDER = (".ipynb", ".py", ".m")


def order_run_targets(names):
    # RUN_SCRIPT_NAME ("run.py") is cryostack_src.models.icepack.notebook's
    # deterministic conversion artifact: when a materialized notebook working
    # copy is present, its generated run.py -- not the co-staged source
    # notebook -- is THE canonical execution target. A fixed, project-defined
    # convention name (exactly like ISSM's "runme.m"), not a per-example
    # special case: any directory with a file literally named this puts it
    # first, regardless of what else is present.
    preferred = [n for n in names if n.lower().endswith(_RUN_TARGET_ORDER)]
    others = [n for n in names if not n.lower().endswith(_RUN_TARGET_ORDER)]
    if RUN_SCRIPT_NAME in preferred:
        preferred = [RUN_SCRIPT_NAME] + [n for n in preferred if n != RUN_SCRIPT_NAME]
    return preferred + others


def choose_run_target(names):
    if RUN_SCRIPT_NAME in names:
        return RUN_SCRIPT_NAME
    ordered = order_run_targets(names)
    for suffix in _RUN_TARGET_ORDER:
        for name in ordered:
            if name.lower().endswith(suffix):
                return name
    return ordered[0] if ordered else ""
