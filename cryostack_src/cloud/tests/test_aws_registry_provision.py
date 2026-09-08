"""AWS ECR repository provisioning (registry_provision.py), describe-before-
create, idempotency -- extended here to cover the new ICESEE ECR repository
support added alongside its verified tested image (bkyanjo/icesee-combined:
v1.0.1, verified 2026-09-08). All AWS CLI calls are faked; no real AWS
resources are touched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.cloud.drivers.aws import registry as registry_mod
from cryostack_src.cloud.drivers.aws import registry_provision as rp
from cryostack_src.cloud.drivers.aws.models import AWSConfig

CONFIG = AWSConfig(region="us-east-2")


class FakeAWS:
    """A minimal in-memory ECR the provisioner can drive."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.repos: dict[str, dict] = {}

    def count(self, *prefix) -> int:
        p = list(prefix)
        return sum(1 for c in self.calls if c[: len(p)] == p)

    @staticmethod
    def _opt(args: list[str], name: str):
        return args[args.index(name) + 1]

    def __call__(self, config, args):
        a = list(args)
        self.calls.append(a)

        if a[:2] == ["ecr", "describe-repositories"]:
            if "--repository-names" in a:
                name = self._opt(a, "--repository-names")
                if name not in self.repos:
                    return (255, "", "RepositoryNotFoundException: ...")
                return (0, json.dumps({"repositories": [self.repos[name]]}), "")
            return (0, json.dumps({"repositories": list(self.repos.values())}), "")

        if a[:2] == ["ecr", "create-repository"]:
            name = self._opt(a, "--repository-name")
            repo = {
                "repositoryName": name,
                "repositoryUri": f"123456789012.dkr.ecr.us-east-2.amazonaws.com/{name}",
            }
            self.repos[name] = repo
            return (0, json.dumps({"repository": repo}), "")

        raise AssertionError(f"unexpected AWS call: {a}")

    def seed(self, name: str) -> None:
        self.repos[name] = {
            "repositoryName": name,
            "repositoryUri": f"123456789012.dkr.ecr.us-east-2.amazonaws.com/{name}",
        }


@pytest.fixture
def aws(monkeypatch):
    fake = FakeAWS()
    monkeypatch.setattr(rp, "run_aws", fake)
    monkeypatch.setattr(registry_mod, "run_aws", fake)
    return fake


def test_fresh_account_creates_only_issm_by_default(aws):
    result = rp.ensure_registry_resources(CONFIG)
    assert result.created == ["cryostack-issm"]
    assert result.reused == []
    assert result.resources.issm_repository == "cryostack-issm"
    assert result.resources.icepack_repository is None
    assert result.resources.icesee_repository is None


def test_second_run_reuses_issm(aws):
    rp.ensure_registry_resources(CONFIG)
    result = rp.ensure_registry_resources(CONFIG)
    assert result.created == []
    assert result.reused == ["cryostack-issm"]
    assert aws.count("ecr", "create-repository") == 1


def test_include_icepack_creates_both_repositories(aws):
    result = rp.ensure_registry_resources(CONFIG, include_icepack=True)
    assert set(result.created) == {"cryostack-issm", "cryostack-icepack"}
    assert result.resources.icepack_repository == "cryostack-icepack"
    assert result.resources.icesee_repository is None


# -- ICESEE ECR repository (new) ------------------------------------------
def test_include_icesee_creates_the_icesee_repository(aws):
    result = rp.ensure_registry_resources(CONFIG, include_icesee=True)
    assert set(result.created) == {"cryostack-issm", "cryostack-icesee"}
    assert result.resources.icesee_repository == "cryostack-icesee"
    assert result.resources.icesee_repository_uri == (
        "123456789012.dkr.ecr.us-east-2.amazonaws.com/cryostack-icesee")


def test_include_icesee_is_idempotent_on_a_second_prepare(aws):
    first = rp.ensure_registry_resources(CONFIG, include_icesee=True)
    assert "cryostack-icesee" in first.created

    second = rp.ensure_registry_resources(CONFIG, include_icesee=True)
    assert "cryostack-icesee" in second.reused
    assert aws.count("ecr", "create-repository") == 2   # issm + icesee, once each


def test_include_icesee_reuses_an_already_existing_repository(aws):
    aws.seed("cryostack-icesee")
    result = rp.ensure_registry_resources(CONFIG, include_icesee=True)
    assert "cryostack-icesee" in result.reused
    assert aws.count("ecr", "create-repository") == 1   # issm only


def test_include_icesee_and_icepack_together_are_independent(aws):
    result = rp.ensure_registry_resources(
        CONFIG, include_icepack=True, include_icesee=True)
    assert set(result.created) == {
        "cryostack-issm", "cryostack-icepack", "cryostack-icesee"}
    assert result.resources.icepack_repository == "cryostack-icepack"
    assert result.resources.icesee_repository == "cryostack-icesee"
