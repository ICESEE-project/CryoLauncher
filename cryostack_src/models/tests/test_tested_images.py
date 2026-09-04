"""The tested-image registry and its effect on resolved container provenance."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.models.stack import (
    ContainerIdentityError,
    default_tested_image_for_model,
    find_tested_image,
    get_tested_image,
    resolve_container,
    resolve_stack,
)
from cryostack_src.models.stack import (
    tested_images_for_model as _images_for_model,
)

_KEY = "icesee-combined-v1.0.1"
_REF = "bkyanjo/icesee-combined:v1.0.1"
_DIGEST = "sha256:e393b1eed21f3481fffcfb3bb7ce5ce315fbff0cc8dc0fe4f2bcc2e2f1d538ed"

# v1.0.0: superseded (v1.0.1 adds the AWS CLI for cloud S3 sync -- see
# tools/cloud/Dockerfile and test_cloud_image_awscli.py) but still
# registered, unmodified -- an already-mirrored ECR image, or a run's
# recorded provenance, that named v1.0.0 must still resolve to the SAME
# real fact it always did.
_OLD_KEY = "icesee-combined-v1.0.0"
_OLD_REF = "bkyanjo/icesee-combined:v1.0.0"
_OLD_DIGEST = "sha256:a727f60a738c748d1812b157e1fe94ddb1177ecc32354afa7b747db2f6b7bae5"


# ── registry facts ────────────────────────────────────────────────────────
def test_registry_entry_is_the_combined_image_with_verified_digest():
    img = get_tested_image(_KEY)
    assert img.reference == _REF
    assert img.digest == _DIGEST
    assert img.models == ("issm", "icepack")
    assert img.stack_profile == "tested"


def test_superseded_v1_0_0_stays_registered_unmodified():
    """The old entry is never deleted or overwritten when a newer tested
    image is added -- its digest is a historical fact, not something a
    later release may silently rewrite."""
    img = get_tested_image(_OLD_KEY)
    assert img.reference == _OLD_REF
    assert img.digest == _OLD_DIGEST
    assert img.models == ("issm", "icepack")


def test_tested_issm_offers_the_combined_image_v1_0_1_first():
    imgs = _images_for_model("ISSM")
    assert [i.key for i in imgs] == [_KEY, _OLD_KEY]
    assert all(i.supports("issm") for i in imgs)
    assert default_tested_image_for_model("issm").key == _KEY


def test_tested_icepack_also_sees_the_combined_image():
    assert [i.key for i in _images_for_model("icepack")] == [_KEY, _OLD_KEY]
    assert default_tested_image_for_model("icepack").reference == _REF


def test_unknown_model_has_no_tested_images():
    assert _images_for_model("nope") == ()
    assert default_tested_image_for_model("nope") is None


def test_find_tested_image_by_key_and_reference():
    assert find_tested_image(_KEY).key == _KEY
    assert find_tested_image(_REF).key == _KEY
    assert find_tested_image(f"docker://{_REF}").key == _KEY
    assert find_tested_image("ghcr.io/other/image:1") is None


# ── resolve_container / resolve_stack with a tested image ─────────────────
def test_tested_image_resolves_to_exact_docker_hub_reference():
    ci = resolve_container(
        container_source="docker", image_uri="", tested_image=get_tested_image(_KEY)
    )
    assert ci.source == "docker"
    assert ci.reference == f"docker://{_REF}"
    assert ci.digest == _DIGEST
    assert ci.build_provenance["tested_image"] == _KEY
    assert ci.build_provenance["digest_source"] == "cryostack-tested-registry"


def test_resolve_stack_tested_image_records_reference_and_known_digest():
    out = resolve_stack(
        model="issm", profile="tested", selections=None,
        container_source="docker", image_uri="",
        tested_image_key=_KEY, digest_resolver=None,
    )
    c = out["container"]
    assert c["reference"] == f"docker://{_REF}"
    assert c["digest"] == _DIGEST
    assert "digest_status" not in c.get("build_provenance", {})


def test_docker_source_without_image_or_tested_key_is_blocked():
    with pytest.raises(ContainerIdentityError):
        resolve_container(container_source="docker", image_uri="")
    with pytest.raises(ContainerIdentityError):
        resolve_stack(
            model="issm", profile="tested", selections=None,
            container_source="docker", image_uri="", tested_image_key=None,
        )


def test_custom_image_digest_stays_explicitly_unresolved():
    out = resolve_stack(
        model="issm", profile="tested", selections=None,
        container_source="docker", image_uri="my-org/icesee-fork:dev",
        tested_image_key=None, digest_resolver=None,
    )
    c = out["container"]
    assert c["digest"] is None
    assert c["build_provenance"]["digest_status"] == "unresolved"
    assert c["build_provenance"]["requested_tag"] == "dev"


# ── git / local SIF source modes are untouched by the registry ────────────
def test_git_source_still_records_build_inputs_not_a_digest():
    out = resolve_stack(
        model="issm", profile="tested", selections=None,
        container_source="git", image_uri="",
    )
    c = out["container"]
    assert c["source"] == "git"
    assert c["digest"] is None
    assert c["build_provenance"]["base_image_digest"].startswith("sha256:e2dc1c0d")


def test_local_sif_source_still_records_the_path():
    out = resolve_stack(
        model="issm", profile="tested", selections=None,
        container_source="local", image_uri="/scratch/combined-env.sif",
    )
    c = out["container"]
    assert c["source"] == "local"
    assert c["reference"] == "/scratch/combined-env.sif"
    assert c["build_provenance"]["digest_status"] == "not-applicable"
