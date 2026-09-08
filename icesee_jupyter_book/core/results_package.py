"""DA-aware ResultPackage foundation for ICESEE (Phase 3 of the ICESEE
parity port): the smallest viable schema over outputs ICESEE already
writes today -- HDF5 datasets under ``results/`` and PNGs under
``figures/``.

This is deliberately NOT the CryoLauncher glaciological tier-1
ResultPackage (``outputs/{metadata,mesh,fields,model,figures}``,
cryostack_src/models/*/results.py) -- an ICESEE run is an ensemble /
data-assimilation experiment, not a single deterministic mesh solve, and
forcing that schema onto it would flatten exactly the DA identity the rest
of this port preserves.

Categorisation is name-based, against the dataset names ICESEE's own EnKF
pipeline actually writes (see external/ICESEE/src/EnKF/*.py):
  - ``true_state`` / ``nurged_state`` / ``wrong_state`` / ``background``
    -> "forecast" (ICESEE's own term for the true/uncorrected-background
    trajectory before assimilation)
  - a name starting with ``ensemble`` (``ensemble``, ``ensemble_mean``) or
    containing ``analysis`` -> "ensemble"
  - a name containing ``obs`` (``hu_obs``), or the observation-error
    covariance ``R`` -> "observations"
  - anything else -> "model_native" (never dropped -- no scientific
    meaning is invented for a name this module does not recognise)

Inspection is HEADER-ONLY (dataset name / shape / dtype via h5py) -- this
module never reads a full array, and never renders or interprets a plot.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_FORECAST_NAMES = {"true_state", "nurged_state", "wrong_state", "background"}


def _categorize(name: str) -> str:
    low = name.lower()
    if low in _FORECAST_NAMES:
        return "forecast"
    if low.startswith("ensemble") or "analysis" in low:
        return "ensemble"
    if "obs" in low or low == "r":
        return "observations"
    return "model_native"


@dataclass(frozen=True)
class H5DatasetInfo:
    name: str
    shape: tuple
    dtype: str
    category: str    # "forecast" | "ensemble" | "observations" | "model_native"


@dataclass(frozen=True)
class H5ArtifactInfo:
    path: Path
    datasets: tuple    # tuple[H5DatasetInfo, ...]

    def by_category(self, category: str) -> tuple:
        return tuple(d for d in self.datasets if d.category == category)


def inspect_h5_file(path: "Path | str") -> H5ArtifactInfo:
    """Header-only inspection: dataset names, shapes, dtypes. Never a full
    array read. A dataset h5py cannot introspect is skipped, not fatal."""
    import h5py

    datasets = []
    with h5py.File(path, "r") as f:
        for name in f.keys():
            try:
                ds = f[name]
                datasets.append(H5DatasetInfo(
                    name=name, shape=tuple(ds.shape), dtype=str(ds.dtype),
                    category=_categorize(name),
                ))
            except Exception:  # noqa: BLE001
                continue
    return H5ArtifactInfo(path=Path(path), datasets=tuple(datasets))


@dataclass(frozen=True)
class IceseeResultPackage:
    """Read-only, data-only view of one ICESEE run's local outputs."""

    run_dir: Path
    h5_artifacts: tuple    # tuple[H5ArtifactInfo, ...]
    figures: tuple         # tuple[Path, ...]

    def _datasets(self, category: str) -> tuple:
        return tuple(
            dataset
            for artifact in self.h5_artifacts
            for dataset in artifact.by_category(category)
        )

    def forecast(self) -> tuple:
        return self._datasets("forecast")

    def ensemble(self) -> tuple:
        return self._datasets("ensemble")

    def observations(self) -> tuple:
        return self._datasets("observations")

    def model_native(self) -> tuple:
        return self._datasets("model_native")

    def is_empty(self) -> bool:
        return not self.h5_artifacts and not self.figures

    def summary_lines(self) -> list:
        """(category label, dataset) rows for a Results-tab listing. Only
        categories with at least one dataset are represented."""
        lines = []
        for category, label in (
            ("forecast", "Forecast/truth"),
            ("ensemble", "Ensemble"),
            ("observations", "Observations"),
            ("model_native", "Other"),
        ):
            for dataset in self._datasets(category):
                lines.append(f"{label}: {dataset.name} {list(dataset.shape)} ({dataset.dtype})")
        return lines


def discover_result_package(run_dir: "Path | str") -> IceseeResultPackage:
    """Build an :class:`IceseeResultPackage` from what is ACTUALLY present
    under ``run_dir`` today -- never a fabricated/expected layout."""
    run_dir = Path(run_dir)
    results_dir = run_dir / "results"
    figures_dir = run_dir / "figures"

    artifacts = []
    if results_dir.is_dir():
        for h5_file in sorted(results_dir.glob("*.h5")):
            try:
                artifacts.append(inspect_h5_file(h5_file))
            except Exception:  # noqa: BLE001 - a corrupt file must not break discovery
                continue

    figures = sorted(figures_dir.glob("*.png")) if figures_dir.is_dir() else []
    if not figures and results_dir.is_dir():
        figures = sorted(results_dir.glob("*.png"))

    return IceseeResultPackage(
        run_dir=run_dir, h5_artifacts=tuple(artifacts), figures=tuple(figures),
    )
