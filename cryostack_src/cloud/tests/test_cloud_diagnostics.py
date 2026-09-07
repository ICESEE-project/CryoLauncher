"""AWS run-diagnostics menu: non-secret resource snapshot + pure console links.

Two invariants, both proven here: (1) building the menu makes NO AWS call --
it is a string transform; (2) nothing credential-like is ever persisted.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.diagnostics import (
    aws_console_links,
    has_diagnostics,
    merge_aws_resources,
    resources_from_poll,
)

_SEED = {
    "region": "us-east-2",
    "account_id": "774888247882",
    "batch_job_id": "1ebd6f32-0f69-407c-a931-6b1f1490fb8a",
    "job_queue": "cryostack-queue",
    "job_definition": "cryostack-icepack:3",
    "s3_run": "s3://cryostack-runs-774888247882/runs/alice/run-1",
    "image_reference": "bkyanjo/icesee-combined:v1.0.1",
    "image_digest": "sha256:" + "e" * 64,
}


# ── merge: allow-list + secret guard + monotonic ────────────────────────
def test_merge_keeps_only_non_secret_identity():
    dirty = {
        **_SEED,
        "AWS_SESSION_TOKEN": "FQoGZ...", "aws_secret_access_key": "abc",
        "ExternalId": "cryostack:alice:xyz", "external_id": "cryostack:alice:xyz",
        "credentials": {"AWS_ACCESS_KEY_ID": "ASIA"}, "authorization": "Bearer x",
        "some_unknown_key": "whatever",
    }
    out = merge_aws_resources({}, dirty)
    assert out == _SEED                                  # exactly the allow-list survives
    for banned in ("AWS_SESSION_TOKEN", "aws_secret_access_key", "ExternalId",
                   "external_id", "credentials", "authorization", "some_unknown_key"):
        assert banned not in out
    assert "ASIA" not in str(out) and "cryostack:alice" not in str(out)


def test_merge_is_monotonic_and_never_overwrites_with_empty():
    base = merge_aws_resources({}, _SEED)
    assert merge_aws_resources(base, {}) == base
    assert merge_aws_resources(base, {"log_stream": ""}) == base           # empty ignored
    grown = merge_aws_resources(base, {"log_stream": "cryostack/x/abc"})
    assert grown["log_stream"] == "cryostack/x/abc"
    assert {k: grown[k] for k in base} == base                             # existing intact
    # a later poll that lacks a field does not erase it
    assert merge_aws_resources(grown, {"region": "us-east-2"}) == grown


def test_resources_from_poll_extracts_incrementally_revealed_identity():
    picked = resources_from_poll({
        "provider": "aws", "region": "us-east-2",
        "log_stream": "cryostack-icepack/default/abc",
        "job_queue": "arn:aws:batch:us-east-2:774888247882:job-queue/cryostack-queue",
        "job_definition": "arn:aws:batch:us-east-2:774888247882:job-definition/cryostack-icepack:3",
        "task_arn": "arn:aws:ecs:us-east-2:774888247882:task/AWSBatch-ce/deadbeef01",
        "image": "774888247882.dkr.ecr.us-east-2.amazonaws.com/cryostack-icepack@sha256:abc",
        "created_at": 123, "stopped_at": None,
    })
    assert picked["log_stream"] == "cryostack-icepack/default/abc"
    assert picked["log_group"] == "/aws/batch/job"          # default when a stream exists
    assert picked["task_arn"].endswith("deadbeef01")
    assert "created_at" not in picked and "provider" not in picked
    # a poll before the container exists yields nothing to add
    assert resources_from_poll({"region": "us-east-2"}) == {"region": "us-east-2"}
    assert resources_from_poll({}) == {}


# ── console links: pure, ordered, partial-aware ─────────────────────────
def test_seed_only_snapshot_still_gives_a_useful_menu():
    labels = [x["label"] for x in aws_console_links(_SEED)]
    # image_public_url absent -> the ECR image ref itself is not linkable here
    assert labels == ["Batch job", "S3 run storage", "Job queue", "Job definition"]
    assert has_diagnostics(_SEED)
    assert not has_diagnostics({})
    assert not has_diagnostics({"region": "us-east-2"})       # nothing to link yet


def test_running_job_menu_grows_as_polling_reveals_resources():
    snap = merge_aws_resources(_SEED, resources_from_poll({
        "region": "us-east-2",
        "log_stream": "cryostack-icepack/default/abc",
        "task_arn": "arn:aws:ecs:us-east-2:774888247882:task/AWSBatch-ce/deadbeef01",
    }))
    labels = [x["label"] for x in aws_console_links(snap)]
    assert labels == ["Batch job", "Container logs", "Fargate task",
                      "S3 run storage", "Job queue", "Job definition"]
    by = {x["label"]: x["url"] for x in aws_console_links(snap)}
    assert by["Batch job"].endswith("#jobs/detail/1ebd6f32-0f69-407c-a931-6b1f1490fb8a")
    assert "cloudwatch/home" in by["Container logs"]
    assert "$252F" in by["Container logs"]                    # / encoded for CloudWatch
    assert "/clusters/AWSBatch-ce/tasks/deadbeef01" in by["Fargate task"]
    assert by["S3 run storage"].startswith(
        "https://us-east-2.console.aws.amazon.com/s3/buckets/cryostack-runs-774888247882")
    assert "prefix=runs%2Falice%2Frun-1%2F" in by["S3 run storage"]


def test_labels_are_exactly_the_seven_agreed_labels():
    full = merge_aws_resources(_SEED, {
        "log_stream": "s", "task_arn": "arn:aws:ecs:us-east-2:1:task/c/t",
        "image_public_url": "https://hub.docker.com/r/bkyanjo/icesee-combined/tags?name=v1.0.1",
    })
    got = {x["label"] for x in aws_console_links(full)}
    assert got == {"Batch job", "Container logs", "Fargate task", "Container image",
                   "S3 run storage", "Job queue", "Job definition"}


def test_container_image_prefers_the_public_docker_hub_link():
    snap = merge_aws_resources(_SEED, {
        "image_public_url": "https://hub.docker.com/r/bkyanjo/icesee-combined/tags?name=v1.0.1",
    })
    img = next(x for x in aws_console_links(snap) if x["label"] == "Container image")
    assert img["url"] == "https://hub.docker.com/r/bkyanjo/icesee-combined/tags?name=v1.0.1"


def test_historical_snapshot_links_are_independent_of_any_current_default():
    # a run recorded in a DIFFERENT region / account must link to its own
    old = {
        "region": "eu-west-1", "account_id": "111111111111",
        "batch_job_id": "old-job", "s3_run": "s3://old-bucket/runs/bob/r0",
    }
    urls = " ".join(x["url"] for x in aws_console_links(old))
    assert "eu-west-1" in urls and "us-east-2" not in urls
    assert "old-bucket" in urls


def test_no_network_module_is_imported():
    import cryostack_src.cloud.diagnostics as d
    src = Path(d.__file__).read_text()
    for banned in ("requests", "boto3", "botocore", "urllib.request",
                   "run_aws", "subprocess", "socket"):
        assert banned not in src
