# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS run diagnostics (console deep-links)
# File        : diagnostics.py
#
# Description :
#     Turn a cloud run's *persisted, non-secret* AWS resource identity into a
#     small menu of AWS console deep-links -- Batch job, container logs,
#     Fargate task, container image, S3 run storage, job queue, job
#     definition.
#
#     Two hard rules, both enforced here:
#       1. PURE. Building the menu makes NO AWS call -- not CloudWatch, not
#          Batch, not STS. It is a string transform over a dict.
#       2. NON-SECRET. ``merge_aws_resources`` drops anything that looks like
#          a credential / token / ExternalId before it is ever persisted.
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""Non-secret AWS resource snapshot + console-link menu for a cloud run.

The snapshot (``metadata["aws_resources"]`` on a run) is built INCREMENTALLY:
the fields known at submit are seeded immediately, and each normal
``DescribeJobs`` poll folds in whatever it newly reveals (log stream, ECS
task ARN, resolved queue / job-definition ARNs, container image). The menu is
therefore useful for a *running* job, not only a terminal one.

A historical run renders its menu from ITS OWN persisted snapshot -- never
from the current Cloud Environment defaults.
"""
from __future__ import annotations

from urllib.parse import quote

# ---------------------------------------------------------------------------
# what may NOT be persisted
# ---------------------------------------------------------------------------
#: any resource key whose lowercased name contains one of these is dropped by
#: merge_aws_resources -- a defence-in-depth guard so a future caller cannot
#: accidentally persist credential material under metadata["aws_resources"].
_SECRET_KEY_HINTS: tuple[str, ...] = (
    "secret", "token", "session", "credential", "password", "passwd",
    "externalid", "external_id", "access_key", "accesskey", "authorization",
    "private", "signature",
)

#: the identity fields a run's snapshot may carry. Everything else is ignored.
_ALLOWED_KEYS: frozenset[str] = frozenset({
    "region", "account_id",
    "batch_job_id", "job_name",
    "job_queue", "job_definition",
    "log_group", "log_stream",
    "task_arn",
    "image", "image_reference", "image_digest", "image_public_url",
    "s3_run",
})

DEFAULT_LOG_GROUP = "/aws/batch/job"


def _is_secretish(key: str) -> bool:
    k = (key or "").strip().lower()
    return any(hint in k for hint in _SECRET_KEY_HINTS)


def merge_aws_resources(existing: dict | None, updates: dict | None) -> dict:
    """Merge ``updates`` into ``existing`` and return a NEW dict.

    * only :data:`_ALLOWED_KEYS` survive;
    * a secret-looking key is dropped even if it is on the allow-list-adjacent
      path (defence in depth);
    * empty / ``None`` values never overwrite a value already known;
    * values are coerced to ``str`` and stripped.

    Idempotent and monotonic: calling it again with the same (or a subset of
    the same) ``updates`` returns an equal dict.
    """
    out: dict[str, str] = {}
    for src in (existing or {}, updates or {}):
        if not isinstance(src, dict):
            continue
        for key, value in src.items():
            if key not in _ALLOWED_KEYS or _is_secretish(key):
                continue
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            out[key] = text
    return out


def resources_from_poll(status_metadata: dict | None) -> dict:
    """Extract the non-secret resource identity a ``DescribeJobs`` poll
    reveals (``CloudBackend.status``'s ``metadata``). Missing keys are simply
    absent -- the caller merges, so a partial poll grows the snapshot."""
    m = status_metadata or {}
    picked = {
        "region": m.get("region"),
        "log_stream": m.get("log_stream"),
        "log_group": m.get("log_group") or (DEFAULT_LOG_GROUP if m.get("log_stream") else None),
        "job_queue": m.get("job_queue"),
        "job_definition": m.get("job_definition"),
        "task_arn": m.get("task_arn"),
        "image": m.get("image"),
    }
    return {k: v for k, v in picked.items() if v}


# ---------------------------------------------------------------------------
# console deep-links  (pure -- NO AWS call)
# ---------------------------------------------------------------------------
def _q(value: str) -> str:
    return quote(str(value or ""), safe="")


def _cw(value: str) -> str:
    """CloudWatch console path segment encoding (``/`` -> ``$252F`` etc.)."""
    return quote(str(value or ""), safe="").replace("%", "$25")


def _batch_home(region: str) -> str:
    return (f"https://{region}.console.aws.amazon.com/batch/home"
            f"?region={_q(region)}")


def _looks_like_arn(value: str) -> bool:
    return str(value or "").startswith("arn:aws:")


def _split_s3(uri: str) -> tuple[str, str]:
    body = str(uri or "")[5:] if str(uri or "").startswith("s3://") else ""
    bucket, _, prefix = body.partition("/")
    return bucket, prefix.rstrip("/")


def _split_task_arn(arn: str) -> tuple[str, str]:
    """``arn:aws:ecs:r:a:task/<cluster>/<id>`` or ``.../task/<id>`` ->
    ``(cluster, task_id)``; ``cluster`` may be ``""`` (old ARN format)."""
    tail = str(arn or "").split(":task/", 1)[-1]
    parts = [p for p in tail.split("/") if p]
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    if len(parts) == 1:
        return "", parts[0]
    return "", ""


def _link(label: str, url: str, detail: str = "") -> dict:
    return {"label": label, "url": url, "detail": detail}


def aws_console_links(resources: dict | None) -> list[dict]:
    """The AWS diagnostics menu for a run, as ``[{label, url, detail}]`` in a
    stable order. PURE -- no AWS call. Only entries whose backing resource is
    present in ``resources`` are returned, so a running job whose task ARN is
    not known yet simply has no "Fargate task" entry (yet).

    Labels are exactly, and only: Batch job, Container logs, Fargate task,
    Container image, S3 run storage, Job queue, Job definition.
    """
    r = merge_aws_resources({}, resources)      # normalise + drop anything odd
    region = r.get("region") or ""
    links: list[dict] = []

    job_id = r.get("batch_job_id")
    if region and job_id:
        links.append(_link(
            "Batch job", f"{_batch_home(region)}#jobs/detail/{_q(job_id)}", job_id))

    stream = r.get("log_stream")
    group = r.get("log_group") or (DEFAULT_LOG_GROUP if stream else "")
    if region and group and stream:
        links.append(_link(
            "Container logs",
            (f"https://{region}.console.aws.amazon.com/cloudwatch/home"
             f"?region={_q(region)}#logsV2:log-groups/log-group/{_cw(group)}"
             f"/log-events/{_cw(stream)}"),
            stream))

    task_arn = r.get("task_arn")
    if region and task_arn:
        cluster, task_id = _split_task_arn(task_arn)
        if task_id:
            base = (f"https://{region}.console.aws.amazon.com/ecs/v2"
                    f"/clusters/{_q(cluster or 'default')}/tasks/{_q(task_id)}")
            links.append(_link("Fargate task",
                               f"{base}/configuration?region={_q(region)}", task_id))

    img_url = r.get("image_public_url")
    image = r.get("image") or ""
    if img_url:
        links.append(_link("Container image", img_url,
                           r.get("image_reference") or r.get("image_digest") or ""))
    elif region and "dkr.ecr." in image:
        # <acct>.dkr.ecr.<r>.amazonaws.com/<repo>[@sha256:..|:tag]
        host, _, path = image.partition("/")
        acct = host.split(".", 1)[0]
        repo = path.split("@", 1)[0].split(":", 1)[0]
        digest = path.split("@", 1)[1] if "@" in path else ""
        url = (f"https://{region}.console.aws.amazon.com/ecr/repositories/private"
               f"/{_q(acct)}/{_q(repo)}?region={_q(region)}")
        if digest:
            url = (f"https://{region}.console.aws.amazon.com/ecr/repositories/private"
                   f"/{_q(acct)}/{_q(repo)}/_/image/{_q(digest)}/details"
                   f"?region={_q(region)}")
        links.append(_link("Container image", url, image))

    s3_run = r.get("s3_run")
    if region and s3_run:
        bucket, prefix = _split_s3(s3_run)
        if bucket:
            url = (f"https://{region}.console.aws.amazon.com/s3/buckets/{_q(bucket)}"
                   f"?region={_q(region)}")
            if prefix:
                url += f"&prefix={_q(prefix + '/')}"
            links.append(_link("S3 run storage", url, s3_run))

    queue = r.get("job_queue")
    if region and queue:
        if _looks_like_arn(queue):
            url = f"{_batch_home(region)}#queues/detail/{_q(queue)}"
        else:
            url = f"{_batch_home(region)}#queues"
        links.append(_link("Job queue", url, queue.rsplit("/", 1)[-1]))

    jobdef = r.get("job_definition")
    if region and jobdef:
        if _looks_like_arn(jobdef):
            url = f"{_batch_home(region)}#job-definition/detail/{_q(jobdef)}"
        else:
            url = f"{_batch_home(region)}#job-definition"
        links.append(_link("Job definition", url, jobdef.rsplit("/", 1)[-1]))

    return links


def has_diagnostics(resources: dict | None) -> bool:
    """True when at least one console link can be built (a menu is worth
    showing)."""
    return bool(aws_console_links(resources))
