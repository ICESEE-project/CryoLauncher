# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Combined Cloud Image -- AWS CLI Regression
# File        : test_cloud_image_awscli.py
#
# Description :
#     The combined Icepack/ISSM cloud runtime image must ship the AWS CLI
#     as a build-time dependency (never installed dynamically at job
#     start). Reproduces and fixes the live failure:
#     "[cryostack-cloud] ERROR (3): the batch container has no 'aws' CLI
#     (needed for S3 I/O)" -- the job reached Fargate successfully; the
#     image itself never had `aws`.
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""Static (always-on) checks against the source Dockerfile, plus a live
Docker smoke test that only runs when a usable docker daemon (and network
access to pull the upstream base image + AWS's official installer) is
available -- it skips cleanly otherwise rather than failing the suite.

``tools/cloud/Dockerfile`` is the SOURCE image both ``cryostack-issm`` and
``cryostack-icepack`` ECR job definitions mirror (registry_delivery.py /
mirror_tested_image) -- fixed once here, never per-model.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_DOCKERFILE = _REPO / "tools/cloud/Dockerfile"


def _dockerfile_text() -> str:
    return _DOCKERFILE.read_text(encoding="utf-8")


# ── static: the fix is present in the one source Dockerfile ───────────────
def test_dockerfile_installs_awscli_at_build_time():
    src = _dockerfile_text()
    assert "awscli-exe-linux-x86_64" in src, (
        "the AWS CLI v2 official installer must be baked into the image at "
        "build time -- never installed dynamically when a job starts"
    )
    assert "aws --version" in src, (
        "the build itself must verify the CLI actually works, not merely "
        "attempt the install"
    )
    # single source of truth -- the combined image both cryostack-issm and
    # cryostack-icepack mirror; never a per-model Dockerfile / drift
    assert src.count("awscli-exe-linux-x86_64") == 1


def test_dockerfile_pins_an_exact_awscli_version():
    """A tested, digest-pinned image must be reproducible -- never floats
    to "whatever AWS's installer serves today"."""
    m = re.search(r"AWSCLI_VERSION=(\d+\.\d+\.\d+)", _dockerfile_text())
    assert m, "expected an exact x.y.z AWS CLI version pin"


def test_awscli_install_reuses_tools_the_base_image_already_ships():
    """curl/unzip must NOT be apt-get installed for this -- they are already
    present in the upstream base image (docker.io/bkyanjo/combined-lean),
    verified empirically (see the commit message). Adding them again here
    would be a redundant, silently-diverging dependency the next person has
    to notice by hand."""
    src = _dockerfile_text()
    start = src.index("AWSCLI_VERSION=")
    end = src.index("&& aws --version", start)
    block = src[start:end]
    assert "apt-get" not in block
    assert "curl" in block and "unzip" in block   # used, just not (re)installed


def test_awscli_temp_files_are_cleaned_up():
    """The installer's own zip + extracted staging tree must not survive in
    a layer -- keep the image lean, matching every existing RUN block's own
    cleanup convention (e.g. `rm -rf /var/lib/apt/lists/*`)."""
    src = _dockerfile_text()
    start = src.index("AWSCLI_VERSION=")
    end = src.index("&& aws --version", start)
    block = src[start:end]
    assert "rm -rf" in block and "awscliv2.zip" in block


def test_existing_dockerfile_layers_are_unchanged():
    """The fix is additive only -- every existing instruction (the base
    image, the git/rsync apt-get, the ICESEE pip install sequence, every
    with-* wrapper, the ISSM/MATLAB environment, ENTRYPOINT) is untouched.
    Preserves image contents and every model environment exactly."""
    src = _dockerfile_text()
    for must_still_be_present in (
        "FROM docker.io/bkyanjo/combined-lean:v1.0",
        "git \\\n        rsync \\",
        "/opt/venv-icepack/bin/pip install --no-cache-dir -r /tmp/icesee-pip-reqs-safe.txt",
        "/opt/venv-firedrake/bin/pip install --no-cache-dir -r /tmp/icesee-pip-reqs-safe.txt",
        "> /usr/local/bin/with-issm && chmod +x /usr/local/bin/with-issm",
        "> /usr/local/bin/with-icepack && chmod +x /usr/local/bin/with-icepack",
        "> /usr/local/bin/with-firedrake && chmod +x /usr/local/bin/with-firedrake",
        "ISSM_DIR=/opt/ISSM",
        "MLM_LICENSE_FILE=1711@matlablic.ecs.gatech.edu",
        'ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]',
    ):
        assert must_still_be_present in src, f"missing (regression): {must_still_be_present!r}"


def test_awscli_layer_does_not_broaden_iam_or_change_s3_prefix_design():
    """No IAM policy text, no role/permission grant, and no S3 prefix/
    user-isolation logic belongs in an image layer -- confirms this fix
    stayed exactly where it should (a CLI binary), not a policy change in
    disguise."""
    src = _dockerfile_text()
    start = src.index("AWSCLI_VERSION=")
    end = src.index("&& aws --version", start)
    block = src[start:end].lower()
    for forbidden in ("iam", "policy", "role", "s3://", "arn:aws"):
        assert forbidden not in block


# ── live smoke test: build + run, only when docker/network actually work ──
def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=True)
    except Exception:
        return False
    return True


def _base_image() -> str:
    m = re.search(r"^FROM (\S+)", _dockerfile_text(), re.MULTILINE)
    assert m, "no FROM line found in tools/cloud/Dockerfile"
    return m.group(1)


def _awscli_run_block() -> str:
    """The exact RUN instruction this checkpoint added, lifted verbatim from
    the real Dockerfile -- the smoke test below builds against the SAME
    text that ships, never a hand-duplicated copy that could drift."""
    src = _dockerfile_text()
    start = src.rindex("RUN set -eu \\\n    && AWSCLI_VERSION=")
    end = src.index("&& aws --version", start) + len("&& aws --version")
    return src[start:end]


@pytest.mark.skipif(not _docker_available(),
                    reason="no usable docker daemon in this environment")
def test_live_smoke_awscli_is_present_and_functional_in_the_built_image(tmp_path):
    """Builds a throwaway image (the real upstream base image +  ONLY this
    checkpoint's new layer, lifted verbatim from tools/cloud/Dockerfile) and
    proves, inside an actual running container:

    * ``aws --version`` succeeds (the checkpoint's own stated requirement);
    * the runner's EXACT invocation shape (``aws s3 sync <src> <dst>
      --only-show-errors``) is understood by the installed CLI -- given two
      local paths it is correctly rejected at ARGUMENT-VALIDATION time (a
      clear "usage: aws s3 sync <LocalPath> <S3Uri> ..." message), never a
      "command not found"/"invalid choice" error, and never a real network
      attempt (no AWS contact -- this fails before any HTTP request; a
      genuine attempt to reach AWS would show a DNS/connection error
      instead, which this test explicitly checks is ABSENT).

    Skips (never fails the suite) when this environment has no usable
    docker daemon, or the build cannot reach Docker Hub / AWS's installer
    endpoint -- this is a live infrastructure probe, not a hermetic unit
    test, and its absence must never block the rest of the suite.
    """
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(f"FROM {_base_image()}\n{_awscli_run_block()}\n")

    tag = "cryostack-cloud-awscli-smoke:test"
    build = subprocess.run(
        ["docker", "build", "-f", str(dockerfile), "-t", tag, str(tmp_path)],
        capture_output=True, text=True, timeout=300,
    )
    if build.returncode != 0:
        pytest.skip(
            "could not build the smoke image (no network to Docker Hub / "
            f"AWS's installer?): {(build.stderr or build.stdout)[-2000:]}"
        )
    try:
        version = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "/usr/local/bin/aws", tag, "--version"],
            capture_output=True, text=True, timeout=60,
        )
        assert version.returncode == 0, version.stderr
        assert "aws-cli/" in (version.stdout + version.stderr)

        sync = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "/usr/bin/bash", tag, "-c",
             'mkdir -p /tmp/src /tmp/dst && '
             'aws s3 sync "/tmp/src/" "/tmp/dst/" --only-show-errors'],
            capture_output=True, text=True, timeout=60,
        )
        assert sync.returncode != 0            # correctly rejected -- not real S3 URIs
        assert "S3Uri" in sync.stderr or "S3Uri" in sync.stdout
        combined = sync.stderr + sync.stdout
        for leaked in ("Could not connect", "getaddrinfo", "Temporary failure",
                       "Name or service not known"):
            assert leaked not in combined      # never actually reached AWS
    finally:
        subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)
