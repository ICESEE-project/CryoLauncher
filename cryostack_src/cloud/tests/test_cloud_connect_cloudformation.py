"""C7.2 -- CryoStackExecutionRole template + Quick Create URL."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect.cloudformation import (
    EXECUTION_ROLE_NAME,
    execution_role_template,
    quick_create_url,
    render_template,
)

PRINCIPAL = "arn:aws:iam::713938953301:role/cryostack-service"
EXTERNAL_ID = "cryostack:alice-abc:sekret+random/value"
TEMPLATE_URL = "https://cryostack-public.s3.amazonaws.com/cf/execution-role.json"


@pytest.fixture
def template():
    return execution_role_template()


def _all_statements(template):
    policy = template["Resources"]["CryoStackExecutionRole"]["Properties"]["Policies"][0]
    return policy["PolicyDocument"]["Statement"]


def test_trust_policy_requires_sts_external_id_and_the_cryostack_principal(template):
    trust = template["Resources"]["CryoStackExecutionRole"]["Properties"][
        "AssumeRolePolicyDocument"
    ]
    stmt = trust["Statement"][0]
    assert stmt["Action"] == "sts:AssumeRole"
    assert stmt["Principal"]["AWS"] == {"Ref": "CryoStackPrincipalArn"}
    assert stmt["Condition"]["StringEquals"]["sts:ExternalId"] == {"Ref": "ExternalId"}


def test_external_id_is_a_noecho_parameter(template):
    param = template["Parameters"]["ExternalId"]
    assert param["NoEcho"] is True
    assert param["Type"] == "String"


def test_role_has_no_fixed_physical_name(template):
    """WS onboarding role-name collision fix: the Role resource must NOT set
    an explicit RoleName -- CloudFormation generates a unique, stack-scoped
    physical name so a second connection's stack (a different CryoStack
    identity, or a genuinely new connection replacing this one) can never
    collide with 'Resource of type AWS::IAM::Role ... already exists'.
    EXECUTION_ROLE_NAME remains only the template's Role LOGICAL id."""
    props = template["Resources"]["CryoStackExecutionRole"]["Properties"]
    assert "RoleName" not in props
    assert "CryoStackExecutionRole" in template["Resources"]     # logical id unchanged
    assert EXECUTION_ROLE_NAME == "CryoStackExecutionRole"


def test_role_arn_output_is_the_real_cloudformation_created_role(template):
    """The pasted-back RoleArn must always be Fn::GetAtt on the actual
    resource CloudFormation created -- never a string built from a fixed
    name -- so it is correct regardless of what physical name CFN picked."""
    output = template["Outputs"]["RoleArn"]
    assert output["Value"] == {"Fn::GetAtt": ["CryoStackExecutionRole", "Arn"]}


def test_no_administrator_access_and_no_star_star(template):
    blob = json.dumps(template)
    assert "AdministratorAccess" not in blob
    assert "PowerUserAccess" not in blob
    for stmt in _all_statements(template):
        actions = stmt["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        resources = stmt["Resource"]
        resources = [resources] if isinstance(resources, str) else resources
        # a bare Action:"*" is never allowed; Resource:"*" only for known
        # un-scopable describe/auth/identity statements
        assert "*" not in actions
        if "*" in resources:
            assert stmt["Sid"] in {
                "CryoStackEcrAuth",
                "CryoStackEcrListRepositories",
                "CryoStackBatchRead",
                "CryoStackNetworkDiscovery",
                "CryoStackIdentityAndPricing",
                "CryoStackIamListRoles",
            }, stmt["Sid"]


def test_s3_is_scoped_to_cryostack_runs(template):
    sids = {s["Sid"]: s for s in _all_statements(template)}
    assert sids["CryoStackRunsBuckets"]["Resource"] == {
        "Fn::Sub": "arn:${AWS::Partition}:s3:::cryostack-runs-*"
    }
    assert sids["CryoStackRunsObjects"]["Resource"] == {
        "Fn::Sub": "arn:${AWS::Partition}:s3:::cryostack-runs-*/*"
    }


def test_ecr_repo_actions_are_scoped_to_cryostack_repositories(template):
    sids = {s["Sid"]: s for s in _all_statements(template)}
    repos = sids["CryoStackEcrRepos"]
    assert "repository/cryostack-*" in repos["Resource"]["Fn::Sub"]
    # every repository-specific ECR action stays scoped; only the account-wide
    # LISTING call (ecr:DescribeRepositories with no filter) is on Resource "*"
    scoped = repos["Action"] if isinstance(repos["Action"], list) else [repos["Action"]]
    assert "ecr:DescribeRepositories" not in scoped
    for must_stay_scoped in ("ecr:CreateRepository", "ecr:PutImage",
                             "ecr:DescribeImages", "ecr:BatchGetImage",
                             "ecr:UploadLayerPart", "ecr:PutLifecyclePolicy"):
        assert must_stay_scoped in scoped

    lst = sids["CryoStackEcrListRepositories"]
    assert lst["Action"] == "ecr:DescribeRepositories"
    assert lst["Resource"] == "*"


def test_ecr_describe_repositories_is_the_only_ecr_action_moved_to_star(template):
    """Regression for the Account-B Prepare failure:
    `AccessDeniedException ... ecr:DescribeRepositories on arn:...:repository/*`.
    The unfiltered discovery call needs Resource "*"; nothing else changed."""
    star_ecr = set()
    for s in _all_statements(template):
        acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
        res = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
        if "*" in res:
            star_ecr.update(a for a in acts if a.startswith("ecr:"))
    assert star_ecr == {"ecr:GetAuthorizationToken", "ecr:DescribeRepositories"}


def test_batch_submit_describe_terminate_are_all_present(template):
    actions = set()
    for stmt in _all_statements(template):
        a = stmt["Action"]
        actions.update([a] if isinstance(a, str) else a)
    assert {"batch:SubmitJob", "batch:DescribeJobs", "batch:TerminateJob"} <= actions


def test_provisioning_permission_audit_actions_are_all_granted(template):
    """C7.3 IAM audit: every AWS action the connected role's Prepare cloud
    performs (bootstrap + prepare_batch) must be in the template policy."""
    granted = set()
    for stmt in _all_statements(template):
        a = stmt["Action"]
        granted.update([a] if isinstance(a, str) else a)

    required = {
        # S3 (storage.py)
        "s3:CreateBucket", "s3:ListBucket", "s3:PutEncryptionConfiguration",
        "s3:PutBucketPublicAccessBlock",
        # EC2 discovery (network.py)
        "ec2:DescribeVpcs", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups",
        # IAM (iam.py / iam_provision.py)
        "iam:ListRoles", "iam:CreateRole", "iam:PutRolePolicy",
        "iam:AttachRolePolicy", "iam:PassRole",
        # ECR (registry*.py / registry_delivery.py)
        "ecr:GetAuthorizationToken", "ecr:CreateRepository",
        "ecr:DescribeRepositories", "ecr:DescribeImages", "ecr:BatchGetImage",
        "ecr:PutImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload", "ecr:GetLifecyclePolicy",
        "ecr:PutLifecyclePolicy",
        # Batch (batch.py / batch_provision.py)
        "batch:DescribeComputeEnvironments", "batch:DescribeJobQueues",
        "batch:DescribeJobDefinitions", "batch:CreateComputeEnvironment",
        "batch:UpdateComputeEnvironment", "batch:CreateJobQueue",
        "batch:UpdateJobQueue", "batch:RegisterJobDefinition",
        # Batch service-linked role (managed CE, no explicit --service-role)
        "iam:CreateServiceLinkedRole",
        # CloudWatch Logs (batch_provision.py)
        "logs:CreateLogGroup", "logs:PutRetentionPolicy",
        # STS
        "sts:GetCallerIdentity",
    }
    missing = required - granted
    assert not missing, f"template is missing provisioning permissions: {sorted(missing)}"


def test_provisioned_role_names_are_inside_the_iam_scope():
    """The cryostack-* roles iam_provision.py creates must match the template's
    role/cryostack-* scope; the PascalCase cross-account role must not."""
    from cryostack_src.cloud.connect.cloudformation import EXECUTION_ROLE_NAME
    from cryostack_src.cloud.drivers.aws.iam_provision import (
        BATCH_SERVICE_ROLE_NAME,
        ECS_EXECUTION_ROLE_NAME,
        JOB_ROLE_NAME,
    )

    for name in (BATCH_SERVICE_ROLE_NAME, ECS_EXECUTION_ROLE_NAME, JOB_ROLE_NAME):
        assert name.startswith("cryostack-"), name
    # the cross-account role is deliberately OUTSIDE role/cryostack-*
    assert not EXECUTION_ROLE_NAME.startswith("cryostack-")


def test_cloudwatch_log_reads_are_scoped_to_the_cryostack_group(template):
    sids = {s["Sid"]: s for s in _all_statements(template)}
    read = sids["CryoStackLogsRead"]
    assert "logs:GetLogEvents" in read["Action"]
    assert "log-group:/cryostack/*" in read["Resource"]["Fn::Sub"]


def test_passrole_is_tightly_scoped_to_cryostack_roles_and_services(template):
    sids = {s["Sid"]: s for s in _all_statements(template)}
    pr = sids["CryoStackPassRole"]
    assert pr["Action"] == "iam:PassRole"
    assert pr["Resource"]["Fn::Sub"].endswith("role/cryostack-*")
    services = pr["Condition"]["StringEquals"]["iam:PassedToService"]
    assert set(services) == {"batch.amazonaws.com", "ecs-tasks.amazonaws.com"}


def test_render_template_is_valid_json_round_trip(template):
    assert json.loads(render_template()) == template


def test_checked_in_deployment_artifact_matches_render_template():
    artifact = (
        _REPO / "deployment" / "cloudformation" / "cryostack-execution-role.json"
    )
    assert artifact.is_file(), "regenerate deployment/cloudformation/ (see its README)"
    assert json.loads(artifact.read_text(encoding="utf-8")) == json.loads(
        render_template()
    )


# -- Quick Create URL --------------------------------------------------
def test_quick_create_url_is_well_formed_and_encoded():
    url = quick_create_url(
        template_url=TEMPLATE_URL,
        external_id=EXTERNAL_ID,
        region="us-east-2",
        principal_arn=PRINCIPAL,
        stack_name="cryostack-access",
    )
    parsed = urlparse(url)
    assert parsed.netloc == "us-east-2.console.aws.amazon.com"
    assert parsed.path == "/cloudformation/home"
    assert parsed.fragment.startswith("/stacks/quickcreate")

    query = parse_qs(parsed.fragment.split("?", 1)[1])
    assert query["templateURL"] == [TEMPLATE_URL]
    assert query["stackName"] == ["cryostack-access"]
    # the ExternalId survives a full encode/decode round trip byte-for-byte
    assert query["param_ExternalId"] == [EXTERNAL_ID]
    assert query["param_CryoStackPrincipalArn"] == [PRINCIPAL]
    # reserved characters were percent-encoded in the raw string
    raw = parsed.fragment.split("?", 1)[1]
    assert "sekret%2Brandom%2Fvalue" in raw


def test_quick_create_url_requires_every_input():
    for missing in ("template_url", "external_id", "region", "principal_arn"):
        kwargs = dict(
            template_url=TEMPLATE_URL,
            external_id=EXTERNAL_ID,
            region="us-east-2",
            principal_arn=PRINCIPAL,
        )
        kwargs[missing] = ""
        with pytest.raises(ValueError):
            quick_create_url(**kwargs)
