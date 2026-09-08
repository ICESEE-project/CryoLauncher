# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Driver
# File        : driver.py
#
# Description :
#     Provides the high-level AWS cloud driver used by CryoStack to
#     discover and prepare AWS resources.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-24
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
AWS cloud driver for CryoStack.

The driver combines AWS authentication, storage, networking, IAM,
registry, Batch, and capability discovery behind one interface.

Resource provisioning is introduced incrementally. Storage and IAM
can currently be prepared automatically, while registry and AWS Batch
resources remain discovery-only until their provisioning layers are
completed.
"""

from __future__ import annotations

import re

from ..base import CloudDriver

# Defence-in-depth: strip anything that looks like AWS credential material or a
# CryoStack ExternalId from a raw error before it is carried in a result the UI
# will print. `run_aws` keeps credentials in the child env (never argv), so this
# only matters if a CLI error echoes something unexpected.
_SECRET_TEXT_RE = re.compile(
    r"(ASIA[0-9A-Z]{6,}|AKIA[0-9A-Z]{6,}"
    r"|(?:aws[_-])?(?:session|security)[_ -]?token[\"'=:\s]+\S+"
    r"|x-amz-security-token[\"'=:\s]+\S+"
    r"|\b(?:FwoG|IQoJ|FQoG|Fwo)[A-Za-z0-9+/=_-]{16,}"
    r"|cryostack:[\w.\-]+:[\w\-]{8,})",
    re.IGNORECASE,
)


def _redact(text: str) -> str:
    return _SECRET_TEXT_RE.sub("<redacted>", text or "")


def _issm_matlab_secrets(secret_arn: str) -> list[dict] | None:
    """``containerProperties.secrets`` for the ISSM job definition from a
    (non-secret) Secrets Manager ARN. ``None`` when unconfigured -- the
    license value never passes through CryoStack."""
    from cryostack_src.cloud.matlab_license import CloudMatlabLicense

    arn = (secret_arn or "").strip()
    if not arn:
        return None
    lic = CloudMatlabLicense(configured=True, mechanism="secrets-manager",
                             secret_arn=arn)
    return lic.batch_secrets_block() or None

from .auth import (
    AWSCredentialsError,
    discover_account,
)

from .batch import (
    discover_batch_resources,
)

from .batch_config import (
    DEFAULT_MAX_VCPUS,
)

from .batch_provision import (
    AWSBatchProvisionResult,
    ensure_batch_resources,
)

from .registry_delivery import (
    RegistryDeliveryError,
    buildx_imagetools_copier,
    mirror_tested_image,
)

from .capabilities import (
    discover_capabilities,
)

from .iam import (
    discover_iam_resources,
)

from .iam_provision import (
    ensure_iam_resources,
)

from .models import (
    AWSConfig,
)

from .network import (
    discover_network_resources,
)

from .registry import (
    discover_registry_resources,
)

from .storage import (
    prepare_storage,
)

from .registry_provision import (
    ensure_registry_resources,
)

from cryostack_src.cloud.legacy.aws_batch import (
    batch_logs,
    batch_status,
    terminate_batch_job,
)

class AWSDriver(
    CloudDriver
):
    """
    CryoStack AWS cloud driver.
    """

    name = "aws"

    def __init__(
        self,
        *,
        region: str = "us-east-2",
        profile: str | None = None,
        credentials: dict[str, str] | None = None,
        submitter=None,
    ) -> None:

        #: ``credentials`` (assumed-role temporary env) is end-user mode and
        #: wins over ``profile``; both absent is developer/ambient mode.
        self.config = AWSConfig(
            region=region,
            profile=profile,
            credentials=credentials,
        )

        #
        # Transitional submission hook.
        #
        # ISSM cloud submission will move fully into the AWS
        # driver after Batch provisioning is completed.
        #
        self._submitter = submitter

    def account(
        self,
    ):

        return discover_account(
            self.config
        )

    def capabilities(
        self,
    ):

        return discover_capabilities(
            self.config
        )

    def prepare_storage(
        self,
        *,
        bucket: str | None = None,
    ):

        return prepare_storage(
            self.config,
            bucket=bucket,
        )

    def network(
        self,
    ):

        return discover_network_resources(
            self.config
        )

    def iam(
        self,
    ):

        return discover_iam_resources(
            self.config
        )

    def registry(
        self,
    ):

        return discover_registry_resources(
            self.config
        )

    def batch(
        self,
    ):

        return discover_batch_resources(
            self.config
        )

    def prepare_batch(
        self,
        *,
        network=None,
        iam=None,
        registry=None,          # accepted for call-site compatibility; unused
        max_vcpus: int = DEFAULT_MAX_VCPUS,
        include_icepack: bool = False,
        include_icesee: bool = False,
        image_copier=None,
        matlab_secret_arn: str = "",
    ) -> AWSBatchProvisionResult:
        """
        Idempotently provision AWS Batch on Fargate: a scale-to-zero compute
        environment, a job queue, and the ISSM job definition (+ log group).
        When ``include_icepack``/``include_icesee`` is set, that model's job
        definition (+ its own log group) is provisioned the same way, in the
        SAME compute environment / queue -- one Batch environment, N job
        definitions, no second cloud execution path. ICESEE's job definition
        runs :func:`icesee_jupyter_book.core.cloud_runner.icesee_batch_command`
        (its own ``ICESEE_*`` env contract, verified 2026-09-08 for
        single-rank/lorenz96 only -- see that module), never the generic
        ``cryostack-run`` command ISSM/Icepack share.

        Each model's job definition is pinned to the tested image **by
        digest**: the (single, combined) tested image is mirrored into that
        model's own ECR repository (once per repository -- ``cryostack-issm``
        / ``cryostack-icepack``) and the resulting ``<repo>@sha256:...``
        reference feeds its job definition. A failed or unconfigured mirror
        for one model leaves only THAT model's job definition untouched --
        CryoStack never points Batch at an unverified image, and one model's
        delivery failure never blocks the other's.

        Discovery results for network / IAM may be passed in to avoid
        re-describing. ``image_copier`` overrides the transfer mechanism; by
        default it is ``buildx_imagetools_copier`` -- a one-time, idempotent
        registry-to-registry copy (``docker buildx imagetools create``): no
        image rebuild, no Apptainer conversion, and Batch never depends on a
        mutable tag. The copy runs only when the exact tested image is not
        already in the target ECR repository. The SAME copier instance is
        reused for both models' mirror calls.
        """

        network = network or self.network()
        iam = iam or self.iam()

        copier = (image_copier if image_copier is not None
                  else buildx_imagetools_copier(self.config))

        def _mirror(model: str) -> tuple[object | None, str | None, list[str]]:
            """Mirror one model's tested image; never lets that model's
            failure raise -- it degrades to "job definition left unchanged"
            exactly like the pre-Icepack ISSM-only behaviour did."""
            try:
                d = mirror_tested_image(self.config, model=model, copier=copier)
            except RegistryDeliveryError as err:
                return None, None, [
                    f"Tested-image delivery not ready: {err} "
                    f"-- {model.upper()} job definition left unchanged."
                ]
            if d.verified and d.immutable_reference:
                return d, d.immutable_reference, list(d.messages)
            return d, None, list(d.messages)

        delivery, issm_image, delivery_messages = _mirror("issm")

        icepack_delivery = None
        icepack_image = None
        if include_icepack:
            icepack_delivery, icepack_image, icepack_messages = _mirror("icepack")
            delivery_messages.extend(icepack_messages)

        icesee_delivery = None
        icesee_image = None
        if include_icesee:
            icesee_delivery, icesee_image, icesee_messages = _mirror("icesee")
            delivery_messages.extend(icesee_messages)

        from cryostack_src.cloud.runtime import cloud_run_command
        from icesee_jupyter_book.core.cloud_runner import icesee_batch_command

        result = ensure_batch_resources(
            self.config,
            subnets=network.subnet_ids,
            security_groups=network.security_group_ids,
            job_role_arn=iam.job_role,
            execution_role_arn=iam.ecs_execution_role,
            issm_image=issm_image,
            max_vcpus=max_vcpus,
            job_command=cloud_run_command(),
            issm_secrets=_issm_matlab_secrets(matlab_secret_arn),
            include_icepack=include_icepack,
            icepack_image=icepack_image,
            include_icesee=include_icesee,
            icesee_image=icesee_image,
            icesee_command=icesee_batch_command() if include_icesee else None,
        )
        result.image_delivery = delivery
        result.icepack_image_delivery = icepack_delivery
        result.icesee_image_delivery = icesee_delivery
        result.messages.extend(delivery_messages)
        return result

    def bootstrap(
        self,
        *,
        bucket: str | None = None,
        matlab_secret_arn: str = "",
    ) -> dict:
        """
        Prepare the AWS environment currently supported by CryoStack.

        The bootstrap sequence currently:

        1. verifies the AWS connection,
        2. prepares S3 run storage,
        3. discovers usable networking,
        4. prepares required IAM roles,
        5. discovers ECR repositories,
        6. discovers AWS Batch resources,
        7. recalculates the final capability state.

        Registry and Batch provisioning will be added separately.
        """

        messages: list[str] = []

        # Per-row readiness for the UI: "connected"/"not_connected" for account,
        # "ready"/"failed"/"not_attempted" for the rest. Preparation aborts on
        # the first failing stage; stages that were never reached stay
        # "not_attempted" so the UI never shows them as an independent failure.
        row_status: dict[str, str] = {
            "account": "not_connected",
            "storage": "not_attempted",
            "registry": "not_attempted",
            "compute": "not_attempted",
        }

        def _partial(*, capabilities=None) -> dict:
            return {
                "success": False,
                "provider": self.name,
                "region": self.config.region,
                "account": account,
                "storage": None,
                "network": None,
                "iam": None,
                "registry": None,
                "batch": None,
                "capabilities": capabilities,
                "row_status": dict(row_status),
                "messages": list(messages),
            }

        #
        # ---------------------------------------------------------
        # Account
        # ---------------------------------------------------------
        #
        account = self.account()

        if not account.authenticated:
            messages.append("AWS account is not connected.")
            return _partial(capabilities=self.capabilities())

        row_status["account"] = "connected"
        messages.append("AWS account connected.")

        # From here, one abort point: a stage raising stops preparation, records
        # a sanitized reason, and returns the partial state. `AWSCredentialsError`
        # keeps its dedicated message; any other error is classified.
        #: which UI row a mid-preparation failure belongs to
        _STAGE_ROW = {
            "storage": "storage",
            "network": "compute", "iam": "compute", "batch": "compute",
            "registry": "registry",
        }
        stage = "storage"
        try:

            #
            # ---------------------------------------------------------
            # Storage
            # ---------------------------------------------------------
            #
            storage = self.prepare_storage(bucket=bucket)
            row_status["storage"] = "ready"
            messages.append(
                "CryoStack S3 storage created."
                if storage.created
                else "CryoStack S3 storage already exists."
            )

            #
            # ---------------------------------------------------------
            # Network
            # ---------------------------------------------------------
            #
            stage = "network"
            network = self.network()
            if (
                network.vpc_id
                and network.subnet_ids
                and network.security_group_ids
            ):
                messages.append("AWS networking discovered.")
            else:
                messages.append("AWS networking is incomplete.")

            #
            # ---------------------------------------------------------
            # IAM
            # ---------------------------------------------------------
            #
            stage = "iam"
            iam_result = ensure_iam_resources(
                self.config,
                bucket=storage.bucket,
            )
            iam = iam_result.resources
            if iam_result.created:
                messages.append(
                    "Created IAM resources: " + ", ".join(iam_result.created)
                )
            if iam_result.reused:
                messages.append(
                    "Reused IAM resources: " + ", ".join(iam_result.reused)
                )

            #
            # ---------------------------------------------------------
            # Registry
            # ---------------------------------------------------------
            #
            stage = "registry"
            # Prepare Cloud provisions every currently-tested model's ECR
            # repository -- cryostack-issm, cryostack-icepack and
            # cryostack-icesee -- from the single tested combined image
            # (models=("issm","icepack","icesee")); idempotent, never a
            # rebuild.
            registry_result = self.prepare_registry(
                include_icepack=True, include_icesee=True)
            registry = registry_result.resources
            if registry_result.created:
                messages.append(
                    "Created ECR repositories: "
                    + ", ".join(registry_result.created)
                )
            if registry_result.reused:
                messages.append(
                    "Reused ECR repositories: "
                    + ", ".join(registry_result.reused)
                )
            row_status["registry"] = "ready"

            #
            # ---------------------------------------------------------
            # Batch (Fargate) provisioning
            # ---------------------------------------------------------
            #
            stage = "batch"
            batch_result = self.prepare_batch(
                network=network,
                iam=iam,
                registry=registry,
                include_icepack=True,
                include_icesee=True,
                matlab_secret_arn=matlab_secret_arn,
            )

        except AWSCredentialsError:
            row_status[_STAGE_ROW.get(stage, "compute")] = "failed"
            messages.append(
                "[cloud][ERROR] AWS access was lost while preparing the cloud "
                "environment. Re-check the connected AWS account and try again."
            )
            return _partial()

        except Exception as error:  # noqa: BLE001 -- surfaced + carried to the Run Log
            row_status[_STAGE_ROW.get(stage, "compute")] = "failed"
            messages.append(
                f"[cloud][ERROR] Could not prepare the cloud environment "
                f"(stage: {stage}). See the detail below and the AWS role's "
                f"permissions."
            )
            # raw detail is carried verbatim; the Run Log emitter sanitizes it
            messages.append(f"[cloud][detail] {_redact(str(error))[:1500]}")
            return _partial()

        batch = batch_result.resources

        for label, items in (
            ("Created", batch_result.created),
            ("Updated", batch_result.updated),
            ("Reused", batch_result.reused),
        ):
            if items:
                messages.append(
                    f"{label} AWS Batch resources: "
                    + ", ".join(items)
                )

        for skipped in batch_result.skipped:
            messages.append(
                f"AWS Batch: skipped {skipped}"
            )

        for message in batch_result.messages:
            messages.append(message)

        if (
            batch.compute_environment
            and batch.job_queue
            and batch.issm_job_definition
        ):

            messages.append(
                "AWS Batch environment is ready."
            )

        else:

            messages.append(
                "AWS Batch environment is incomplete."
            )

        #
        # Recalculate after provisioning.
        #
        capabilities = self.capabilities()

        success = bool(
            capabilities.authenticated
            and capabilities.storage_ready
            and capabilities.network_ready
            and capabilities.iam_ready
            and capabilities.batch_ready
        )

        # every stage completed without raising; reflect the recalculated
        # capability state per row (a stage can still be "incomplete" without
        # having raised -- e.g. discovery found no usable VPC).
        row_status["account"] = "connected" if capabilities.authenticated else "not_connected"
        row_status["storage"] = "ready" if capabilities.storage_ready else "failed"
        row_status["registry"] = "ready" if capabilities.registry_ready else "failed"
        row_status["compute"] = (
            "ready"
            if (capabilities.network_ready and capabilities.iam_ready
                and capabilities.batch_ready)
            else "failed"
        )

        return {
            "success": success,
            "provider": self.name,
            "region": self.config.region,
            "account": account,
            "storage": storage,
            "network": network,
            "iam": iam,
            "registry": registry,
            "batch": batch,
            "capabilities": capabilities,
            "row_status": dict(row_status),
            "messages": messages,
        }

    def prepare_registry(
        self,
        *,
        include_icepack: bool = False,
        include_icesee: bool = False,
    ):

        return ensure_registry_resources(
            self.config,
            include_icepack=include_icepack,
            include_icesee=include_icesee,
        )

    def submit(self, **kwargs):
        """Submit a staged CryoStack cloud run to AWS Batch.

        Flow: ``assert_cloud_run_allowed`` (license / model gate, before any
        upload) -> ``stage_run_inputs`` (the StagedExample tree + descriptor to
        ``s3://<bucket>/runs/<run-id>/input/``) -> ``aws batch submit-job`` with
        three non-secret env values.

        A legacy ``submitter`` may still be injected (old ICESEE path); it wins
        when present so nothing existing breaks.

        Returns a dict:
            {run_id, batch_job_id, s3_run, s3_input, s3_outputs, model,
             run_target, job_queue, job_definition, messages}
        """
        if self._submitter is not None:
            return self._submitter(**kwargs)

        from cryostack_src.cloud.preflight import assert_cloud_run_allowed
        from .staging import stage_run_inputs
        from .submit import submit_batch_job
        from .batch_config import JOB_QUEUE_NAME, job_definition_name

        staged_source = kwargs.get("staged_source") or kwargs.get("source")
        model = (kwargs.get("model") or "").strip().lower()
        run_target = (kwargs.get("run_target") or "runme.m").strip()
        bucket = (kwargs.get("bucket") or "").strip()
        working_directory = kwargs.get("working_directory") or "."
        run_id = kwargs.get("run_id")
        run_prefix = kwargs.get("run_prefix") or ""
        job_name = kwargs.get("job_name") or "cryostack"
        job_queue = (kwargs.get("job_queue") or "").strip() or JOB_QUEUE_NAME
        job_definition = (kwargs.get("job_definition") or "").strip() or job_definition_name(model)
        matlab_license_configured = bool(kwargs.get("matlab_license_configured", False))
        s3 = kwargs.get("s3")
        aws = kwargs.get("aws")

        if staged_source is None:
            raise RuntimeError("AWS cloud submission needs a staged run (staged_source).")
        if not bucket:
            raise RuntimeError("AWS cloud submission needs an S3 bucket.")

        # 1. gate the run BEFORE anything is uploaded or a job is created
        assert_cloud_run_allowed(
            model=model, matlab_license_configured=matlab_license_configured
        )

        # 2. stage the run's inputs to S3
        staging = stage_run_inputs(
            self.config,
            source=staged_source,
            model=model,
            run_target=run_target,
            bucket=bucket,
            run_id=run_id,
            run_prefix=run_prefix,
            working_directory=working_directory,
            s3=s3,
        )

        # 3. submit to Batch
        submission = submit_batch_job(
            self.config,
            job_name=job_name,
            job_queue=job_queue,
            job_definition=job_definition,
            s3_run=staging.s3_run,
            model=model,
            run_target=run_target,
            run_id=staging.run_id,
            aws=aws,
        )

        return {
            "run_id": staging.run_id,
            "batch_job_id": submission.job_id,
            "s3_run": staging.s3_run,
            "s3_input": staging.s3_input,
            "s3_outputs": staging.s3_outputs,
            "model": model,
            "run_target": run_target,
            "job_queue": submission.job_queue,
            "job_definition": submission.job_definition,
            "messages": [*staging.messages, *submission.messages],
        }

    def status(
        self,
        job_id: str,
    ):

        return batch_status(
            self.config,
            job_id,
        )

    def logs(
        self,
        job_id: str,
    ):

        return batch_logs(
            self.config,
            job_id,
        )

    def terminate(
        self,
        job_id: str,
    ):

        return terminate_batch_job(
            self.config,
            job_id,
        )