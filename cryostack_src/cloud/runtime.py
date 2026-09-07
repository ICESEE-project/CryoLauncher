# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Generic Cloud Runtime
# File        : runtime.py
#
# Description :
#     The provider-neutral cloud execution contract: the small runner that
#     runs inside the batch container, and the machine-readable execution
#     descriptor staged alongside a run's inputs.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-31
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
CryoStack generic cloud runtime.

One small runner, one execution descriptor -- the SAME runner for every
supported model; only the ``case "${CRYOSTACK_MODEL}"`` branch differs. The
runner:

1. reads its runtime configuration from the environment
   (``CRYOSTACK_S3_RUN`` / ``CRYOSTACK_MODEL`` / ``CRYOSTACK_RUN_TARGET``),
2. syncs ``<s3-run>/input/`` into a local working directory,
3. runs the model runtime -- exactly what ``stage_example_for_run`` prepared
   (ISSM: injected ``runme.m``, ``cryostack_md_overrides.m``, ``data/<...>``
   datasets, ``postprocess_icesee.m``; Icepack: the selected example's own
   ``.py``/``.ipynb`` run target, then -- if the caller staged one alongside
   the run inputs -- the portable output collector produced by
   :mod:`cryostack_src.models.icepack.postprocess`),
4. syncs ``<workdir>/outputs/`` back to ``<s3-run>/outputs/`` (best effort,
   even on a failed run), and
5. exits with the *true* model exit code.

No scientific logic lives in the runner beyond selecting the per-model runtime
command. No credentials and no MATLAB license value are ever embedded -- the
license, if any, arrives only through the batch container's environment.

**Execution-artifact contract**: this runner script itself becomes the Batch
job definition's ``containerProperties.command`` (:func:`cloud_run_command`),
and AWS Batch resolves/forwards a job's effective container command through
ECS ``RunTask`` overrides on every launch -- capped at 8192 characters,
exactly like ``submit-job``'s own ``--container-overrides``. Any run-specific
or model-specific logic (an output collector, a helper script, ...) that
would make this text large must therefore never be embedded inline here: it
is staged as an ordinary FILE alongside the run's other inputs (via
``WorkspaceManager.stage_example_for_run``'s ``extra_files``, exactly how
ISSM's own ``postprocess_icesee.m`` already works) and simply *invoked* by
filename after ``phase 1`` downloads it -- the runner only ever contains the
short, per-model INVOCATION, never the helper's source text. A run that
predates this convention (or a caller that never staged the helper) is not a
hard failure: the invocation is skipped with a warning, exactly like every
other best-effort step here.
"""

from __future__ import annotations

import re

#: models with a complete cloud runtime path today
SUPPORTED_CLOUD_MODELS: tuple[str, ...] = ("issm", "icepack")

#: filenames the Icepack branch looks for under WORKDIR after phase 1 -- the
#: SAME names a caller must use as extra_files keys when staging (see
#: icepack_postprocess_extra_files() below); a single source of truth so the
#: runner script and the staging helper can never drift apart. The runner +
#: export module names are re-exported from
#: cryostack_src.models.icepack.export so the cloud and Remote/SLURM paths
#: stage the identical helpers.
ICEPACK_POSTPROCESS_FILENAME = "cryostack_icepack_postprocess.py"
ICEPACK_RUNNER_FILENAME = "cryostack_icepack_runner.py"
ICEPACK_EXPORT_FILENAME = "cryostack_icepack_export.py"

#: version of the structured-result contract the run must produce
RESULT_CONTRACT_VERSION = 1

RUN_DESCRIPTOR_NAME = "cryostack-run.json"
RUN_DESCRIPTOR_SCHEMA = "cryostack.cloud.run"
RUN_DESCRIPTOR_VERSION = 1

_RUN_TARGET_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\Z")


class CloudRuntimeError(RuntimeError):
    """The cloud runtime contract could not be satisfied for this run."""


def is_supported_cloud_model(model: str) -> bool:
    return (model or "").strip().lower() in SUPPORTED_CLOUD_MODELS


# ── execution descriptor ─────────────────────────────────────────────────
def build_run_descriptor(
    *,
    model: str,
    run_target: str,
    working_directory: str = ".",
    result_contract_version: int = RESULT_CONTRACT_VERSION,
) -> dict:
    """The machine-readable execution descriptor placed under ``input/``.

    Execution inputs only -- **never** AWS/SSH credentials, local user paths or
    a MATLAB license value.
    """
    m = (model or "").strip().lower()
    if not m:
        raise CloudRuntimeError("a cloud run descriptor needs a model")
    target = (run_target or "").strip()
    if not target or target.startswith(("/", "~")) or ".." in target.split("/"):
        raise CloudRuntimeError(f"unsafe run target for a cloud run: {run_target!r}")
    if not _RUN_TARGET_RE.match(target):
        raise CloudRuntimeError(f"unsafe run target for a cloud run: {run_target!r}")
    wd = (working_directory or ".").strip()
    if wd.startswith(("/", "~")) or ".." in wd.split("/"):
        raise CloudRuntimeError(f"working_directory must be relative: {working_directory!r}")
    return {
        "schema": RUN_DESCRIPTOR_SCHEMA,
        "version": RUN_DESCRIPTOR_VERSION,
        "model": m,
        "run_target": target,
        "working_directory": wd or ".",
        "result_contract_version": int(result_contract_version),
    }


_SECRET_HINTS = (
    "aws_access_key", "aws_secret", "aws_session", "secret_access_key",
    "mlm_license", "license_file", "ssh", "password", "token", "/home/",
    "/users/", "credential",
)


def descriptor_is_clean(descriptor: dict) -> bool:
    """True when the descriptor carries no credential-like or absolute-path
    values (a guard for the staging helper and its tests)."""
    import json

    blob = json.dumps(descriptor, sort_keys=True).lower()
    return not any(hint in blob for hint in _SECRET_HINTS)


# ── the runner ───────────────────────────────────────────────────────────
_RUNNER = r"""#!/usr/bin/env bash
# =====================================================================
# CryoStack generic cloud runner  (auto-generated -- do not edit)
# =====================================================================
set -uo pipefail

log()  { printf '[cryostack-cloud] %s\n' "$*" >&2; }
fail() { log "ERROR ($1): $2"; exit "$1"; }

: "${CRYOSTACK_S3_RUN:?CRYOSTACK_S3_RUN is required}"
: "${CRYOSTACK_MODEL:?CRYOSTACK_MODEL is required}"
RUN_TARGET="${CRYOSTACK_RUN_TARGET:-runme.m}"
WORKDIR="${CRYOSTACK_WORKDIR:-/tmp/cryostack/run}"
OUTPUTS="${WORKDIR}/outputs"

command -v aws >/dev/null 2>&1 || fail 3 "the batch container has no 'aws' CLI (needed for S3 I/O)"

# -- phase 1: fetch the staged inputs ---------------------------------
log "phase 1/3  sync  ${CRYOSTACK_S3_RUN}/input/  ->  ${WORKDIR}"
mkdir -p "${WORKDIR}" "${OUTPUTS}" || fail 4 "cannot create ${WORKDIR}"
aws s3 sync "${CRYOSTACK_S3_RUN}/input/" "${WORKDIR}/" --only-show-errors \
    || fail 4 "input sync failed"

# -- phase 2: run the model runtime (the science is never swallowed) --
cd "${WORKDIR}" || fail 5 "cannot enter ${WORKDIR}"
export ICESEE_RUN_DIR="${WORKDIR}"
log "phase 2/3  run   model=${CRYOSTACK_MODEL}  target=${RUN_TARGET}"
# captured now (staged inputs just landed) so a model-specific output
# collector can tell "staged input" from "artifact this run produced"
export CRYOSTACK_RUN_STARTED="$(date +%s)"
rc=0
case "${CRYOSTACK_MODEL}" in
  smoke)
    # license-neutral infrastructure smoke test: no model runtime, just prove
    # the container can read the staged input and write a structured output.
    log "smoke: writing outputs/metadata.json (no model runtime)"
    mkdir -p "${OUTPUTS}"
    _host="$(hostname 2>/dev/null)"; [ -n "${_host}" ] || _host="container"
    printf '{"schema":"cryostack.cloud.smoke","version":1,"ok":true,"run_target":"%s","hostname":"%s"}\n' \
      "${RUN_TARGET}" "${_host}" > "${OUTPUTS}/metadata.json"
    [ -f "${WORKDIR}/${RUN_TARGET}" ] && cp -f "${WORKDIR}/${RUN_TARGET}" "${OUTPUTS}/echoed-input.txt"
    rc=0
    ;;
  issm)
    with-issm matlab -nodesktop -nosplash -batch \
      "ICESEE_RUN_DIR='${WORKDIR}'; setenv('ICESEE_RUN_DIR','${WORKDIR}'); run('${RUN_TARGET}'); run('${WORKDIR}/postprocess_icesee.m');"
    rc=$?
    ;;
  icepack)
    # notebooks are converted to a script first (same rule as the local /
    # remote Icepack execution path in models/icepack/execution.py); a
    # single stage, no license, no MATLAB. A materialized run.py already IS
    # a script -- the *.ipynb branch only matters for a raw notebook target.
    case "${RUN_TARGET}" in
      *.ipynb)
        PY_TARGET="${RUN_TARGET%.ipynb}.py"
        with-icepack jupyter nbconvert --to script "${WORKDIR}/${RUN_TARGET}" \
          || log "WARNING: nbconvert failed; the run will fail on the missing script"
        SCRIPT="${WORKDIR}/${PY_TARGET}"
        ;;
      *)
        SCRIPT="${WORKDIR}/${RUN_TARGET}"
        ;;
    esac
    # Run through the CryoStack Icepack runner when it was staged (same
    # helper the Remote/SLURM path uses -- cryostack_src/models/icepack/
    # export.py):
    #   * forces a headless Matplotlib backend (Agg) BEFORE the script
    #     imports it -- the tutorials rely on Jupyter inline display;
    #   * persists still-open figures the script drew to
    #     outputs/figures/figure-NN.png (deterministic, de-duplicated, never
    #     by injecting savefig into the science script);
    #   * runs the allow-list structured field export (never guesses).
    # The runner exits with the SCIENCE exit code; its extra steps are
    # non-fatal. Falls back to a bare `python` if the helper wasn't staged.
    if [ -f "${WORKDIR}/__CRYOSTACK_ICEPACK_RUNNER_FILENAME__" ]; then
      with-icepack python "${WORKDIR}/__CRYOSTACK_ICEPACK_RUNNER_FILENAME__" \
        "${SCRIPT}" "${WORKDIR}"
      rc=$?
    else
      MPLBACKEND=Agg with-icepack python "${SCRIPT}"
      rc=$?
    fi
    log "icepack model runtime exit code: ${rc}"
    # Portable stdlib collector (models/icepack/postprocess.py) -- folds any
    # figures / native files into outputs/ and writes an HONEST status
    # (ok | artifacts | empty), never clobbering the exporter's richer
    # metadata. Best effort, even on a failed run (rc is never overwritten):
    # the science already happened. Staged as an ACTUAL FILE alongside
    # run.py -- NEVER embedded inline here (this whole script becomes the
    # Batch job definition's command, capped at 8192 chars on every launch).
    if [ -f "${WORKDIR}/__CRYOSTACK_ICEPACK_PP_FILENAME__" ]; then
      if command -v python3 >/dev/null 2>&1; then
        CRYOSTACK_RUN_DIR="${WORKDIR}" CRYOSTACK_EXAMPLE_DIR="${WORKDIR}" \
        python3 "${WORKDIR}/__CRYOSTACK_ICEPACK_PP_FILENAME__" \
          || log "WARNING: Icepack output collection failed (model rc=${rc})"
      else
        log "WARNING: python3 not found in the container; skipping Icepack output collection"
      fi
    else
      log "WARNING: __CRYOSTACK_ICEPACK_PP_FILENAME__ was not staged with this run's inputs; skipping Icepack output collection"
    fi
    ;;
  *)
    fail 64 "unsupported model: ${CRYOSTACK_MODEL}"
    ;;
esac
log "model runtime exit code: ${rc}"

# -- phase 3: publish outputs (best effort, even on a failed run) ----
if [ -d "${OUTPUTS}" ]; then
  log "phase 3/3  sync  ${OUTPUTS}/  ->  ${CRYOSTACK_S3_RUN}/outputs/"
  aws s3 sync "${OUTPUTS}/" "${CRYOSTACK_S3_RUN}/outputs/" --only-show-errors \
      || log "WARNING: output sync failed (model rc=${rc})"
fi

# -- phase 4: propagate the true scientific exit code --------------
exit "${rc}"
"""


#: the container-overrides / job-definition-command size limit AWS Batch
#: enforces on every job launch (it forwards the effective command through
#: an ECS RunTask override, capped the same as submit-job's own
#: --container-overrides). Kept here so tests -- and any future runner
#: change -- can assert against the real number, not a guess.
BATCH_CONTAINER_OVERRIDE_LIMIT = 8192


def build_cloud_runner() -> str:
    """The generic cloud runner script (identical for every execution mode,
    and for every model -- see this module's docstring for why NO
    model-specific helper source may be embedded here). Only the Icepack
    helper FILENAMES are substituted (a single source of truth shared with
    :func:`icepack_postprocess_extra_files`), never their source text."""
    return (
        _RUNNER
        .replace("__CRYOSTACK_ICEPACK_PP_FILENAME__", ICEPACK_POSTPROCESS_FILENAME)
        .replace("__CRYOSTACK_ICEPACK_RUNNER_FILENAME__", ICEPACK_RUNNER_FILENAME)
    )


def icepack_postprocess_extra_files() -> dict[str, str]:
    """The ``extra_files`` a cloud-run caller merges into
    ``WorkspaceManager.stage_example_for_run`` so the Icepack post-run
    helpers are staged as ordinary files alongside ``run.py`` -- the SAME
    generic mechanism ISSM's own ``postprocess_icesee.m`` already uses, and
    the SAME helper source the Remote/SLURM path stages
    (``cryostack_src.models.icepack.export``). Never embedded into the runner
    script itself (see the module docstring and
    :data:`BATCH_CONTAINER_OVERRIDE_LIMIT`).

    Three files:

    * ``cryostack_icepack_runner.py`` -- forces a headless Matplotlib
      backend, runs the science script, persists live figures, then runs the
      structured export;
    * ``cryostack_icepack_export.py`` -- the allow-list structured field
      exporter (needs Firedrake -- runs in ``with-icepack``);
    * ``cryostack_icepack_postprocess.py`` -- the stdlib collector that folds
      figures / native files into ``outputs/`` and writes an honest status.
    """
    from cryostack_src.models.icepack.export import (
        export_module_source,
        runner_module_source,
    )
    from cryostack_src.models.icepack.postprocess import build_postprocess

    return {
        ICEPACK_RUNNER_FILENAME: runner_module_source(),
        ICEPACK_EXPORT_FILENAME: export_module_source(),
        ICEPACK_POSTPROCESS_FILENAME: build_postprocess(),
    }


def cloud_run_command() -> list[str]:
    """The batch job-definition command that runs the generic runner."""
    return ["bash", "-c", build_cloud_runner()]
