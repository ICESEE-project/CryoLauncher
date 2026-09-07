"""Manifest schema v2: reproducibility provenance (container + software).

v1 manifests must keep loading with empty provenance; v2 must round-trip
exactly. The manifest ``software``/``container`` block is authoritative — the
Slurm ``[stack]`` line is derived from that same block.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.models.stack import resolve_stack, stack_log_line
from cryostack_src.workspace.manifest import (
    MANIFEST_NAME,
    SCHEMA,
    VERSION,
    read_manifest,
    write_manifest,
)
from cryostack_src.workspace.models import RunInfo


def _run(workspace: Path, **over) -> RunInfo:
    base = dict(
        id="run-1", name="run-1", model="issm", backend="container",
        execution_mode="remote", status="running", created=datetime(2026, 8, 28, 12, 0, 0),
        jobid="12451829", remote_directory=Path("/scratch/run-1"),
        workspace_directory=workspace,
    )
    base.update(over)
    return RunInfo(**base)


def _write_v1(dir_: Path) -> Path:
    """A hand-built pre-provenance manifest exactly as v1 wrote it."""
    dir_.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "version": 1,
        "run": {
            "id": "legacy-1", "name": "legacy-1", "model": "issm",
            "backend": "container", "execution_mode": "remote", "status": "completed",
            "job_id": "999", "created": "2026-08-01T09:00:00", "finished": None,
            "workspace": str(dir_.resolve()),
            "remote_directory": "/scratch/legacy", "results_directory": None,
            "figures_directory": None, "log_file": None,
            "command": "", "notes": "", "metadata": {"host": "hpc"},
        },
    }
    p = dir_ / MANIFEST_NAME
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


# ── v1 backward compatibility ──────────────────────────────────────────────
def test_v1_manifest_reads_with_empty_provenance(tmp_path):
    p = _write_v1(tmp_path / "legacy-1")
    run = read_manifest(p)
    assert run.id == "legacy-1"
    assert run.metadata == {"host": "hpc"}
    assert run.container == {}
    assert run.software == {}


def test_v1_manifest_is_not_rewritten_on_read(tmp_path):
    p = _write_v1(tmp_path / "legacy-1")
    before = p.read_text()
    read_manifest(p)
    assert p.read_text() == before          # untouched
    assert json.loads(before)["version"] == 1


def test_writer_now_emits_version_2(tmp_path):
    ws = tmp_path / "run-1"
    write_manifest(_run(ws), ws)
    payload = json.loads((ws / MANIFEST_NAME).read_text())
    assert payload["version"] == VERSION == 2
    assert payload["run"]["container"] == {}
    assert payload["run"]["software"] == {}


# ── v2 exact round trip ────────────────────────────────────────────────────
def test_v2_round_trip_preserves_provenance(tmp_path):
    ws = tmp_path / "run-1"
    prov = resolve_stack(
        model="issm", profile="tested", selections=None,
        container_source="git", image_uri="",
    )
    run = _run(ws, container=prov["container"], software=prov["software"])
    write_manifest(run, ws)
    back = read_manifest(ws / MANIFEST_NAME)
    assert back.container == prov["container"]
    assert back.software == prov["software"]


# ── tested ISSM stack ──────────────────────────────────────────────────────
def test_tested_issm_stack_persists_issm_and_icesee_image_provenance(tmp_path):
    ws = tmp_path / "run-1"
    prov = resolve_stack(model="issm", profile="tested", selections=None,
                         container_source="git", image_uri="")
    write_manifest(_run(ws, container=prov["container"], software=prov["software"]), ws)
    sw = read_manifest(ws / MANIFEST_NAME).software

    assert set(sw) == {"issm", "icesee"}
    assert sw["issm"] == {
        "source": "image",
        "requested_ref": None,
        "resolved_commit": "e70338d8685f8582b61958211e8f5fce2ea686ff",
        "version": "2026.1 (self-reported)",
        "source_ref": "main snapshot",
        "repository": "https://github.com/ISSMteam/ISSM.git",
        "resolved_via": "image",
    }
    assert sw["icesee"]["source"] == "image"
    assert sw["icesee"]["resolved_commit"] is None
    assert sw["icesee"]["commit_status"] == "unknown-until-image-inspected"
    assert sw["icesee"]["version"] == "0.1.9"


# ── tested Icepack stack ───────────────────────────────────────────────────
def test_tested_icepack_stack_persists_icepack_firedrake_icesee(tmp_path):
    ws = tmp_path / "run-2"
    prov = resolve_stack(model="icepack", profile="tested", selections=None,
                         container_source="git", image_uri="")
    write_manifest(_run(ws, model="icepack",
                        container=prov["container"], software=prov["software"]), ws)
    sw = read_manifest(ws / MANIFEST_NAME).software

    assert set(sw) == {"icepack", "firedrake", "icesee"}
    assert all(v["source"] == "image" for v in sw.values())
    assert sw["firedrake"]["version"] == "2025.10.2"
    assert sw["firedrake"]["resolved_commit"] is None
    assert sw["icepack"]["resolved_commit"] is None


# ── container identity in the reproducibility contract ────────────────────
def test_oci_tag_without_digest_resolution_is_marked_unresolved(tmp_path):
    ws = tmp_path / "run-3"
    prov = resolve_stack(
        model="issm", profile="tested", selections=None,
        container_source="docker", image_uri="bkyanjo/icesee-combined:v1.0.0",
        digest_resolver=None,
    )
    write_manifest(_run(ws, container=prov["container"], software=prov["software"]), ws)
    c = read_manifest(ws / MANIFEST_NAME).container

    assert c["source"] == "docker"
    assert c["digest"] is None
    assert c["build_provenance"]["digest_status"] == "unresolved"
    assert c["build_provenance"]["requested_tag"] == "v1.0.0"


def test_resolved_oci_digest_is_preserved_exactly(tmp_path):
    ws = tmp_path / "run-4"
    digest = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
    prov = resolve_stack(
        model="issm", profile="tested", selections=None,
        container_source="docker", image_uri="ghcr.io/x/icesee-combined@" + digest,
        digest_resolver=lambda ref: digest,
    )
    write_manifest(_run(ws, container=prov["container"], software=prov["software"]), ws)
    c = read_manifest(ws / MANIFEST_NAME).container
    assert c["digest"] == digest


def test_git_container_keeps_immutable_build_inputs(tmp_path):
    ws = tmp_path / "run-5"
    prov = resolve_stack(model="issm", profile="tested", selections=None,
                         container_source="git", image_uri="")
    write_manifest(_run(ws, container=prov["container"], software=prov["software"]), ws)
    bp = read_manifest(ws / MANIFEST_NAME).container["build_provenance"]
    assert bp["base_image"] == "docker.io/bkyanjo/combined-lean:v1.0"
    assert bp["base_image_digest"].startswith("sha256:e2dc1c0d")


# ── the [stack] line derives from the same provenance block ───────────────
def test_stack_log_line_is_a_pure_function_of_the_persisted_block(tmp_path):
    ws = tmp_path / "run-6"
    prov = resolve_stack(model="issm", profile="tested", selections=None,
                         container_source="git", image_uri="")
    write_manifest(_run(ws, container=prov["container"], software=prov["software"]), ws)
    back = read_manifest(ws / MANIFEST_NAME)

    # rebuilding from the persisted manifest yields the identical line
    rebuilt = {"profile": prov["profile"], "container": back.container, "software": back.software}
    assert stack_log_line(rebuilt) == stack_log_line(prov)
    assert stack_log_line(rebuilt).startswith("[stack] tested")
    assert "issm=image" in stack_log_line(rebuilt)
    assert "@e70338d8685f" in stack_log_line(rebuilt)


# ── unsupported schema still rejected ────────────────────────────────────
def test_unknown_schema_version_still_rejected(tmp_path):
    d = tmp_path / "bad"
    d.mkdir()
    (d / MANIFEST_NAME).write_text(json.dumps({
        "schema": SCHEMA, "version": 99,
        "run": {"id": "x", "workspace": str(d.resolve())},
    }))
    with pytest.raises(ValueError):
        read_manifest(d / MANIFEST_NAME)


# ── a cloud run manifest carries the full non-secret identity ────────────
def test_cloud_run_manifest_round_trips_provider_and_experiment_identity(tmp_path):
    """Phase 5: Runs / Files / Run Log / Results describe the SAME persisted
    run -- so the manifest must carry, non-secret, everything the four tabs
    and the history card show for a completed cloud run."""
    ws = tmp_path / "cloud-run"
    prov = resolve_stack(model="icepack", profile="tested", selections=None,
                         container_source="docker", image_uri="",
                         tested_image_key="icesee-combined-v1.0.1")
    run = _run(
        ws, id="cloud-1", name="cloud-1", model="icepack", backend="aws",
        execution_mode="cloud", status="completed", jobid="1ebd6f32-0f69",
        remote_directory=Path("s3://cryostack-runs-774888247882/runs/u/x"),
        container=prov["container"], software=prov["software"],
        metadata={
            "provider": "aws", "region": "us-east-2",
            "account_id": "774888247882",
            "example": "00-meshes-functions",
            "source": "00-meshes-functions.ipynb",
            "run_target": "run.py",
            "job_queue": "cryostack-queue", "job_definition": "cryostack-icepack",
            "image_reference": "bkyanjo/icesee-combined:v1.0.1",
            "image_digest": prov["container"]["digest"],
            "aws_resources": {"job_id": "1ebd6f32-0f69", "region": "us-east-2",
                              "log_group": "/aws/batch/job",
                              "s3_run": "s3://cryostack-runs-774888247882/runs/u/x"},
        },
    )
    write_manifest(run, ws)
    back = read_manifest(ws / MANIFEST_NAME)

    assert back.model == "icepack" and back.backend == "aws"
    assert back.execution_mode == "cloud" and back.jobid == "1ebd6f32-0f69"
    md = back.metadata
    # experiment identity -- distinct source vs run target
    assert md["example"] == "00-meshes-functions"
    assert md["source"] == "00-meshes-functions.ipynb" and md["run_target"] == "run.py"
    # provider identity
    assert md["provider"] == "aws" and md["job_queue"] == "cryostack-queue"
    # container identity: the reused schema, digest frozen
    assert back.container["source"] == "docker"
    assert back.container["digest"] == prov["container"]["digest"]
    assert back.container["build_provenance"]["tested_image"] == "icesee-combined-v1.0.1"
    assert back.software                                   # per-component provenance
    # AWS diagnostics identity (non-secret) survives the round trip
    assert md["aws_resources"]["job_id"] == "1ebd6f32-0f69"
    # NEVER a secret / credential / ExternalId
    blob = json.dumps({"metadata": md, "container": back.container,
                       "software": back.software})
    for forbidden in ("AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "ExternalId",
                      "MLM_LICENSE_FILE=", "@matlablic"):
        assert forbidden not in blob
