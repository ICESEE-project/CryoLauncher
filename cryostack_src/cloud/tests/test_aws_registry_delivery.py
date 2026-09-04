"""Cloud Commit 2 -- tested-image delivery into ECR and digest pinning.

All ECR / registry operations are mocked; no image is transferred and no AWS
resource is created. The transfer itself is an injected ``copier``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.cloud.drivers.aws import registry_delivery as rd
from cryostack_src.cloud.drivers.aws import registry_provision as rp
from cryostack_src.cloud.drivers.aws.models import AWSConfig
from cryostack_src.cloud.drivers.aws.registry_delivery import (
    ECRImageDelivery,
    RegistryDeliveryError,
    ecr_repository_name,
    mirror_tested_image,
)
from cryostack_src.cloud.drivers.aws.registry_delivery import (
    tested_image_for_model as _resolve_tested_image,
)

CONFIG = AWSConfig(region="us-east-2")
REPO = "cryostack-issm"
URI = "111111111111.dkr.ecr.us-east-2.amazonaws.com/cryostack-issm"
# v1.0.1 is the current default tested image (adds the AWS CLI for cloud
# S3 sync -- see cryostack_src/cloud/tests/test_cloud_image_awscli.py and
# tools/cloud/Dockerfile); v1.0.0 stays registered (test_tested_images.py)
# but is no longer what tested_image_for_model() resolves to.
SOURCE_REF = "bkyanjo/icesee-combined:v1.0.1"
SOURCE_DIGEST = "sha256:e393b1eed21f3481fffcfb3bb7ce5ce315fbff0cc8dc0fe4f2bcc2e2f1d538ed"
SRC_TAG = "src-e393b1eed21f3481"


class FakeECR:
    def __init__(self):
        self.calls: list[list[str]] = []
        self.repos: dict[str, dict] = {}
        self.images: dict[str, list[dict]] = {}
        self.manifests: dict[tuple[str, str], str] = {}
        self.lifecycle: dict[str, str] = {}

    # -- seeding ----------------------------------------------------
    def add_repo(self, name=REPO, uri=URI):
        self.repos[name] = {"repositoryName": name, "repositoryUri": uri}
        self.images.setdefault(name, [])

    def add_image(self, repo, digest, tags, *, arch="amd64",
                  media="application/vnd.oci.image.index.v1+json", manifest=None):
        manifest = manifest or json.dumps({"digest": digest})
        self.images.setdefault(repo, []).append({
            "imageDigest": digest, "imageTags": list(tags),
            "imageManifestMediaType": media, "imageArchitecture": arch,
        })
        self.manifests[(repo, digest)] = manifest

    def tags_of(self, repo, digest):
        for i in self.images.get(repo, []):
            if i["imageDigest"] == digest:
                return set(i["imageTags"])
        return set()

    def digest_of_tag(self, repo, tag):
        for i in self.images.get(repo, []):
            if tag in i["imageTags"]:
                return i["imageDigest"]
        return None

    def count(self, *prefix):
        p = list(prefix)
        return sum(1 for c in self.calls if c[: len(p)] == p)

    # -- the run_aws stand-in -------------------------------------
    def __call__(self, config, args):
        a = list(args)
        self.calls.append(a)

        def opt(name):
            return a[a.index(name) + 1]

        if a[:2] == ["ecr", "describe-repositories"]:
            if "--repository-names" in a:
                n = opt("--repository-names")
                if n in self.repos:
                    return (0, json.dumps({"repositories": [self.repos[n]]}), "")
                return (254, "", "An error occurred (RepositoryNotFoundException)")
            return (0, json.dumps({"repositories": list(self.repos.values())}), "")

        if a[:2] == ["ecr", "create-repository"]:
            n = opt("--repository-name")
            self.add_repo(n, f"111111111111.dkr.ecr.us-east-2.amazonaws.com/{n}")
            return (0, json.dumps({"repository": self.repos[n]}), "")

        if a[:2] == ["ecr", "get-lifecycle-policy"]:
            n = opt("--repository-name")
            if n in self.lifecycle:
                return (0, json.dumps({"lifecyclePolicyText": self.lifecycle[n]}), "")
            return (254, "", "An error occurred (LifecyclePolicyNotFoundException)")

        if a[:2] == ["ecr", "put-lifecycle-policy"]:
            self.lifecycle[opt("--repository-name")] = opt("--lifecycle-policy-text")
            return (0, "{}", "")

        if a[:2] == ["ecr", "describe-images"]:
            n = opt("--repository-name")
            iid = opt("--image-ids")
            imgs = self.images.get(n, [])
            if iid.startswith("imageTag="):
                key = iid.split("=", 1)[1]
                match = [i for i in imgs if key in i["imageTags"]]
            else:
                key = iid.split("=", 1)[1]
                match = [i for i in imgs if i["imageDigest"] == key]
            if not match:
                return (254, "", "An error occurred (ImageNotFoundException)")
            return (0, json.dumps({"imageDetails": match}), "")

        if a[:2] == ["ecr", "batch-get-image"]:
            n = opt("--repository-name")
            d = opt("--image-ids").split("=", 1)[1]
            m = self.manifests.get((n, d))
            if m is None:
                return (0, json.dumps({"images": []}), "")
            img = next(i for i in self.images[n] if i["imageDigest"] == d)
            return (0, json.dumps({"images": [{
                "imageId": {"imageDigest": d}, "imageManifest": m,
                "imageManifestMediaType": img["imageManifestMediaType"],
            }]}), "")

        if a[:2] == ["ecr", "put-image"]:
            n = opt("--repository-name")
            manifest = opt("--image-manifest")
            newtag = opt("--image-tag")
            for i in self.images[n]:
                if self.manifests.get((n, i["imageDigest"])) == manifest:
                    for j in self.images[n]:
                        if newtag in j["imageTags"] and j is not i:
                            j["imageTags"].remove(newtag)
                    if newtag not in i["imageTags"]:
                        i["imageTags"].append(newtag)
                    return (0, "{}", "")
            return (254, "", "ImageNotFoundException")

        raise AssertionError(f"unexpected AWS call: {a}")


@pytest.fixture
def ecr(monkeypatch):
    fake = FakeECR()
    monkeypatch.setattr(rd, "run_aws", fake)
    monkeypatch.setattr(rp, "run_aws", fake)
    return fake


def _pushing_copier(ecr: FakeECR, *, digest="sha256:dest0000", arch="amd64"):
    calls = []

    def _copy(source_reference, destination_reference):
        calls.append((source_reference, destination_reference))
        ecr.add_image(REPO, digest, ["tested"], arch=arch)

    _copy.calls = calls
    return _copy


# ── resolution ─────────────────────────────────────────────────────────
def test_tested_image_resolved_from_registry():
    img = _resolve_tested_image("issm")
    assert img.reference == SOURCE_REF
    assert img.digest == SOURCE_DIGEST
    assert ecr_repository_name("issm") == "cryostack-issm"


# ── absent image -> mirror ─────────────────────────────────────────────
def test_repository_absent_is_created_then_mirrored(ecr):
    copier = _pushing_copier(ecr)
    result = mirror_tested_image(CONFIG, model="issm", copier=copier)

    assert ecr.count("ecr", "create-repository") == 1
    assert copier.calls == [(SOURCE_REF, f"{URI}:tested")]
    assert result.mirrored is True and result.verified is True
    assert result.immutable_reference == f"{URI}@sha256:dest0000"
    assert result.destination_digest == "sha256:dest0000"
    # the ECR image is now bound to the exact tested source
    assert SRC_TAG in ecr.tags_of(REPO, "sha256:dest0000")


def test_present_image_is_reused_with_zero_transfer(ecr):
    ecr.add_repo()
    ecr.add_image(REPO, "sha256:already", ["tested", SRC_TAG])

    def _must_not_copy(*_a):
        raise AssertionError("copier must not run when the image is present")

    result = mirror_tested_image(CONFIG, model="issm", copier=_must_not_copy)
    assert result.reused is True and result.mirrored is False
    assert result.immutable_reference == f"{URI}@sha256:already"
    assert ecr.count("ecr", "put-image") == 0


def test_tested_tag_wrong_digest_is_repaired(ecr):
    ecr.add_repo()
    ecr.add_image(REPO, "sha256:good", [SRC_TAG])          # correct source binding
    ecr.add_image(REPO, "sha256:stale", ["tested"])        # alias points elsewhere

    result = mirror_tested_image(CONFIG, model="issm", copier=None)

    assert result.repaired is True and result.mirrored is False
    assert result.immutable_reference == f"{URI}@sha256:good"
    assert ecr.digest_of_tag(REPO, "tested") == "sha256:good"
    assert "tested" not in ecr.tags_of(REPO, "sha256:stale")


# ── failure modes ─────────────────────────────────────────────────────
def test_no_copier_and_absent_image_fails_without_touching_ecr(ecr):
    ecr.add_repo()
    with pytest.raises(RegistryDeliveryError) as exc:
        mirror_tested_image(CONFIG, model="issm", copier=None)
    assert "copier" in str(exc.value)
    assert ecr.count("ecr", "put-image") == 0


def test_destination_verification_failure_raises(ecr):
    ecr.add_repo()

    def _lying_copier(*_a):
        return None                                        # "succeeds", pushes nothing

    with pytest.raises(RegistryDeliveryError) as exc:
        mirror_tested_image(CONFIG, model="issm", copier=_lying_copier)
    assert "no image is present" in str(exc.value).lower()
    assert SRC_TAG not in ecr.tags_of(REPO, "sha256:dest0000")   # never bound


def test_copier_exception_becomes_delivery_error(ecr):
    ecr.add_repo()

    def _boom(*_a):
        raise RuntimeError("network reset")

    with pytest.raises(RegistryDeliveryError) as exc:
        mirror_tested_image(CONFIG, model="issm", copier=_boom)
    assert "network reset" in str(exc.value)


# ── digest nuance ────────────────────────────────────────────────────
def test_source_and_destination_digests_recorded_separately(ecr):
    result = mirror_tested_image(
        CONFIG, model="issm",
        copier=_pushing_copier(ecr, digest="sha256:different"),
    )
    assert result.source_digest == SOURCE_DIGEST
    assert result.destination_digest == "sha256:different"
    assert result.digests_match() is False
    assert result.immutable_reference.endswith("@sha256:different")
    assert result.architecture == "amd64"


def test_digests_match_only_when_identical():
    d = ECRImageDelivery(
        model="issm", repository=REPO, repository_uri=URI, tag="tested",
        source_reference=SOURCE_REF, source_digest="sha256:x",
        destination_digest="sha256:x")
    assert d.digests_match() is True
    d2 = ECRImageDelivery(
        model="issm", repository=REPO, repository_uri=URI, tag="tested",
        source_reference=SOURCE_REF, source_digest="sha256:x",
        destination_digest="sha256:y")
    assert d2.digests_match() is False


# ── lifecycle policy ─────────────────────────────────────────────────
def test_lifecycle_policy_is_installed_idempotently(ecr):
    mirror_tested_image(CONFIG, model="issm", copier=_pushing_copier(ecr))
    assert ecr.count("ecr", "put-lifecycle-policy") == 1
    policy = json.loads(ecr.lifecycle[REPO])
    assert policy["rules"][0]["selection"]["tagStatus"] == "untagged"

    # second delivery: policy already matches -> not re-written
    mirror_tested_image(CONFIG, model="issm", copier=None)
    assert ecr.count("ecr", "put-lifecycle-policy") == 1


# ── no credentials leak ─────────────────────────────────────────────
def test_no_credentials_or_tokens_in_result(ecr):
    result = mirror_tested_image(CONFIG, model="issm", copier=_pushing_copier(ecr))
    blob = repr(result) + " ".join(result.messages)
    for secret in ("password", "token", "Bearer", "authorization", "AKIA", "--password-stdin"):
        assert secret.lower() not in blob.lower()
