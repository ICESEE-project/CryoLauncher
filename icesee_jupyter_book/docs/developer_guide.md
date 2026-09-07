# Developer Guide

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>
:::

:::{raw} html
<div class="cryostack-docs-page">

  <section class="cryostack-docs-hero">

    <div class="cryostack-section-label">
      CryoStack Documentation
    </div>

    <h1>Developer Guide</h1>

    <p>
      Build, extend, test, and integrate applications with the
      CryoStack scientific-computing platform.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary"
         href="https://github.com/ICESEE-project/CryoLauncher"
         target="_blank" rel="noopener noreferrer">
        CryoLauncher Repository
      </a>

      <a class="cryostack-btn secondary" href="../documentation.html">
        Platform Documentation
      </a>
    </div>

  </section>

  <section id="navigation" class="cryostack-section">

    <div class="cryostack-section-label">
      On this page
    </div>

    <h2>Where to go next.</h2>

    <p class="cryostack-section-intro">
      Cards navigate to the sections below. Detailed material stays as
      readable documentation, not cards.
    </p>

    <div class="cryostack-docs-summary-grid">

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">AR</div>
        <h3><a href="#architecture">Architecture</a></h3>
        <p>How the web shell, gateways, application layer, and execution
           backends fit together.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">AP</div>
        <h3><a href="#application-development">Application development</a></h3>
        <p>Local environment, running a gateway, Basic and Advanced modes.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">UI</div>
        <h3><a href="#shared-ui">Shared UI</a></h3>
        <p>Reusable application-shell components and the single responsive
           stylesheet.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">MA</div>
        <h3><a href="#models-and-adapters">Models and adapters</a></h3>
        <p>The model-adapter contract and the WorkspaceManager boundaries.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">RV</div>
        <h3><a href="#results-and-visualization">Results and visualization</a></h3>
        <p>The transport-neutral result package and deterministic rendering.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">TE</div>
        <h3><a href="#testing">Testing</a></h3>
        <p>The Python suite, Node tests, the book build, and source guards.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CN</div>
        <h3><a href="#connector-development">Connector development</a></h3>
        <p>Connector architecture and how to build one locally.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CW</div>
        <h3><a href="#contribution-workflow">Contribution workflow</a></h3>
        <p>Branching, commits, and the checks every change must pass.</p>
      </div>

    </div>

  </section>

  <section id="scope" class="cryostack-section">

    <div class="cryostack-section-label">Scope</div>
    <h2>What this guide covers.</h2>

    <p class="cryostack-section-intro">
      This guide is for people <strong>building on or extending</strong>
      CryoStack. Instructions for ordinary users who install and pair the
      CryoStack Connector, and for configuring HPC access, live in the
      CryoLauncher <strong>User Manual</strong>.
    </p>

    <p>
      Operating a CryoStack <em>deployment</em> &mdash; publishing production
      connector binaries, the canonical release store, nginx and service
      administration, production rollback &mdash; is covered by a separate
      <strong>Maintainer Guide</strong> at <code>/docs/maintainer/</code>.
      That guide is restricted at the authentication boundary to accounts
      holding a <code>developer</code>, <code>maintainer</code>,
      <code>admin</code>, or <code>owner</code> role; a project owner grants
      roles from the CryoStack Control Center. It is not part of this public
      build.
    </p>

    <p>
      <span class="cryostack-status supported">Stable</span>
      architecture, application development, shared UI, models, results,
      testing, contribution workflow.
      <span class="cryostack-status dev">In progress</span>
      expanded model-adapter reference and integration examples.
    </p>

  </section>

</div>
:::

---

## Architecture

CryoStack separates four layers so each can evolve independently:

```text
  WEB SHELL            GATEWAY UI            APPLICATION           EXECUTION
 ┌───────────┐  ──►   ┌───────────┐  ──►   ┌───────────┐  ──►   ┌───────────┐
 │ book +    │        │ Voilà     │        │ adapters, │        │ Remote /  │
 │ auth +    │        │ gateways  │        │ workspace,│        │ HPC,      │
 │ proxies   │        │ (per-user │        │ results,  │        │ containers│
 │ (aiohttp) │        │  kernel)  │        │ profiles  │        │ Spack, …  │
 └───────────┘        └───────────┘        └───────────┘        └───────────┘
```

**Request flow.** A browser request reaches nginx, which forwards everything
to the aiohttp app (`bin/icesee_app.py`) on a local port. That app serves the
built book as static files, installs the authentication routes, mounts the
role-gated Control Center, and wraps each application proxy in `require_login`
so an unauthenticated request never reaches a gateway kernel. The proxy
forwards the caller's verified CryoStack identity to the kernel as a request
header; the kernel treats that header as the **only** trusted identity and
namespaces every workspace by it.

**Ownership boundaries.** Resource facts (login host, scheduler defaults,
supported access/auth mechanisms) belong to a `ComputeProfile` and are never
personal. Per-user, per-resource settings (HPC username, remote directory,
allocation) are persisted only for an authenticated user and are never
inferred from the server process environment. Secrets (bootstrap passwords,
pairing codes, relay tokens) are never persisted and never written to a
manifest, run plan, or log.

**Repository layout.**

| Path | Contents |
|---|---|
| `bin/icesee_app.py` | aiohttp web shell: static book, auth, Control Center, gateway proxies |
| `icesee_jupyter_book/` | Jupyter Book source, gateway UI (`ui/`), gateway core (`core/`) |
| `icesee_jupyter_book/ui/` | Voilà gateways + shared application-shell components |
| `cryostack_src/` | model adapters, workspace, submission, results, visualization, resource profiles, remote bridge |
| `icesee_auth/` | session + role storage, OAuth providers, `require_login` / `require_roles` |
| `control_center/` | role-gated operator console mounted at `/control/` |
| `icesee_hpc_connector/` | the desktop Connector application |
| `deployment/` | build, release, and nginx tooling (see the Maintainer Guide) |

## Application development

**Environment.** Development uses the project conda environment
(`icesee1-dev`). Clone with submodules, create the environment from the
project spec, then run the web shell:

```bash
git clone --recurse-submodules https://github.com/ICESEE-project/CryoLauncher.git
cd CryoLauncher
python bin/icesee_app.py        # serves http://127.0.0.1:8080
```

The shell expects the book to be built
(`jupyter-book build icesee_jupyter_book`) and the two gateway notebooks to
be present. It starts one Voilà process per application and proxies to them.

**Gateway shape.** Each gateway is a single `build_*_ui()` function returning
one `ipywidgets` tree. It composes:

- shared application-shell components (header, Remote Connection panel, Slurm
  Resources panel) from `icesee_jupyter_book/ui/`;
- model-specific run settings, example discovery, and the Run Plan;
- a Workspace panel (persistent, per-user) and a Results panel.

**Basic and Advanced modes.** Basic mode presents curated, validated
configuration — for ISSM this is a solver-aware parameter panel that stages a
user-owned working copy and never mutates a canonical example. Advanced mode
exposes a generic, model-neutral file editor over the same workspace, with
canonical material read-only and a **Clone to My Workspace** action. Both
modes converge on the same submission contract.

## Shared UI

The gateways share generic, model-neutral building blocks in
`icesee_jupyter_book/ui/`. These components **arrange the gateway's existing
widget instances** — they do not own transport, the Run gate, identity
verification, or model logic.

| Component | Responsibility |
|---|---|
| `shared_application_header.build_application_header(app_name)` | Compact shell header: fixed **CryoStack** wordmark above a distinct application name. The mark is derived from the one canonical `cryostack.png`. |
| `shared_remote_connection_panel.build_remote_connection_panel(...)` | Remote Connection organised as *Compute resource / Your HPC identity / Access / Status*, with a status chip driven by the access state, the connector card, and a **Diagnostics** accordion holding the session id, websocket path, and relay state. |
| `shared_slurm_resources_panel.build_slurm_resources_panel(...)` | Slurm request grouped as *Job settings / Compute resources / Allocation and notifications*, full-word labels, help text, responsive 3→2→1 numeric grid. Serializer keys and submission arguments are unchanged. |
| `shared_auth_ux` | Authentication options come from `ComputeProfile.auth_modes` / `ssh_agent_supported`; certificates, token auth, and portal *provisioning* are never advertised. Manual key registration shows a fixed six-step checklist and never collects an institutional web-portal password. |
| `shared_validation` | Pure pre-submit checks: node/task/tasks-per-node floors and consistency, wall-time and memory syntax, allocation required only when the profile says so. No invented site limits. |

All responsive rules for the `cryostack-*` component classes live in a single
stylesheet, `icesee_jupyter_book/ui/shared_app_styles.py`. Do not add a
per-gateway visual system.

## Models and adapters

**Model adapters** (`cryostack_src/models/`) present a uniform interface to
the gateway: discover runnable examples, resolve an entrypoint, describe
templates, and — where relevant — expose a curated parameter schema. A new
model is added by implementing that interface; the gateway code stays
model-neutral.

**WorkspaceManager contracts.** Every workspace is scoped to one
authenticated CryoStack user and stored under a per-user owner root. The
manager enforces containment: a path outside the owner root is rejected, and
canonical application material is read-only and surfaced with a
**Clone to My Workspace** action. User examples and datasets live under
`<owner_root>/examples/<model>/` and `<owner_root>/datasets/`; discovery
merges canonical and user entries and filters utility directories.

**SSH credential namespace.** The server-side SSH Key Manager and the
workstation Connector namespace the generated key by resource + HPC username
(and, server-side, the authenticated CryoStack user), so two people
configuring the same resource never collide on one key. Keys live under
`~/.ssh/cryostack/`. An older cluster-only key is reported but never read or
adopted automatically.

**Execution backends.** A model runs on one of two remote backends, selected
in the gateway:

- **ICESEE-Spack** — a source build activated on the allocation. MATLAB (for
  ISSM) is site-provided. This is the path for **multi-node** runs: ISSM's
  `generic` cluster launches its solver with `mpiexec`, and the host `srun`
  is available, so PRRTE can place ranks across the allocation.
- **ICESEE-Container** — a digest-pinned Apptainer image. The Slurm job runs
  **one** `apptainer exec` on the batch node; ISSM's `solve()` then
  self-launches `mpiexec` (Spack OpenMPI 5 / PRRTE 4) *inside* the image. The
  image ships no Slurm or SSH client, so that launch is confined to the batch
  node by three `apptainer exec --env` flags (`PRTE_MCA_ras=^slurm`,
  `PRTE_MCA_plm=ssh`, `PRTE_MCA_rmaps_default_mapping_policy=:oversubscribe`).
  **Container ISSM is therefore single-node.** `md.cluster.np` (2 for every
  stock ISSM example) is the MPI rank count and is owned by the example, not
  by the Slurm panel; a container ISSM run requesting `-N > 1` logs an
  advisory and still runs on the batch node. Validated end-to-end on Georgia
  Tech PACE (`SquareIceShelf`, `solve` → `outbin` → `postprocess_icesee.m` →
  `cryostack.issm.results` → Results preview). Multi-node containerized MPI is
  a deliberate, unaddressed limitation — use the Spack backend. Do not
  reintroduce the removed `srun` shim (`cryostack_src/models/submission.py`).

**Cloud execution (AWS Batch).**

- *Auth model — two modes.* **Developer / operator mode** uses ambient AWS CLI
  credentials + an optional named profile (`aws configure`); it is the local
  development and acceptance path only. **End-user mode** ("Bring your AWS
  account") is a cross-account IAM role (`CryoStackExecutionRole`) assumed via
  `sts:AssumeRole` with a per-connection `ExternalId`; CryoStack holds only
  *temporary* STS credentials for one operation and persists only non-secret
  connection metadata (`cryostack_src/cloud/connect/`). Never document
  `aws configure` for normal users — keep CLI/profile guidance in Developer /
  Maintainer scope. The onboarding template + Quick Create URL builder live in
  `cryostack_src/cloud/connect/cloudformation.py`; the CryoStack principal ARN
  is deployment config (`CRYOSTACK_AWS_PRINCIPAL_ARN`), never hardcoded, and
  the hosted template URL is `CRYOSTACK_CF_TEMPLATE_URL`.
- *Credential routing (`cryostack_src/cloud/connect/execution.py`).*
  `resolve_cloud_execution()` picks the path per operation: a connected
  `AWSConnection` → a **fresh** `sts:AssumeRole` every time (nothing cached),
  region from the connection, bucket `cryostack-runs-<account-id>`, `profile`
  forced to `None`; **no ambient-credential fallback** — a broken connection
  raises `CloudAccessError` and the op fails closed. No connection record →
  developer mode, unchanged. `CloudBridge` / `CloudBackend` / `CloudManager`
  take a `credentials` kwarg; when set it wins and `run_aws` scrubs ambient
  `AWS_*` from the child env.
- *Run Log emission from background tasks.* Cloud Test/Prepare/Smoke and the
  run lifecycle write the Workspace Run Log from a **detached asyncio task**.
  `with output: print(...)` silently drops there — `ipywidgets.Output` binds
  its capture to the kernel's parent-message header at `__enter__`, which a
  task resumed on a later event-loop iteration no longer has. Use
  `cloud_runtime._emit_log(widget, *lines)` (it calls `Output.append_stdout`,
  writing straight to the synced `outputs` traitlet, and redacts credential
  material). This is why a failed Prepare once left the Run Log empty.
- *Prepare readiness.* `AWSDriver.bootstrap` aborts on the first failing stage
  and returns a structured partial result (`row_status` per row:
  `connected`/`ready`/`failed`/`not_attempted`, plus sanitized messages) rather
  than raising — so Storage/Containers/Compute that were never reached show a
  neutral "Not prepared", never an independent failure. An unhandled exception
  before any structured result marks only the **account** row failed.
- *Interactive BYO run lifecycle (C7.5).* `CloudRunController` takes an
  `execution_provider` (`_resolve_cloud_execution`); when set, **every** AWS
  operation of the run — stage/submit, each status poll, terminate, and the S3
  result sync — is performed with a **fresh** `CloudExecution` (a fresh
  `sts:AssumeRole` for a connected BYO account) and never falls back to
  ambient/profile. `run_once` asserts the fresh session's account matches the
  reviewed `_account_id` before staging (`_assert_same_account` → fail closed).
  `Review & Launch` submits `review.config` verbatim (no rebuilt
  `CloudRunConfig`) and re-checks the C7.4 digest — which includes the account
  id — so a config or account change after Review blocks the launch.
  `current_cloud_bridge()` auto-resolves BYO credentials for the manual
  status/log/terminate/results buttons and `resolve_workspace_run_status`
  (BYO runs carry a non-secret `account_id` in metadata for re-attach after a
  refresh; no STS credentials are persisted). The **CLOUD RUN** card
  (`cloud_active_run_runtime.py`) renders `on_run_view` state changes and ticks
  elapsed time + `live_cost_usd(cost_public, elapsed)` once a second — purely
  local, no pricing call during the run; AWS status polling keeps its
  `CRYOSTACK_CLOUD_POLL_SECONDS` (default 20 s) cadence. `sync_cloud_results`
  gained a `credentials` param (scrubs ambient `AWS_*`, drops `--profile`).
- *Cost & runtime estimate (`cryostack_src/cloud/estimate/`, `cryostack_src/cloud/review.py`).*
  `resolve_fargate_prices(region)` queries the AWS Price List API from
  `us-east-1` and selects the priced region by `regionCode` attribute;
  results are cached ~6 h; any failure → `available=False` (never a fabricated
  price, never blocks Launch). `estimate_runtime()` prefers previous
  successful CryoStack runs → a curated `KNOWN_EXAMPLE_RUNTIMES` table → the
  configured time limit, each labelled. `estimate_cloud_cost()` returns a
  `CloudCostEstimate` with an `estimate_for_elapsed()` helper C7.5 reuses.
  `build_cloud_run_review()` renders from the **canonical**
  `CloudRunConfig.fargate` (same values the submit path uses — no second
  copy); `review_digest()` fingerprints the billable scientific + resource
  config so a change after the review opens forces a re-review before Launch.
  Launch gating: fresh AssumeRole verification + all infra Ready + supported
  model + config valid + preflight (ISSM needs a cloud-reachable MATLAB
  license — blocked honestly otherwise). Pricing uses ambient/host credentials
  by default (public, account-neutral data) — never the stored STS session.
- *CryoStack-provisioned IAM roles are `cryostack-*`* (`cryostack-batch-service-role`,
  `cryostack-ecs-execution-role`, `cryostack-job-role`) so they sit inside the
  cross-account role's `role/cryostack-*` scope and never collide with the
  PascalCase `CryoStackExecutionRole` the user creates. `iam.py` no longer
  matches `CryoStackExecutionRole` when discovering the ECS task-execution
  role. The C7.2 template was audited against every API call `bootstrap` +
  `prepare_batch` make; delta added: `iam:ListRoles`, `ecr:GetLifecyclePolicy`,
  `ecr:PutLifecyclePolicy` (checked-in artifact regenerated).
- *Implemented:* an end-to-end ISSM path — config + preflight, a user-owned
  working copy staged to `s3://<bucket>/runs/<safe-user>/<run-id>/`,
  `aws batch submit-job` (Fargate), lifecycle status/logs/terminate.
  Submission is non-blocking (`cloud_run_controller.CloudRunController`, the
  same asyncio worker pattern as the auto-tail log worker): the UI returns at
  once, the run auto-polls, and on completion the outputs sync into the user's
  run cache and render through the same Results panel every backend uses. All
  AWS calls go through the `aws` CLI; CryoStack stores no credentials.
  Job-definition selection is controlled (the model default or a known
  CryoStack name only). A license-neutral **infrastructure smoke test**
  (`cryostack_src.cloud.smoke`) checks identity + S3 + Batch + ECR reachability
  without submitting a job.
- *Requires qualification:* budget/quota/cleanup automation, failure-recovery
  tests, IAM tightening, and one real run on a controlled account.
- *Manual checkpoint:* `overnight/CLOUD_AWS_ACCEPTANCE.md` — provisioning and
  the first paid run are human-authorised.
- *ISSM cloud MATLAB licensing (config seam).* "Container image ready" is **not**
  "ISSM runtime ready". The combined image ships full MATLAB, but the campus
  network license server is unreachable from Fargate, so a cloud ISSM run needs
  its own license reachable from AWS. The seam
  (`cryostack_src/cloud/matlab_license.py`): the user creates an AWS Secrets
  Manager secret in **their own** account holding the `MLM_LICENSE_FILE` value
  and registers only its **ARN** on the `AWSConnection`
  (`matlab_license_secret_arn`, non-secret). `resolve_cloud_matlab_license()`
  turns that into a `containerProperties.secrets` entry
  (`{"name": "MLM_LICENSE_FILE", "valueFrom": <arn>}`) on the ISSM job
  definition, and AWS Batch injects the value at container launch. CryoStack
  never reads, logs, persists, or fingerprints the license value — only the ARN;
  `assert_not_a_license_value()` and the connect-security tests guard against a
  raw value ever reaching a manifest, command preview, or job-definition
  fingerprint. Review shows a distinct **ISSM runtime** row
  (`CloudRunReview.issm_runtime_ready`) that stays "Needs a MATLAB license"
  until the ARN is configured, independent of the container/compute rows.
- *Not enabled:* a real ISSM cloud run still needs that Secrets Manager ARN
  configured on the connection **and** a `secretsmanager:GetSecretValue` grant
  in the cross-account role for that ARN; preflight blocks it honestly until
  then. The ARN input field in Cloud Environment plus the end-to-end validation
  with a real license remain the externally-blocked remainder.

## Results and visualization

**Result package.** A completed run exports a transport-neutral package —
`outputs/{metadata.json, mesh, fields, model, figures}` — that can be read
without the original modelling stack. `discover_results()` and
`ResultPackage` present it to the gateway.

**Visualization.** Rendering is deterministic and operates only on the
neutral package: `render_field` and `render_timeseries` in
`cryostack_src/visualization/` back the Results panel's Solution / Field /
Timestep controls. Given the same package and selection, the output is
identical.

**Icepack Remote↔Cloud parity.** Icepack has one shared scientific entrypoint
regardless of backend: `cryostack_icepack_runner.py <script> <run-dir>`
(generated from `cryostack_src/models/icepack/export.py`). It forces a headless
`Agg` backend, executes the example **once** with `runpy.run_path`, captures
every live Matplotlib figure plus figure metadata to
`outputs/figures/_captured.json`, and runs the tier-1 allow-list structured
export from that same namespace. Cloud stages it via
`stage_example_for_run(extra_files=...)`; Remote stages it through the sbatch
heredoc — byte-identical helper text (`test_icepack_remote_cloud_parity.py`
asserts this). The stdlib collector `cryostack_icepack_postprocess.py` then
reports an honest status (`ok` / `artifacts` / `empty`). Provider-specific
execution (Slurm vs AWS Batch) differs; scientific and result behaviour do not.
`00-meshes-functions` correctly yields figures but no recognised tier-1 fields,
so the Solution / Field controls stay hidden — that is not a failure.

**Execution-provider vocabulary.** CryoLauncher distinguishes: *execution mode*
(Remote / Cloud / Local), *compute backend* (Remote → Slurm/HPC; Cloud → AWS
Batch (Fargate)), *model environment* (ICESEE-Spack or ICESEE-Container),
*model* (Icepack / ISSM), *container* (tag + immutable digest + provenance), and
*experiment* (selected example + source + run target). History cards, the Run
Plan, and manifests render these as separate rows and derive a historical run's
identity from its **persisted metadata**, never the current UI defaults — a
legacy widget such as `backend_dd` never determines cloud semantics.

## Testing

| Suite | Command |
|---|---|
| Python | `python -m pytest cryostack_src icesee_jupyter_book icesee_hpc_connector deployment` |
| Node (connector setup page) | `node --test deployment/tests/*.test.mjs` |
| Documentation | `jupyter-book build icesee_jupyter_book` |

**Source-guard tests.** Several tests assert on source text to prevent
regressions a unit test would miss — for example that neither gateway
reintroduces a personal default, that both still call the remote-access Run
gate, and that the shared responsive classes stay in the shared stylesheet.
When you rename or move code, update the corresponding guard.

**Gateway build tests.** The gateways are built end-to-end in tests with an
injected synthetic identity, so a broken widget tree fails fast without a
browser.

## Connector development

The CryoStack Connector is the small desktop application that bridges the
browser to a VPN-protected cluster over the relay.

**Architecture.** Pairing uses a versioned protocol: a `session_id` that is
not secret, a one-time `pairing_code`, and per-session secrets that
authenticate the connector's WebSocket. The relay never exposes a
"newest session" endpoint. On macOS the Cocoa main thread does UI only (menu,
onboarding/status window, a timer status poll) while **one** background
worker owns the HTTP pairing exchange, the WebSocket connect/reconnect, and
every SSH operation. The `.app` is built `--onedir` and ad-hoc signed so a
copy in `/Applications` is not subject to Gatekeeper App Translocation.

**Build one locally.** On the platform you are targeting (connectors cannot
be cross-compiled):

```bash
bash build_connector.sh
# headless Linux:
xvfb-run bash build_connector.sh
```

`build_connector.sh` first runs `scripts/build_brand_assets.py`, which
regenerates every icon and the shared header mark from the one canonical
`icesee_jupyter_book/cryostack.png`. Do not hand-edit those outputs.

Inspect the result:

```bash
ls -lh dist/packages/
cat dist/packages/CryoStack-Connector-<platform>.<ext>.build.json
```

The `.build.json` sidecar travels with the artifact:

| Field | Meaning |
|---|---|
| `platform` | canonical platform key (`linux-x86_64`, `macos-arm64`, …) |
| `filename` | canonical artifact filename |
| `sha256`, `size_bytes` | re-verified when the artifact is registered for release |
| `built_at` | UTC build time |
| `pairing_protocol` | the connector–relay pairing protocol the binary speaks |
| `connector_build_revision` | exact source revision (`git` short SHA, `-dirty` if modified) |

`pairing_protocol` matters: a connector built from source that predates a
protocol change cannot pair with the current relay, and release registration
refuses a mismatch. Publishing and releasing a built artifact is a
maintainer operation — see the Maintainer Guide.

**Known macOS issues (accepted for the current release).** Connector v2
pairing, direct launch, the menu bar, and the visible pairing/status window
all work. Two issues are deferred: a `/Applications` copy can become
unresponsive while a direct launch works (suspected App Translocation of the
ad-hoc-signed bundle; clear with
`xattr -dr com.apple.quarantine "/Applications/CryoStack Connector.app"`),
and paste into the pairing-code field is unreliable (type the code, or export
`CRYOSTACK_PAIRING_CODE`). `bash scripts/diagnose_connector_macos.sh` audits
translocation, quarantine, and signing state. Do not regress the working
direct-launch path while addressing these.

## Contribution workflow

1. Branch from `main`. Keep a change focused — one concern per commit, a
   couple of small related commits at most.
2. Match the surrounding code: naming, comment density, and idiom.
3. Run the full Python suite, the Node tests when connector-page code
   changed, and the book build when documentation changed. State plainly
   what passed and what was skipped.
4. Never introduce a personal default, a credential, or a secret — the
   source-guard tests reject the obvious cases, but the responsibility is
   yours.
5. Open a pull request against `main` describing what changed and how it was
   verified.

:::{raw} html
<div class="cryostack-docs-page">
  <footer class="cryostack-footer">

    <div class="cryostack-footer-main">

      <div class="cryostack-footer-brand">
        <div class="cryostack-footer-logo">CryoStack</div>
        <p>
          An integrated platform for cryosphere modeling, data assimilation,
          scientific visualization, and HPC-enabled research.
        </p>
      </div>

      <div class="cryostack-footer-group">
        <h3>Platform</h3>
        <a href="../index.html">Home</a>
        <a href="../documentation.html">Documentation</a>
        <a href="../resources.html">Resources</a>
        <a href="../about.html">About</a>
      </div>

      <div class="cryostack-footer-group">
        <h3>Applications</h3>
        <a href="/icesheets/">CryoLauncher</a>
        <a href="/icesee-gui/">ICESEE</a>
        <a href="/livist/">LIVIST</a>
      </div>

      <div class="cryostack-footer-group">
        <h3>Community</h3>
        <a href="https://github.com/ICESEE-project/CryoLauncher" target="_blank" rel="noopener noreferrer">GitHub</a>
        <a href="https://github.com/ICESEE-project" target="_blank" rel="noopener noreferrer">ICESEE Project</a>
        <a href="https://github.com/ICESEE-project/CryoLauncher/issues" target="_blank" rel="noopener noreferrer">Report an Issue</a>
      </div>

    </div>

    <div class="cryostack-footer-bottom">
      <div>Developed by ICCL and PGSL at the Georgia Institute of Technology.</div>
      <div class="cryostack-footer-meta">
        <span>© 2026 CryoStack</span>
        <span>BSD 2-Clause License</span>
      </div>
    </div>

  </footer>
</div>
:::
