"""Backend-neutral reader for the CryoStack ISSM result package.

Reads ``outputs/{metadata.json, mesh/mesh.h5, fields/<Sol>/<Field>.h5}`` produced
by :mod:`cryostack_src.models.issm.postprocess`. Needs neither MATLAB nor a live
ISSM install -- so the same code serves a run retrieved from Remote, a Container,
or S3, and later the agents.

It is completely unaware of SSH / connector / Slurm / Apptainer / AWS /
Workspace: point it at any local directory that contains an ``outputs/`` tree
and it behaves identically.

Deterministic plotting is NOT here -- it lives in
:mod:`cryostack_src.visualization.issm`, which consumes this package.
:meth:`ResultPackage.recommended_plots` returns plot *descriptions* only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "cryostack.issm.results"
METADATA_NAME = "metadata.json"

_MESH_ELEMENT_COLUMNS = {3, 4, 6}

# Preference layer only -- the field list in ``metadata.json`` is always
# authoritative. This just decides *ordering* and which fields a compact UI
# should surface first, by ISSM solution family. Unknown solutions (and unknown
# fields within a known solution) fall back to metadata order.
#
# Field names are taken from the ISSM class ``defaultoutputs`` (e.g.
# ``src/m/classes/stressbalance.m``), not guessed. A transient run's field set
# is whatever the sub-analyses actually produced -- the extra names here are
# just a sensible surfacing order when present.
PREFERRED_FIELDS: dict[str, tuple[str, ...]] = {
    "StressbalanceSolution": ("Vel", "Vx", "Vy", "Vz", "Pressure"),
    "ThermalSolution": (
        "Temperature", "Enthalpy", "Waterfraction", "Watercolumn",
        "BasalforcingsGroundediceMeltingRate",
    ),
    "SteadystateSolution": (
        "Vel", "Vx", "Vy", "Pressure", "Temperature",
        "BasalforcingsGroundediceMeltingRate",
    ),
    "MasstransportSolution": ("Thickness", "Surface", "Base"),
    "BalancethicknessSolution": ("Thickness", "Vel"),
    "BalancevelocitySolution": ("Vel", "Vx", "Vy"),
    "TransientSolution": (
        "Vel", "Vx", "Vy", "Vz", "Thickness", "Surface", "Base", "Pressure",
        "Temperature", "MaskIceLevelset", "MaskOceanLevelset",
        "BasalforcingsGroundediceMeltingRate", "SmbMassBalance",
        "EffectivePressure", "HydrologyHead", "HydrologyGapHeight",
        "HydraulicPotential", "Watercolumn",
    ),
    "HydrologySolution": (
        "EffectivePressure", "HydrologyHead", "HydraulicPotential",
        "HydrologyGapHeight", "HydrologySheetThickness", "Watercolumn",
        "HydrologyBasalFlux", "DegreeOfChannelization",
        "ChannelArea", "ChannelDischarge",
        "HydrologyWaterVx", "HydrologyWaterVy",
    ),
    "DamageEvolutionSolution": ("DamageDbar", "DamageD"),
    "EsaSolution": (
        "EsaUmotion", "EsaNmotion", "EsaEmotion", "EsaXmotion",
        "EsaStrainratexx", "EsaStrainrateyy", "EsaRotationrate",
    ),
    "GiaSolution": ("GiaW", "GiaER", "UGia", "URGia"),
    "LoveSolution": (),
    "SamplingSolution": ("Sample",),
    "OceantransportSolution": ("Thickness", "Surface", "Base"),
    # Forward-compat: sea-level-change families that some ISSM builds expose.
    "SealevelchangeSolution": ("Sealevel", "Bslc", "SealevelBarystaticIce"),
    "SlrSolution": ("Sealevel", "Bslc"),
}


def preferred_order(solution: str, fields) -> list[str]:
    """Order ``fields`` (names actually present) by the solution's preference,
    with anything not listed kept in its original order at the end."""
    names = list(fields)
    ranked = PREFERRED_FIELDS.get(solution, ())
    index = {name: i for i, name in enumerate(ranked)}
    return sorted(names, key=lambda n: (index.get(n, len(ranked)), names.index(n)))


class ResultError(RuntimeError):
    """The requested result / field / mesh could not be read."""


# ── metadata records ───────────────────────────────────────────────────────
@dataclass(frozen=True)
class FieldInfo:
    name: str
    solution: str
    location: str                 # "scalar" | "nodal" | "elemental" | "other"
    shape: tuple[int, ...]
    dtype: str
    transient: bool
    path: str
    units: str | None = None
    available_timesteps: tuple[int, ...] | None = None


@dataclass(frozen=True)
class SkippedField:
    name: str
    reason: str
    kind: str


@dataclass(frozen=True)
class SolutionInfo:
    name: str
    transient: bool
    timesteps: int
    time: tuple[float, ...] | None
    step: tuple[int, ...] | None
    fields: tuple[FieldInfo, ...]
    skipped: tuple[SkippedField, ...]

    def field(self, name: str) -> FieldInfo:
        for f in self.fields:
            if f.name == name:
                return f
        raise ResultError(f"{self.name}: no exported field {name!r}")


def _as_shape(value) -> tuple[int, ...]:
    if value is None:
        return ()
    if isinstance(value, (int, float)):
        return (int(value),)
    return tuple(int(v) for v in value)


def _as_list(value):
    if value is None or (isinstance(value, list) and not value):
        return None
    if isinstance(value, (int, float)):
        return [value]
    return list(value)


def _as_int_tuple_or_none(value):
    """MATLAB ``jsonencode`` emits a length-1 array as a bare scalar, so a
    field available at a single timestep arrives as ``3`` not ``[3]``."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return (int(value),)
    if isinstance(value, list):
        return tuple(int(v) for v in value)
    return None


# ── the package ────────────────────────────────────────────────────────────
class ResultPackage:
    """A read-only view of one run's exported results."""

    def __init__(self, *, root: Path, outputs: Path | None, metadata: dict,
                 legacy: bool) -> None:
        self.root = Path(root)
        self.outputs = outputs
        self._meta = metadata or {}
        self._legacy = legacy

    # -- top level -----------------------------------------------------------
    @property
    def schema(self) -> str | None:
        return self._meta.get("schema")

    @property
    def version(self) -> int | None:
        return self._meta.get("version")

    @property
    def model(self) -> str | None:
        return self._meta.get("model")

    @property
    def legacy(self) -> bool:
        return self._legacy

    @property
    def status(self) -> str:
        if self.outputs is None:
            return "missing"
        if self._legacy:
            return "legacy"
        return self._meta.get("status") or "ok"

    def is_readable(self) -> bool:
        """True when there is a schema-conformant package to read."""
        return self.outputs is not None and not self._legacy \
            and self._meta.get("schema") == SCHEMA

    # -- mesh --------------------------------------------------------------
    def mesh_metadata(self) -> dict:
        return dict(self._meta.get("mesh") or {})

    def load_mesh(self) -> dict:
        self._require_readable()
        mesh_meta = self._meta.get("mesh") or {}
        rel = mesh_meta.get("path", "mesh/mesh.h5")
        path = self.outputs / rel
        if not path.is_file():
            raise ResultError(f"mesh file not found: {path}")
        h5py = _h5py()
        import numpy as np

        out: dict = {}
        with h5py.File(path, "r") as fh:
            for key in ("x", "y", "z"):
                if key in fh:
                    out[key] = np.asarray(fh[key][()]).reshape(-1)
            if "elements" in fh:
                el = np.asarray(fh["elements"][()])
                out["elements"] = self._orient_elements(el, mesh_meta)
        out["numberofvertices"] = int(mesh_meta.get("numberofvertices",
                                                    len(out.get("x", []))))
        out["numberofelements"] = int(mesh_meta.get("numberofelements",
                                                    len(out.get("elements", []))))
        out["dimension"] = int(mesh_meta.get("dimension", 3 if "z" in out else 2))
        out["element_columns"] = int(mesh_meta.get(
            "element_columns", out["elements"].shape[1] if "elements" in out else 0))
        out["connectivity_indexing"] = "0-based"
        out["connectivity_indexing_source"] = mesh_meta.get(
            "connectivity_indexing", "unknown")
        return out

    @staticmethod
    def _orient_elements(el, mesh_meta: dict):
        import numpy as np

        el = np.asarray(el)
        ne = int(mesh_meta.get("numberofelements", 0))
        ncols = int(mesh_meta.get("element_columns", 0))
        if el.ndim == 2:
            r, c = el.shape
            if ncols and (r, c) == (ncols, ne):
                el = el.T
            elif not (ncols and (r, c) == (ne, ncols)):
                # last axis should be the small one (3/4/6)
                if r in _MESH_ELEMENT_COLUMNS and c not in _MESH_ELEMENT_COLUMNS:
                    el = el.T
        if mesh_meta.get("connectivity_indexing") == "1-based":
            el = el - 1
        return el.astype("int64", copy=False)

    # -- solutions -------------------------------------------------------
    def _solutions_raw(self) -> list[dict]:
        return list(self._meta.get("solutions") or [])

    def available_solutions(self) -> list[str]:
        return [s.get("name", "") for s in self._solutions_raw() if s.get("name")]

    def solution(self, name: str) -> SolutionInfo:
        for s in self._solutions_raw():
            if s.get("name") == name:
                return self._build_solution(s)
        raise ResultError(f"no such solution: {name!r}")

    def _build_solution(self, s: dict) -> SolutionInfo:
        name = s["name"]
        transient = bool(s.get("transient"))
        fields = tuple(
            FieldInfo(
                name=f["name"], solution=name,
                location=f.get("location", "other"),
                shape=_as_shape(f.get("shape")),
                dtype=f.get("dtype", "float64"),
                transient=transient,
                path=f.get("path", f"fields/{name}/{f['name']}.h5"),
                units=f.get("units"),
                available_timesteps=_as_int_tuple_or_none(
                    f.get("available_timesteps")),
            )
            for f in (s.get("fields") or [])
        )
        skipped = tuple(
            SkippedField(name=k.get("name", "?"), reason=k.get("reason", ""),
                         kind=k.get("kind", "unknown"))
            for k in (s.get("skipped") or [])
        )
        time = _as_list(s.get("time"))
        step = _as_list(s.get("step"))
        return SolutionInfo(
            name=name, transient=transient,
            timesteps=int(s.get("timesteps", 1)),
            time=tuple(float(t) for t in time) if time is not None else None,
            step=tuple(int(t) for t in step) if step is not None else None,
            fields=fields, skipped=skipped,
        )

    def available_fields(self, solution: str, *, preferred: bool = True) -> list[str]:
        names = [f.name for f in self.solution(solution).fields]
        return preferred_order(solution, names) if preferred else names

    def field_metadata(self, solution: str, field: str) -> FieldInfo:
        return self.solution(solution).field(field)

    def timesteps(self, solution: str) -> list[int]:
        sol = self.solution(solution)
        return list(range(sol.timesteps))

    def times(self, solution: str) -> list[float] | None:
        sol = self.solution(solution)
        return list(sol.time) if sol.time is not None else None

    # -- field data -----------------------------------------------------
    def load_field(self, solution: str, field: str, timestep: int | None = None):
        self._require_readable()
        info = self.field_metadata(solution, field)
        path = self.outputs / info.path
        if not path.is_file():
            raise ResultError(f"field data not found: {path}")

        h5py = _h5py()
        import numpy as np

        with h5py.File(path, "r") as fh:
            if "values" not in fh:
                raise ResultError(f"{path}: no /values dataset")
            raw = np.asarray(fh["values"][()])

        if not info.transient:
            arr = raw.reshape(-1)
            if timestep not in (None, 0):
                raise ResultError(
                    f"{solution}.{field} is not time-dependent (timestep={timestep})"
                )
            return arr

        n_hint = info.shape[-1] if len(info.shape) == 2 else None
        arr = self._orient_timeseries(raw, info.shape, n_hint)
        if timestep is None:
            return arr
        nsteps = arr.shape[0]
        if not (0 <= timestep < nsteps):
            raise ResultError(
                f"{solution}.{field}: timestep {timestep} out of range [0, {nsteps})"
            )
        if info.available_timesteps is not None and timestep not in info.available_timesteps:
            raise ResultError(
                f"{solution}.{field}: field not available at timestep {timestep} "
                f"(available: {list(info.available_timesteps)})"
            )
        return arr[timestep]

    @staticmethod
    def _orient_timeseries(raw, shape: tuple[int, ...], n_hint: int | None):
        import numpy as np

        a = np.asarray(raw)
        if a.ndim == 1:
            return a.reshape(-1, 1)
        if a.ndim != 2:
            return a
        r, c = a.shape
        if len(shape) == 2:
            ns, n = shape
            if (r, c) == (ns, n):
                return a
            if (r, c) == (n, ns):
                return a.T
        if n_hint is not None:
            if c == n_hint:
                return a
            if r == n_hint:
                return a.T
        return a

    # -- recommendations (metadata only -- rendering lives in
    #    cryostack_src.visualization.issm) -----------------------------------
    def recommended_plots(self, solution: str | None = None) -> list[dict]:
        """Plot *descriptions*, ordered by :data:`PREFERRED_FIELDS`. Renders
        nothing. ``solution=None`` aggregates across every solution."""
        targets = ([solution] if solution is not None
                   else self.available_solutions())
        out: list[dict] = []
        for name in targets:
            sol = self.solution(name)
            by_name = {f.name: f for f in sol.fields}
            for field_name in preferred_order(name, by_name):
                f = by_name[field_name]
                if f.location in ("nodal", "elemental"):
                    out.append({
                        "solution": name, "field": f.name,
                        "kind": "map", "location": f.location,
                        "transient": f.transient,
                        "timestep": (self._default_timestep(sol, f)
                                     if f.transient else None),
                    })
                elif f.location == "scalar" and f.transient:
                    out.append({
                        "solution": name, "field": f.name,
                        "kind": "timeseries", "location": "scalar",
                        "transient": True, "timestep": None,
                    })
        return out

    @staticmethod
    def _default_timestep(sol: SolutionInfo, field: FieldInfo) -> int:
        """Last timestep the field is actually available at."""
        if field.available_timesteps:
            return max(field.available_timesteps)
        return max(sol.timesteps - 1, 0)

    # -- legacy / figures ----------------------------------------------
    def figures(self) -> list[Path]:
        if self.outputs is None:
            return []
        figdir = self.outputs / "figures"
        return sorted(figdir.glob("*.png")) if figdir.is_dir() else []

    def figure_captions(self) -> dict:
        """``{filename: {title?, ...}}`` -- ISSM writes deterministic named
        figures and records no per-figure caption metadata today, so this is
        empty; the Results gallery then labels by filename."""
        fm = self._meta.get("figures_meta")
        return {k: dict(v) for k, v in fm.items()} if isinstance(fm, dict) else {}

    def model_mat(self) -> Path | None:
        if self.outputs is None:
            return None
        candidate = self.outputs / "model" / "md_final.mat"
        return candidate if candidate.is_file() else None

    def legacy_artifacts(self) -> dict:
        if self.outputs is None:
            return {"model_mat": None, "figures": [], "mats": [], "other": []}
        mats = sorted(p for p in self.outputs.rglob("*.mat"))
        pngs = sorted(p for p in self.outputs.rglob("*.png"))
        return {
            "model_mat": str(self.model_mat()) if self.model_mat() else None,
            "figures": [str(p) for p in pngs],
            "mats": [str(p) for p in mats],
            "other": [str(p) for p in sorted(self.outputs.rglob("*"))
                      if p.is_file() and p.suffix.lower() not in
                      {".mat", ".png", ".json", ".h5"}],
        }

    # -- internals ---------------------------------------------------------
    def _require_readable(self) -> None:
        if self.outputs is None:
            raise ResultError(f"no result package under {self.root}")
        if self._legacy:
            raise ResultError(
                "this run predates the neutral result package "
                "(only md_final.mat / figures are available)"
            )
        if self._meta.get("schema") != SCHEMA:
            raise ResultError(f"unknown result schema: {self._meta.get('schema')!r}")


# ── discovery ──────────────────────────────────────────────────────────────
def _find_outputs(root: Path) -> Path | None:
    root = root.expanduser()
    if root.is_dir():
        if root.name == "outputs":
            return root
        if (root / "outputs").is_dir():
            return root / "outputs"
        if any((root / m).exists() for m in
               (METADATA_NAME, "model", "fields", "mesh", "figures")):
            return root
    return None


def discover_results(path: str | Path) -> ResultPackage:
    """Locate and describe a run's result package. Never raises for a missing
    or legacy directory -- inspect :attr:`ResultPackage.status`."""
    root = Path(path)
    outputs = _find_outputs(root)
    if outputs is None:
        return ResultPackage(root=root, outputs=None, metadata={}, legacy=False)

    meta_file = outputs / METADATA_NAME
    if meta_file.is_file():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ResultPackage(root=root, outputs=outputs, metadata={}, legacy=True)
        if isinstance(meta, dict) and meta.get("schema") == SCHEMA:
            return ResultPackage(root=root, outputs=outputs, metadata=meta, legacy=False)
        return ResultPackage(root=root, outputs=outputs, metadata=meta if isinstance(meta, dict) else {},
                             legacy=True)

    # no metadata.json -> a pre-contract run
    return ResultPackage(root=root, outputs=outputs, metadata={}, legacy=True)


def _h5py():
    try:
        import h5py  # noqa: PLC0415 - optional, only needed to read arrays
    except ImportError as err:  # pragma: no cover - environment dependent
        raise ResultError(
            "reading result arrays needs h5py (metadata is still available "
            "without it)"
        ) from err
    return h5py
