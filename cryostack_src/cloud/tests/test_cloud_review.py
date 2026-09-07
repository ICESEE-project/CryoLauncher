"""C7.4 -- CloudRunReview assembly, launch gating and drift digest."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.config import resolve_cloud_config
from cryostack_src.cloud.estimate.estimator import estimate_cloud_cost
from cryostack_src.cloud.estimate.models import FargatePrices, RuntimeEstimate
from cryostack_src.cloud.review import (
    InfrastructureReadiness,
    build_cloud_run_review,
    review_digest,
)

OHIO = FargatePrices(region="us-east-2", vcpu_usd_per_hour=0.04048,
                     gib_usd_per_hour=0.004445, ephemeral_usd_per_gib_hour=0.000111,
                     source="AWS Price List API (us-east-1)",
                     source_timestamp="2026-09-03T00:00:00+00:00", available=True)
RT = RuntimeEstimate(minutes=5.0, source="Based on the SquareIceShelf reference estimate",
                     basis="example_table")


def _cfg(region="us-east-2"):
    return resolve_cloud_config(bucket="cryostack-runs-774888247882", model="issm",
                                region=region)


def _ready():
    return InfrastructureReadiness(account=True, storage=True, container=True, compute=True)


def _review(**over):
    cfg = over.pop("config", _cfg())
    cost = over.pop("cost", estimate_cloud_cost(
        region=cfg.region, vcpu=cfg.vcpu, memory_gib=cfg.memory_gib,
        expected_runtime_minutes=RT.minutes, ephemeral_gib=cfg.ephemeral_gib, prices=OHIO))
    kw = dict(
        config=cfg, model="issm", example="SquareIceShelf", run_target="runme.m",
        account_id="774888247882", region=cfg.region,
        infrastructure=over.pop("infrastructure", _ready()),
        runtime=RT, cost=cost, account_freshly_verified=over.pop("fresh", True),
        config_problems=over.pop("config_problems", []),
        preflight_problems=over.pop("preflight_problems", []),
    )
    kw.update(over)
    return build_cloud_run_review(**kw)


# -- gating -----------------------------------------------------------
def test_connected_and_ready_and_licensed_can_launch():
    r = _review()
    assert r.can_launch and not r.blocked_reasons
    assert r.vcpu == 2 and r.memory_gib == 8 and r.time_limit_minutes == 60


def test_partial_infrastructure_blocks_launch():
    r = _review(infrastructure=InfrastructureReadiness(
        account=True, storage=True, container=False, compute=True))
    assert not r.can_launch
    assert any("Container" in x for x in r.blocked_reasons)


def test_stale_account_verification_blocks_launch():
    r = _review(fresh=False)
    assert not r.can_launch
    assert any("verified" in x.lower() for x in r.blocked_reasons)


def test_issm_without_cloud_matlab_license_is_blocked_honestly():
    r = _review(preflight_problems=[
        "[cloud][ERROR] MATLAB licensing is not configured for this compute "
        "profile ('aws'). ISSM needs a MATLAB license."
    ])
    assert not r.can_launch
    assert any("MATLAB license that is reachable from AWS" in x for x in r.blocked_reasons)


def test_unsupported_model_is_blocked():
    r = _review(model="firedrake")
    assert not r.can_launch
    assert any("no supported cloud runtime" in x for x in r.blocked_reasons)


def test_icepack_review_can_launch_without_matlab():
    """Icepack Cloud Execution checkpoint: with infrastructure ready and a
    fresh account, an Icepack review can launch -- no preflight_problems are
    even offered (unlike the ISSM test above), because none apply."""
    cfg = resolve_cloud_config(bucket="cryostack-runs-774888247882",
                               model="icepack", region="us-east-2")
    r = _review(config=cfg, model="icepack")
    assert r.can_launch and not r.blocked_reasons
    assert r.config.job_definition == "cryostack-icepack"


def test_missing_cost_estimate_does_not_block_launch():
    r = _review(cost=estimate_cloud_cost(
        region="us-east-2", vcpu=2, memory_gib=8, expected_runtime_minutes=5,
        prices=FargatePrices(region="us-east-2", available=False)))
    assert r.can_launch                              # cost unavailable != blocked
    assert r.cost_summary() == "unavailable"
    assert "Cost estimate unavailable" in " ".join(r.estimate_basis_lines())


# -- canonical resources --------------------------------------------
def test_review_resources_are_the_canonical_config_values():
    cfg = _cfg()
    r = _review(config=cfg)
    assert (r.vcpu, r.memory_gib, r.time_limit_minutes) == (
        cfg.vcpu, cfg.memory_gib, cfg.time_limit_minutes)
    assert r.config is cfg                           # same object the submit path uses


# -- drift digest -------------------------------------------------
def test_digest_is_stable_for_the_same_config():
    a = review_digest(config=_cfg(), model="issm", example="SquareIceShelf",
                      run_target="runme.m", account_id="774888247882")
    b = review_digest(config=_cfg(), model="issm", example="SquareIceShelf",
                      run_target="runme.m", account_id="774888247882")
    assert a == b and len(a) == 16


@pytest.mark.parametrize("change", [
    {"region": "eu-west-1"},
    {"example": "PIG"},
    {"run_target": "other.m"},
    {"account_id": "713938953301"},
    {"scientific_overrides": {"stressbalance.maxiter": 20}},
])
def test_digest_changes_when_billable_config_changes(change):
    base = dict(config=_cfg(), model="issm", example="SquareIceShelf",
                run_target="runme.m", account_id="774888247882",
                scientific_overrides={})
    a = review_digest(**base)
    if "region" in change:
        base["config"] = _cfg(region=change.pop("region"))
    base.update(change)
    assert review_digest(**base) != a


def test_digest_changes_when_resource_shape_changes():
    from cryostack_src.cloud.drivers.aws.batch_config import FargateJobConfig

    a = review_digest(config=_cfg(), model="issm", example="x", run_target="r",
                      account_id="A")
    bigger = resolve_cloud_config(bucket="cryostack-runs-1", model="issm",
                                  fargate=FargateJobConfig(vcpu="4", memory_mib="16384"))
    b = review_digest(config=bigger, model="issm", example="x", run_target="r",
                      account_id="A")
    assert a != b


# -- security ---------------------------------------------------
def test_review_public_dict_carries_no_secret_and_no_external_id():
    blob = str(_review().to_public_dict())
    for forbidden in ("AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "ExternalId",
                      "external_id", "cryostack:"):
        assert forbidden not in blob


# -- container image provenance -------------------------------------
def test_review_resolves_the_tested_container_image_for_the_model():
    from cryostack_src.models.stack import default_tested_image_for_model

    for model in ("issm", "icepack"):
        cfg = resolve_cloud_config(bucket="cryostack-runs-774888247882", model=model)
        r = _review(config=cfg, model=model)
        img = default_tested_image_for_model(model)
        assert img is not None
        assert r.image_reference == img.reference
        assert r.image_digest == img.digest
        assert r.image_label == img.label
        assert r.image_key == img.key
        assert r.image_public_url.startswith("https://hub.docker.com/")
        pub = r.to_public_dict()
        assert pub["image_reference"] == img.reference
        assert pub["image_digest"] == img.digest


def test_digest_changes_when_the_tested_image_changes():
    base = dict(config=_cfg(), model="issm", example="x", run_target="r",
                account_id="A")
    a = review_digest(**base, image_digest="sha256:aaaa")
    b = review_digest(**base, image_digest="sha256:bbbb")
    assert a != b
    # default (no image) is still stable
    assert review_digest(**base) == review_digest(**base)


def test_changing_the_default_image_invalidates_an_open_review(monkeypatch):
    import cryostack_src.models.stack.images as images

    cfg = resolve_cloud_config(bucket="cryostack-runs-774888247882", model="icepack")
    before = _review(config=cfg, model="icepack").digest

    newer = images.TestedImage(
        key="icesee-combined-v9.9.9", label="ICESEE Combined v9.9.9",
        reference="bkyanjo/icesee-combined:v9.9.9",
        digest="sha256:" + "9" * 64, models=("issm", "icepack"))
    # a new CryoStack default, resolved first
    reordered = {"icesee-combined-v9.9.9": newer, **images.TESTED_IMAGES}
    monkeypatch.setattr(images, "TESTED_IMAGES", reordered)

    after = _review(config=cfg, model="icepack")
    assert after.digest != before
    assert after.image_reference == "bkyanjo/icesee-combined:v9.9.9"
