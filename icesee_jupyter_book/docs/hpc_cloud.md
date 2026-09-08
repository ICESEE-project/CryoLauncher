# Cloud Run Guide

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>

<div class="cryostack-docs-page">

  <section class="cryostack-docs-hero">

    <div class="cryostack-section-label">
      CryoStack Documentation
    </div>

    <h1>Running on your own AWS account</h1>

    <p>
      How CryoStack launches, monitors, and retrieves the results of a run
      on AWS Batch — using an AWS account you connect yourself
      (bring-your-own-AWS), and the same application configuration you
      already use locally or on HPC.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="../applications/icesheets/user_manual.html#execution-modes-and-backends">
        CryoLauncher Cloud Reference
      </a>

      <a class="cryostack-btn secondary" href="../applications/icesee/user_manual.html#cloud-mode">
        ICESEE Cloud Mode
      </a>

      <a class="cryostack-btn secondary" href="developer_guide.html">
        Developer Guide
      </a>
    </div>

  </section>

  <section id="on-this-page" class="cryostack-section">

    <div class="cryostack-section-label">
      On this page
    </div>

    <h2>Where to go next.</h2>

    <p class="cryostack-section-intro">
      Cards navigate to the sections below. This page describes the
      platform-wide cloud execution path shared by CryoLauncher and ICESEE —
      application-specific fields and screens stay in each application's own
      User Manual.
    </p>

    <div class="cryostack-docs-summary-grid">

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">JM</div>
        <h3><a href="#the-cloud-run-journey">The cloud run journey</a></h3>
        <p>The real sequence: application, configuration, backend, AWS
           connection, launch, monitor, results.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">BK</div>
        <h3><a href="#what-stays-the-same-what-changes">Local, HPC, or Cloud</a></h3>
        <p>What is identical across backends, and what genuinely changes.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">AC</div>
        <h3><a href="#connecting-your-aws-account-byo-aws">Connecting your AWS account</a></h3>
        <p>CloudFormation onboarding, ExternalId, and temporary credentials.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">PC</div>
        <h3><a href="#preparing-cloud-infrastructure">Preparing cloud infrastructure</a></h3>
        <p>Prepare cloud: storage, container registry, and AWS Batch.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">RL</div>
        <h3><a href="#reviewing-and-launching-a-run">Review &amp; Launch</a></h3>
        <p>The run estimate, the review card, and what actually launches.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">MR</div>
        <h3><a href="#monitoring-a-run-and-retrieving-results">Monitoring &amp; results</a></h3>
        <p>Run states, logs, and how outputs come back to your Workspace.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">WE</div>
        <h3><a href="#worked-example-lorenz-96-on-aws">Worked example: Lorenz-96 on AWS</a></h3>
        <p>A concrete, step-by-step walkthrough on the one verified path.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">TS</div>
        <h3><a href="#troubleshooting-and-verification">Troubleshooting</a></h3>
        <p>Common failure points and how to verify your deployment.</p>
      </div>

    </div>

  </section>

  <section id="scope" class="cryostack-section">

    <div class="cryostack-section-label">Scope and status</div>
    <h2>What this page documents.</h2>

    <p class="cryostack-section-intro">
      This describes <strong>software that exists today</strong> — every
      button, label, and step name below matches the running application.
      Nothing here is a roadmap. "Cloud parity" is not one fact — it is
      four separate ones, and they are not all at the same maturity:
    </p>

    <div class="cryostack-docs-summary-grid">

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">SA</div>
        <h3>Shared architecture <span class="cryostack-status supported">Working</span></h3>
        <p>CryoLauncher and ICESEE both provision cloud infrastructure
           through the same <code>AWSDriver</code>/CloudFormation-onboarding
           architecture — one implementation, not two.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CP</div>
        <h3>Configuration portability <span class="cryostack-status supported">Working</span></h3>
        <p>The same scientific/example configuration (<code>params.yaml</code>,
           model settings) carries over across Local, Remote/HPC, and Cloud —
           there is no separate cloud-only configuration to maintain.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CE</div>
        <h3>Cloud exposure <span class="cryostack-status dev">Partial</span></h3>
        <p>CryoLauncher and ICESEE currently expose a Cloud execution mode in
           the UI. This is not true of every CryoStack application — do not
           assume a third application has a cloud path just because these
           two do.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">EV</div>
        <h3>End-to-end validation <span class="cryostack-status dev">Narrow</span></h3>
        <p>Exactly one configuration has been run and confirmed end-to-end:
           <strong>ICESEE Lorenz-96 at NP&nbsp;=&nbsp;1</strong>. CryoLauncher/ISSM
           has the onboarding, provisioning, and submission architecture
           implemented and exercised, but this page makes no claim of a
           fully verified live run-to-results cycle for it.</p>
      </div>

    </div>

    <p class="cryostack-section-intro">
      In short: CryoStack has backend/configuration parity at the
      <strong>architecture</strong> level today. Application-level
      <strong>operational validation</strong> — an actual completed run,
      end to end, on live AWS — is still expanding, one configuration at a
      time, and this page names exactly which one.
      <span class="cryostack-status planned">Not yet available</span>
      in-app teardown of AWS-side infrastructure (stack/role deletion) — see
      <a href="#cleanup">Cleanup</a> below for exactly what that does and
      does not cover.
    </p>

  </section>

</div>
:::

## The cloud run journey

CryoStack's cloud path follows the same shape as Local and Remote/HPC
execution — the application and its configuration do not change; only the
**execution backend** changes:

```text
 Application  →  Configuration  →  Compute backend  →  AWS connection
                                                              │
                                                              ▼
                    Results  ←  Monitor  ←  Launch  ←  Prepare cloud
```

This is the shared architecture, not a claim that Monitor/Results behave
identically in every application today: CryoLauncher uses an active
cloud-run controller that polls the job and synchronizes results
automatically after a successful completion, while ICESEE currently uses
explicit, manual status and result actions instead (details in
<a href="#monitoring-a-run-and-retrieving-results">Monitoring a run and retrieving results</a>).

In the application's own terms, this is:

:::{raw} html
<ol>
  <li>Open the application (CryoLauncher or ICESEE) and select an example.</li>
  <li>Configure it exactly as you would for a local or Remote/HPC run.</li>
  <li>In <b>Run settings</b>, set <b>Execution mode</b> to <b>Cloud</b>.</li>
  <li>Under <b>Cloud Environment → AWS ACCOUNT</b>, connect your AWS account
    (once) — see
    <a href="#connecting-your-aws-account-byo-aws">Connecting your AWS account</a>.</li>
  <li>Click <b>Prepare cloud</b> to provision what your account needs — see
    <a href="#preparing-cloud-infrastructure">Preparing cloud infrastructure</a>.</li>
  <li>Click <b>Review &amp; Launch</b>, then <b>Launch cloud run</b> — see
    <a href="#reviewing-and-launching-a-run">Reviewing and launching a run</a>.</li>
  <li>Watch the <b>CLOUD RUN</b> status card, then open <b>Results</b> — see
    <a href="#monitoring-a-run-and-retrieving-results">Monitoring a run and retrieving results</a>.</li>
</ol>
:::

## What stays the same, what changes

:::{raw} html
<div class="cryostack-docs-page">
  <section class="cryostack-section">

    <div class="cryostack-docs-environments">

      <div>
        <h3>Configuration <span class="cryostack-status supported">Identical</span></h3>
        <p>
          The example, model parameters, filter/solver settings, ensemble
          size, and dataset references are the same object regardless of
          backend. There is no separate "cloud version" of a scientific
          configuration to create or maintain.
        </p>
      </div>

      <div>
        <h3>Local</h3>
        <p>
          Runs inside the CryoStack server process itself. No connection,
          no queue — the fastest path for small runs and iteration.
        </p>
      </div>

      <div>
        <h3>Remote / HPC</h3>
        <p>
          Runs on a Linux server or Slurm-managed cluster you already have
          access to, through the CryoStack Connector or direct SSH. Adds:
          your HPC identity, a remote working directory, and (for ICESEE)
          a first-time Spack environment Check/Prepare step.
        </p>
      </div>

      <div>
        <h3>Cloud</h3>
        <p>
          Runs on AWS Batch, in <strong>your own</strong> AWS account. Adds:
          connecting the account once, letting CryoStack prepare the AWS
          infrastructure, and reviewing an estimated cost before launch. It
          does not add a different scientific workflow.
        </p>
      </div>

    </div>

  </section>
</div>
:::

## Connecting your AWS account (BYO-AWS)

CryoStack never asks for an AWS access key, secret, or CLI profile. Instead,
you create a cross-account IAM role yourself, in your own AWS console, and
CryoStack assumes it for short-lived (temporary) credentials only.

1. In **Cloud Environment → AWS ACCOUNT**, click **Connect AWS Account**.
2. Click **Open AWS Setup**. This opens a CloudFormation *Quick Create* page
   in your own AWS console, pre-filled with a unique **ExternalId** (a
   confused-deputy defence — the role can only be assumed with this exact
   value) and the CryoStack principal it should trust. Review the stack and
   click **Create stack**.
3. The stack creates one IAM role scoped to `cryostack-*` resources only —
   no `AdministratorAccess`, no wildcard actions. Copy the **Role ARN** from
   the stack's **Outputs** tab.
4. Paste the Role ARN back into CryoStack and click **Verify connection**.
   CryoStack assumes the role with your ExternalId, confirms your account,
   and shows **● Connected**.

Each CryoStack connection gets its **own** CloudFormation stack and its own
IAM role — connecting a second AWS identity, or reconnecting after a
previous attempt didn't finish, never requires deleting an existing,
working role first.

```{note}
**Retry connection** (after a failed verification) and **Change AWS
account** (to connect a different account without losing the current one)
are separate, explicit actions in the AWS ACCOUNT panel — see the
CryoLauncher User Manual's <a href="../applications/icesheets/user_manual.html#connect-aws-account">Connect AWS Account</a>
walkthrough for every button and state in detail.
```

**Disconnect** removes only the connection metadata CryoStack stored
locally. There are no long-lived credentials to revoke — STS sessions are
short-lived and are never stored. It does not delete anything in your AWS
account.

## Preparing cloud infrastructure

Once connected, click **Prepare cloud**. Using your temporary role session,
CryoStack creates whatever is missing in **your** account — nothing is
created in a CryoStack-owned account:

- an S3 bucket for run input/output (`cryostack-runs-<your-account-id>`);
- an ECR repository holding the exact, digest-pinned tested container image;
- an AWS Batch compute environment, job queue, and job definition.

The **Account / Storage / Containers / Compute** rows move to **Ready** as
each step completes. **Prepare cloud is safe to run again** — existing
resources are reused, never recreated or duplicated.

## Reviewing and launching a run

Once infrastructure is **Ready**, a **RUN ESTIMATE** appears (expected
runtime, requested resources, and an estimated AWS cost when pricing is
available). Click **Review & Launch** to open the full review card, which
shows the experiment, the AWS account and region, the resources, and an
infrastructure-readiness checklist. **Launch cloud run** is only enabled
once every check passes — CryoStack never launches a configuration it
cannot honestly claim is ready, and it asks you to review again if you
change anything after opening the review.

AWS charges apply to your own AWS account for whatever the run actually
uses; cost figures shown here are estimates only, not a bill.

## Monitoring a run and retrieving results

The underlying job passes through the same states either way:

```text
Staging → Submitting → Queued → Running → Completed
                                        ↘ Failed
                                        ↘ Cancelled
```

**How you observe those states, and how results come back, currently
differs by application — this is a real implementation difference, not an
unvalidated version of the same behavior:**

- **CryoLauncher** shows a **CLOUD RUN** card that tracks the job without
  blocking the interface. **View log** opens the run's live log in the
  Workspace **Run Log** tab; **View results** opens the Workspace
  **Results** tab once the run has reached **Completed**; **Terminate**
  stops a running job, with a confirmation step. Behind this card,
  `CloudRunController` (`icesee_jupyter_book/ui/icesheets_gateway.py`)
  polls the job in the background and, on reaching **Completed**,
  automatically syncs its S3 outputs into your local run cache — no click
  required before Results is populated.
- **ICESEE** does not use that controller or that card. There is no
  background poller — you click **Check status** yourself to see whether a
  job has finished (it prints the current AWS Batch state to the Run Log).
  Opening a completed cloud run from the Workspace **Runs** list then
  triggers a best-effort sync of its S3 outputs into your local run cache
  before showing Results. (ICESEE does have a job-termination capability
  in its cloud code path; this page does not name a specific button label
  for it until that label is verified against the running UI.)

## Worked example: Lorenz-96 on AWS

This is the one path verified end-to-end against the current container
image. Steps this platform does not yet support are called out explicitly
rather than skipped over.

1. **Open ICESEE** and select the **Lorenz-96** example.
2. Leave its configuration at the default (or your own edits) — the same
   `params.yaml` used for a local or Remote run.
3. In **Run settings**, set **Execution mode** to **Cloud**.
4. If you have not connected an AWS account yet, follow
   <a href="#connecting-your-aws-account-byo-aws">Connecting your AWS account</a> now.
   CloudFormation onboarding happens in a separate browser tab — your AWS
   console — not inside CryoStack.
5. Return to CryoStack and click **Verify connection**; confirm the panel
   shows **● Connected**.
6. Click **Prepare cloud** and wait for **Account / Storage / Containers /
   Compute** to all read **Ready**.
7. Set **Processes** to **1** — this is the only value CryoStack will let
   you launch today for ICESEE (see
   <a href="#icesees-verified-runtime-contract">ICESEE's verified runtime contract</a>
   below).
8. Click **Review & Launch**. Confirm the card reads
   **ICESEE runtime: Ready**, **Parallel mode: Single-rank verified**,
   **Processes: 1** — this is CryoStack's own honest preflight check, not a
   cosmetic label.
9. Click **Launch cloud run**.
10. ICESEE does not poll AWS in the background — click **Check status** in
    the Run Log toolbar whenever you want to know whether the job has
    finished. It prints the current AWS Batch state (e.g. `RUNNABLE`,
    `RUNNING`, `SUCCEEDED`) to the Run Log.
11. Once status reads `SUCCEEDED`, open the run from the Workspace **Runs**
    list. Selecting it triggers a best-effort sync of its S3 outputs into
    your local run cache, then shows Results — figures and fields render
    the same way a local run's results do.
12. To change anything (ensemble size, seed, observation settings), edit
    the configuration and repeat from step 8 — a new review is always
    required before a changed configuration can launch.
13. See <a href="#cleanup">Cleanup</a> below before you consider the run
    finished — nothing about the AWS infrastructure this used is removed
    automatically.

## Cleanup

Cleanup is not one action — CryoStack handles some of it, and some of it is
entirely manual today:

- **Individual Batch jobs** — CryoLauncher's **Terminate** button, and
  ICESEE's own cloud termination action, stop a running or queued job
  directly from CryoStack. This works today.
- **AWS job history** — nothing to do; AWS retains completed/terminated job
  records at no ongoing cost. CryoStack does not need to (and does not)
  clean these up.
- **S3 input/output objects** — **not deleted automatically.** Every run's
  staged inputs and outputs persist in your S3 bucket until you remove them
  yourself.
- **AWS Batch resources** (compute environment, job queue, job
  definitions) — created once by Prepare cloud and reused afterward.
  **There is currently no in-app "unprepare" or teardown action.**
- **Disconnecting an AWS account** (the **Disconnect** button) — removes
  only CryoStack's local connection record (ExternalId, role ARN,
  metadata). **It does not delete or modify anything in AWS.**
- **The CloudFormation stack and its IAM role** (from Connecting your AWS
  account) — **not deleted through CryoStack.** If you want to tear down a
  connection's AWS infrastructure entirely, delete the stack yourself from
  the AWS Console or CLI; deleting it removes the IAM role with it.

## ICESEE's verified runtime contract

ICESEE's cloud container has been verified, locally and against the exact
published image, for exactly:

- **Example:** `lorenz96`
- **Processes (`ICESEE_NP`):** `1`

Multi-process execution was tested and found unsafe on this image (the
default execution path has no coordination between MPI ranks and races on
shared output files), and no example other than Lorenz-96 has been run
against the cloud container. CryoStack's Review card enforces this directly
— a different example or a higher process count is **refused with an
explicit reason**, never silently changed to a value that would pass. This
is a deliberate design choice: the goal is an honest preflight, not a
best-effort launch.

## Screenshots

```{admonition} Screenshots not yet captured
:class: note
The repository does not yet contain screenshots for this workflow. The UI
is stable enough to capture now; the following would materially improve
this page and are listed in capture order:

1. **AWS ACCOUNT** panel before connecting (the "Connect AWS Account" state).
2. The CloudFormation Quick Create page, pre-filled, in the AWS console.
3. **AWS ACCOUNT** panel showing **● Connected** with account ID.
4. **Prepare cloud** in progress, then Account/Storage/Containers/Compute
   all **Ready**.
5. The **Review cloud run** card for the Lorenz-96 / Processes = 1 example,
   showing **ICESEE runtime: Ready**.
6. The **CLOUD RUN** status card mid-run (**Running**).
7. The Workspace **Results** tab after a completed cloud run.

Until these are captured, no screenshots are embedded on this page —
inserting placeholders styled as real screenshots would be misleading.
```

## Downloads and reference material

- **CloudFormation template source** —
  `deployment/cloudformation/cryostack-execution-role.json` in the
  CryoStack repository is the exact source of the template your
  administrator publishes at the URL CryoStack opens during
  **Open AWS Setup**. See
  <a href="#preparing-cloud-infrastructure">Preparing cloud infrastructure</a> above
  for what it creates.
- **Example configuration** — the Lorenz-96 example's `params.yaml` (the
  same file used for Local, Remote, and Cloud execution):

  ```yaml
  modeling-parameters:
    example_name: "lorenz96"
    dt: 0.01
    num_years: 10
    timesteps_per_year: 2

  enkf-parameters:
    Nens: 30
    filter_type: "EnKF"
    model_name: "lorenz"
    parallel_flag: "serial"
  ```

- [CryoStack on GitHub](https://github.com/ICESEE-project/CryoLauncher) —
  browse the full source, including the CloudFormation template and the
  cloud execution code referenced throughout this page.

## Troubleshooting and verification

**"Resource of type 'AWS::IAM::Role' ... already exists" during stack
creation.** This was a real defect in an earlier template revision (a fixed
role name collided across connections) and has been fixed — CloudFormation
now generates a unique role name per stack. If you still see this error,
your deployment's published template may be stale; ask your administrator
to confirm it matches the checked-in
`deployment/cloudformation/cryostack-execution-role.json`
(`sha256sum` the two files and compare).

**A CloudFormation stack is stuck in `ROLLBACK_COMPLETE`.** Retrying with
the exact same stack name is refused by AWS once a stack has failed. Use
**Retry connection**, not a manual re-submission of the same Quick Create
URL — CryoStack mints a fresh, non-colliding stack name for the same
connection without changing your ExternalId or an already-working role.

**Launch is disabled and the review lists a reason.** This is intentional —
read the listed reason (infrastructure not yet Ready, account connection
stale, or an unverified example/process count for ICESEE) rather than
retrying blindly; each reason names exactly what to fix.

## Related documentation

- [CryoLauncher User Manual — Execution modes and backends](https://cryostack.eas.gatech.edu/applications/icesheets/user_manual.html#execution-modes-and-backends)
- [ICESEE User Manual — Cloud Mode](https://cryostack.eas.gatech.edu/applications/icesee/user_manual.html#cloud-mode)
- [Developer Guide](https://cryostack.eas.gatech.edu/docs/developer_guide.html)
- [CryoStack Documentation](https://cryostack.eas.gatech.edu/documentation.html)

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
