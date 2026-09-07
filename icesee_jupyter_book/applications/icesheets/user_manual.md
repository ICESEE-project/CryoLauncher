# CryoLauncher User Manual

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>

<div class="cryostack-app-doc-page">

  <section class="cryostack-app-doc-hero">

    <div class="cryostack-section-label">
      CryoLauncher Documentation
    </div>

    <h1>CryoLauncher User Manual</h1>

    <p>
      The operational guide to configuring models, editing examples in your
      own workspace, managing datasets, launching runs on remote resources,
      and exploring structured results.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="/icesheets/">
        Open CryoLauncher
      </a>

      <a class="cryostack-btn secondary" href="getting_started.html">
        Getting Started
      </a>

      <a class="cryostack-btn secondary" href="resources.html">
        Resources
      </a>
    </div>

  </section>

  <div class="cryostack-app-doc-content">
:::

## 1. CryoLauncher overview

CryoLauncher is the numerical-modeling application in CryoStack. It runs in a
browser and gives you one consistent workflow for supported ice-sheet models:
choose a model and example, configure it, submit it to a computing resource,
monitor it, and explore the results.

The interface has two areas:

:::{raw} html
<div class="cryostack-manual-grid">

  <article class="cryostack-manual-card">
    <div class="cryostack-manual-number">01</div>
    <h3>Run settings</h3>
    <p>
      Model, example, Basic/Advanced mode, execution mode and backend, the
      guided configuration panel or the file editor, datasets, and the
      computing-resource settings.
    </p>
  </article>

  <article class="cryostack-manual-card">
    <div class="cryostack-manual-number">02</div>
    <h3>Workspace</h3>
    <p>
      Run history and status, per-run files, the run log, and the Results tab
      with the field-visualization panel and download controls.
    </p>
  </article>

</div>
:::

## 2. Applications and maturity

:::{raw} html
<p>
  <b>ISSM</b> <span class="cryostack-status supported">Supported</span><br>
  The Ice-sheet and Sea-level System Model. This is the mature CryoLauncher
  path: guided configuration, per-user example staging, structured result
  export, and deterministic visualization are all implemented and tested.
</p>
<p>
  <b>Icepack</b> <span class="cryostack-status dev">Experimental</span><br>
  Selectable in the interface. Example discovery, per-user workspace
  editing/cloning, dataset staging, tested-container selection, Slurm
  configuration and validation, remote/HPC submission, run history, provenance,
  and Results/Figures downloads all work the same way they do for ISSM. After a
  run, CryoLauncher collects the figures and native output files the example
  produced into the standard results package, and the Results tab shows them.
</p>
<p>
  What is <b>not</b> yet at ISSM parity, because it depends on model-specific
  science decisions still in review:
</p>
<ul>
  <li><b>Basic-mode curated configuration.</b> ISSM Basic mode edits the
  <code>md</code> model struct; Icepack configuration is Python
  (Firedrake <code>Function</code>s, solver options), which needs its own
  curated parameter set. Use Advanced mode (edit the notebook/script directly)
  for Icepack today.</li>
  <li><b>Structured field visualization.</b> The Results tab shows collected
  figures and output files but not an interactive field/timestep viewer —
  Firedrake results are function-space DOF vectors, not the ISSM
  solution/field/timestep structure the viewer is built on.</li>
  <li><b>Cloud (AWS Batch) execution.</b> ISSM only for now.</li>
</ul>
<p>
  These are tracked as explicit science checkpoints, not left vague. Treat
  Icepack runs as exploratory.
</p>
:::

Basic and Advanced are **CryoLauncher-wide application modes**, not model
modes. ISSM is simply the first model implemented to full maturity behind
them.

## 3. Basic mode

Basic mode is a **guided scientific-configuration surface**. It is not a raw
model-code editor.

- **Guided configuration.** You are shown a small, curated set of parameters,
  not the full model object.
- **Solver-aware.** The panel only offers parameters that are relevant to the
  solver the selected example actually runs. For ISSM this includes
  stressbalance tolerances (`restol`, `reltol`, `abstol`) and `maxiter`, time
  stepping (`time_step`, `final_time`), transient physics toggles
  (stress balance / mass transport / thermal / grounding line / moving front /
  SMB), a friction-coefficient multiplier, an ice-rigidity (rheology&nbsp;B)
  multiplier, and curated extra requested outputs.
- **Opt-in.** Nothing changes unless you explicitly enable a parameter and set
  a value. Spatial fields such as friction or rheology&nbsp;B are applied as a
  multiplier on the existing field, never replaced by a scalar.
- **Defaults preserved.** Every parameter you do not touch keeps the value
  from the example. Basic mode never rewrites example defaults you did not ask
  it to change.
- **Validated before execution.** Each value is range- and type-checked. If a
  value is out of range or malformed, the run is blocked with a clear message
  before anything is submitted.
- **Safe staging.** When you run a Basic-mode configuration against a
  read-only application example, CryoLauncher automatically stages a
  user-owned working copy under your workspace, injects the validated
  overrides into that copy immediately before the solve, and leaves the
  canonical example untouched. If the example is already one of your own, the
  overrides are applied to it in place.

### Basic mode for Icepack

Icepack examples are Firedrake/Python notebooks, not an ISSM `md` model object,
so the curated set is different and deliberately small. Two parameters are
exposed today, both scalars with an unambiguous physical meaning that every
flow tutorial sets the same way:

- **Ice temperature** (`T`, kelvin, 200&nbsp;K – pressure-melting point). Sets
  the depth-averaged temperature from which Icepack derives the ice fluidity.
- **Number of timesteps** — the length of the time-integration loop, only where
  the example sets it as a plain literal (it does not change the physics or the
  timestep size).

The same guarantees apply: the value is range-checked before submission; the
override is a single, exact, commented line change in a user-owned working
copy; the canonical example is never modified; run provenance records exactly
which line changed from what to what. **If the selected Icepack example does
not set the parameter as a plain literal** (for example a temperature written
as an expression, or a timestep count derived from `num_years ×
timesteps_per_year`), the run is blocked with a clear message rather than run
with a silently-ignored value — use Advanced mode to edit that example
directly. No ISSM parameter names or `md` semantics are used for Icepack.

## 4. Advanced mode

Advanced mode is a **model-neutral workspace and file editor** for modifying
examples and files directly.

- **Canonical examples are read-only.** Application examples shipped with a
  model cannot be edited, renamed, or deleted. Opening a file from one shows
  it disabled.
- **Clone to My Workspace.** To edit an application example, clone it. The
  copy lands under your personal workspace as a fully user-owned example.
- **Editor lifecycle.** Open a file, edit it, and use **Save**, **Save As**
  (a new file inside your workspace), **New file**, and **Delete**. A
  **Refresh** control re-reads the file list.
- **Unsaved-change protection.** Switching file, example, model, or
  Basic↔Advanced is blocked while the editor has unsaved changes, unless you
  tick **Discard unsaved changes**. Basic↔Advanced preserves the Advanced
  buffer.
- **User examples.** Create a new example, **Rename** it, or **Delete** it.
  New examples are minimal user-owned directories; if the model adapter
  provides a starter template it is used.
- **Persistence.** User examples, files, and datasets persist across page
  reloads and sessions. Reloading rediscovers them.
- **User isolation.** Everything you create lives under your authenticated
  user's workspace. Another user cannot discover, open, edit, run, rename, or
  delete your examples or files. Canonical examples remain globally visible
  and read-only for everyone.
- **Notebooks.** `.ipynb` files are shown read-only as notebook JSON in this
  version; they are never silently converted to `.py`.

## 5. Application examples vs My Workspace

The **Example** menu merges two kinds of entry, and each entry is labelled as
canonical/read-only or user-owned/editable:

- **Application examples** — the canonical examples shipped with the model
  (for ISSM, `SquareIceShelf` is the recommended first example). Globally
  visible, read-only.
- **My Workspace examples** — examples under your personal workspace. Editable,
  private to you, and persistent.

Only directories that look like a real runnable example are offered — utility
folders such as `Data/`, `Mesh/`, or `Functions/` are filtered out of the
picker.

You do **not** need to clone before a Basic-mode run: changing a Basic-mode
parameter automatically stages a working copy. Clone explicitly when you want
to **edit files** in Advanced mode.

## 6. Creating, cloning, and editing user examples

| Action | What it does |
|---|---|
| Clone to My Workspace | Copies a canonical (or another user-owned) example into `My Workspace / examples / <model> /` with provenance recording the source. |
| New example | Creates a minimal user-owned example directory (with a model starter template if one exists). |
| Rename example | Renames one of your user examples; provenance and the path are updated. |
| Delete example | Removes only that user example. Canonical examples cannot be renamed or deleted. |

User-example names are validated — path separators, `..`, leading dots, and
absolute paths are rejected.

Deleting a user example never deletes reusable datasets, and deleting a run
never deletes examples or datasets.

## 7. Dataset management

Datasets are **reusable input files that live independently of any run or
example**, in your personal dataset area.

- **Upload.** Use the uploader to add one or more files at once. Scientific
  formats (`.mat`, `.h5`, `.nc`, `.csv`, `.dat`, `.exp`, `.txt`, `.json`,
  `.yaml`, …) are all accepted; there is no restrictive extension list. Very
  large files that exceed the browser upload size are reported clearly. Each
  file has a size cap suited to the widget uploader (50&nbsp;MB).
- **List and refresh.** Datasets appear in the explorer immediately. They are
  visible even when they are not text-editable — a distinction is made between
  *visible file* and *editable text file*.
- **Overwrite protection.** Re-uploading a file with the same name is skipped
  unless you tick **Overwrite existing**.
- **Reference from an example.** From one of your user examples, **Reference
  in example** links a dataset (optionally under a chosen relative path). This
  records a reference; it does not copy the file yet.
- **Run staging.** When you run an example that references datasets, each
  referenced dataset is copied into the run's working copy under
  `data/<as>`, and the run's provenance records what was staged. The original
  dataset stays in your dataset area.
- **Delete / unreference.** Deleting a dataset requires confirmation and
  verifies ownership. Removing a reference does not delete the dataset.
  Deleting a dataset that an example still references warns you that the
  reference may become invalid; it does not touch the example's other files.
- **Isolation.** Another user cannot discover, read, reference, rename, or
  delete your datasets.

## 8. Execution modes and backends

**Execution mode** (in Run settings):

:::{raw} html
<p>
  <b>Remote</b> <span class="cryostack-status supported">Supported</span>
  &nbsp;— run on a Linux server or HPC cluster <b>you</b> have access to,
  through the CryoStack Connector (recommended) or direct SSH. Configure access
  with your own HPC identity — see
  <a href="#configure-access-to-your-hpc-system">Configure access to your HPC
  system</a>. Slurm resource settings appear when the resource is
  scheduler-managed.
</p>
<p>
  <b>Cloud</b> <span class="cryostack-status dev">In development</span>
  &nbsp;— run on <b>your own</b> AWS account and credits. You connect the
  account once (<b>Connect AWS Account</b> → <b>Open AWS Setup</b> → create the
  CryoStack access role → <b>Verify</b>), CryoStack prepares the required
  infrastructure, and you review an estimated cost before launching. CryoStack
  uses <b>temporary role access</b> and never stores your AWS access keys — you
  are never asked to paste an access key, a secret, or a CLI profile. Real
  cloud execution has not yet been accepted end-to-end; do not depend on Cloud
  for production work yet.
</p>
:::

### Connect AWS Account

1. In <b>Cloud Environment → AWS ACCOUNT</b>, click <b>Connect AWS Account</b>.
2. Click <b>Open AWS Setup</b>. A CloudFormation <i>Quick Create</i> page opens
   in your AWS console, pre-filled with a unique <i>ExternalId</i> and the
   CryoStack principal. Review it and create the stack — it adds one IAM role,
   <code>CryoStackExecutionRole</code>, with least-privilege access scoped to
   <code>cryostack-*</code> resources.
3. Copy the role ARN from the stack's <b>Outputs</b> tab
   (<code>arn:aws:iam::&lt;account&gt;:role/CryoStackExecutionRole</code>),
   paste it back into CryoStack, and click <b>Verify connection</b>.
4. CryoStack assumes the role with your ExternalId, confirms the account, and
   shows <b>● Connected</b> with your account ID and <i>Access: Temporary
   role</i>.
5. Click <b>Prepare cloud</b>. Using temporary role access, CryoStack derives
   the storage bucket (<code>cryostack-runs-&lt;account-id&gt;</code>), queue
   and job definition and creates whatever is missing <b>in your account</b> —
   S3 storage, the container repository, and the Batch compute environment.
   The panel shows <b>Storage / Containers / Compute</b> moving to <b>Ready</b>.
   Prepare cloud is safe to run again; existing resources are reused, not
   recreated. Detailed provisioning output goes to the Run Log.
6. Once everything is <b>Ready</b>, a <b>RUN ESTIMATE</b> appears — expected
   runtime, the resources the run will request (e.g. 2 vCPU · 8 GiB), and an
   estimated AWS cost. Click <b>Review &amp; Launch</b> to see the full
   <b>Review cloud run</b> card (experiment, account, resources, expected
   runtime, estimated cost with its basis and price-check time, and
   infrastructure readiness), then click <b>Launch cloud run</b> to start.
   Launch is always an explicit action; if you change the example, resources
   or a model parameter after opening the review, CryoStack asks you to review
   the updated estimate again before launching.
7. A <b>CLOUD RUN</b> card then shows live status
   (<i>Staging → Queued → Running → Completed</i>), the AWS account and region,
   the resources, an elapsed timer, an estimated cost so far, and the expected
   runtime. It updates while the run proceeds without blocking the interface.
   All of the run's AWS work (staging, submission, status, logs, termination,
   result retrieval) uses a short-lived role session in <b>your</b> account.
   <b>View log</b> opens the run's log in the Workspace Run Log tab (the same
   live-tail view every run uses); <b>View results</b> (enabled on completion)
   opens the Workspace Results tab. <b>Terminate</b> stops a running job (with a
   confirm step). On completion, CryoStack retrieves the outputs into your run
   cache automatically and Results renders them.

Cost figures are <b>estimates</b>. AWS charges apply to your AWS account; AWS
promotional/free-tier credits, billing rules and payment methods are managed by
AWS (check your AWS Billing &amp; Cost Management console for your credit
balance). If a price cannot be retrieved, CryoStack shows "Cost estimate
unavailable" and still lets you launch.

<b>Disconnect</b> removes the stored connection metadata only. There are no
credentials to revoke — STS sessions are short-lived and are never stored.
Running <code>aws configure</code> or setting up a CLI profile is <b>not</b>
required for this path; that is a developer-only workflow (see the Developer
Guide).

**Backend** (under Remote):

- **ICESEE-Container** — run inside a container. The container source can be:
  - **Docker / OCI** with a *tested* image — the validated container path;
  - **Local SIF** — a pre-built `.sif` on the remote resource;
  - **ICESEE-Containers (git)** — build from the container definitions.
- **ICESEE-Spack** — run against a Spack-managed software environment on the
  remote resource. First-time use requires onboarding (Section&nbsp;10).

The tested-image path pins the container by a verified digest so the software
stack is reproducible.

## 9. Configure access to your HPC system

### The trust model

CryoStack does **not** create an HPC account and does **not** replace your
institution's authentication. You must already have your own access to the
target resource. CryoStack then acts entirely as **you**:

- your own **HPC username**
- your own **allocation / account**
- your own **remote working directory**
- your own **SSH credential** (a key CryoStack generates *for you*, scoped to
  your identity)

Runs never execute through a CryoStack developer's account or a shared
identity. Before any remote run, CryoStack checks the **remote** username the
resource reports and **blocks the run** when it does not match the HPC username
you configured (see *Check SSH Access* and *Run protection* below).

Your settings are stored **per CryoStack user × per compute resource** — another
user configuring the same resource never sees or reuses your username,
directory, allocation, or key.

### Where you configure it

**Run settings → Remote Connection**, laid out around your workflow:

| Group | Fields |
|---|---|
| **Compute resource** | Resource, Host, Port |
| **Your HPC identity** | HPC username, Remote working directory |
| **Access** | Connection method, Authentication method |
| **Status** | ● Not checked / Checking… / Verified / Mismatch / Failed |

with **[ Check SSH Access ]** and **[ Open Connector Setup ]**, a **CryoStack
Connector** card, and a **Diagnostics** section for the session id and relay
details. Resource facts (host, port, scheduler defaults, VPN/MFA requirements)
come from the resource's profile; the identity fields start blank and only ever
hold *your* values.

### Recommended path — the CryoStack Connector

For clusters behind a campus network or VPN, the recommended **Connection
method** is the **CryoStack Connector**: a small desktop app on *your*
workstation that carries CryoStack's SSH through your existing network access.

1. **Remote Connection → Connection method: CryoStack Connector.**
2. Click **Open Connector Setup** — CryoStack creates a pairing session and
   shows a **pairing code** on the **CryoStack Connector** card.
3. On the setup page (`/connect/`), **download the connector for your
   platform**. The offered downloads are exactly the platforms listed in
   `/downloads/connectors/manifest.json`; if your platform is not listed, a
   build has not been published for it yet — check
   [/downloads/connectors/](https://cryostack.eas.gatech.edu/downloads/connectors/).
4. **Install / launch** the connector.
5. **Pair** — the connector pairs with your most recent CryoStack session
   automatically; if it was already running, quit and relaunch it, or enter the
   pairing code from the card into the connector's pairing field.
6. The **CryoStack Connector** card then shows **Connected**.
7. Fill in **HPC username** and **Remote working directory**, set up your SSH
   key (below), and click **Check SSH Access** until it shows **Verified**.

The pairing code is one-time, expires with the session, and is never added to a
download link.

**Known macOS notes (honest, not blocking normal use):** the macOS connector
can be launched directly from the downloaded disk image. Copying it into
`/Applications` has a known responsiveness issue on some systems, and
copy/paste into the pairing field is still being polished — type the code, or
run the connector from the disk image, if either bites.

### Direct SSH from server

**Direct SSH from server** connects from the CryoStack server straight to the
resource using a **shared, server-side identity**. It is a **developer /
shared-trust mode**, not the normal multi-user path — use it only for a
single-tenant deployment or local development. Everyone else should use the
Connector.

### SSH keys

CryoStack generates a dedicated SSH key for you, **namespaced by compute
resource + your HPC username** (and, on the CryoStack server, by your CryoStack
user). It is stored under `~/.ssh/cryostack/` on the machine that owns it —
your workstation for the Connector, the server for Direct SSH. One CryoStack
user's key is never reused as another user's credential. An older cluster-only
key from a previous version (`~/.ssh/id_ed25519_icesee_<cluster>`) is shown for
reference but never adopted; re-register once.

```
Generate / View your CryoStack SSH public key
        ↓
register the PUBLIC key with the HPC resource
        ↓
Check SSH Access  →  Verified
```

- The **public key** (the `...pub` file — one line starting `ssh-ed25519 …`)
  is safe to give to the HPC service.
- The **private key** must **never** be copied into an HPC portal, pasted into
  a website, emailed, or shared. CryoStack never asks you for it, and never
  asks for a portal password.

How the public key is registered depends on the resource's **Authentication
method**:

#### SSH key

Where the resource allows key installation over SSH, choose **Authentication
method: SSH key**, seed it once with **Password bootstrap** (below), then Check
SSH Access.

#### Password bootstrap (one-time)

For resources that support it, choose **Authentication method: Password
bootstrap**:

1. Enter your HPC account password in the one-time field.
2. Click **Enable passwordless SSH**.

CryoStack uses the password **once** to append your CryoStack public key to
`~/.ssh/authorized_keys` on the resource. The password is **typed input only —
it is not stored** and is not written anywhere. When it succeeds, switch back
to **SSH key** and Check SSH Access. Password bootstrap does not work on every
HPC system (some disable password SSH, or require MFA) — if it fails, use
manual registration.

#### Manual / web-portal registration

Some HPC systems do not allow a key to be installed over SSH — you register it
through an account-management website (for example sites like the University at
Buffalo CCR, where you add authorized keys on a portal). CryoStack shows a
**Register your key** checklist for these resources:

1. **Generate / view** your CryoStack public key.
2. **Copy** the *public* key.
3. Sign in to **your institution's HPC / account portal**.
4. Find **SSH keys / authorized keys / access keys**.
5. **Add** the public key.
6. **Save / apply** the change.
7. **Return to CryoStack.**
8. Click **Check SSH Access.**

The exact portal and menu names differ by institution. If the resource's
profile carries a portal URL, CryoStack links it directly; otherwise it shows
these neutral steps. **CryoStack never asks for the portal's web password.**

### VPN, MFA, campus network

Some resources require an **institutional VPN**, **multi-factor
authentication**, or being **on a campus network** before SSH works at all.
These are **resource requirements, not CryoStack credentials** — CryoStack
cannot satisfy them for you. When the resource's profile declares them,
CryoStack shows the requirement beside the resource. Because the CryoStack
Connector runs on your workstation, it naturally inherits your VPN / campus
network.

### SSH agent

An **SSH agent** authentication option appears only for resources whose profile
declares agent support. No currently configured resource does, and the
**CryoStack Connector uses a dedicated key file, not your ssh-agent**. (The
server-side SSH Key Manager has an *Add Key to Agent* action for the server's
own agent, used only by the Direct SSH path.)

### Remote working directory

The **Remote working directory** is the location *on the HPC system* where
CryoStack stages each run's files and reads back results. It must be
**writable by your HPC identity**. Use a path you own, for example:

```
~/projects/cryostack
/scratch/<your-username>/cryostack
```

Prefer a filesystem with enough quota for run inputs and outputs (often a
`scratch` or `work` area rather than `home`). If the directory is missing or
not writable, CryoStack fails the run with a clear message — it never falls
back to another location.

### Slurm resources

When the resource is scheduler-managed, a **Slurm resources** panel appears,
grouped as:

| Group | Fields |
|---|---|
| **Job settings** | Job name, Wall time |
| **Compute resources** | Nodes, Tasks, Tasks / node, Partition, Memory |
| **Allocation & notifications** | Account, Email |

- **Account** — your (or your project's) **Slurm allocation**. It can be
  **mandatory** for a resource; CryoStack blocks submission with a clear
  message when the resource requires an account and the field is empty.
- **Email** — an optional address for job start / end / fail notifications.
- **Wall time** — `MM:SS`, `HH:MM:SS`, or `D-HH:MM:SS`.
- **Memory** — for example `512M`, `4G`, `16GB`, `1T`.
- Before submission CryoStack checks internal consistency (nodes ≥ 1,
  tasks ≥ 1, tasks / node ≥ 1, tasks / node ≤ tasks) and the syntax of wall
  time and memory. It does **not** invent cluster-specific ceilings — the
  scheduler still enforces the resource's real policies.

### Check SSH Access

**Check SSH Access** does exactly this:

```
connect to the resource
   ↓
run the identity command (whoami)
   ↓
compare the result to your configured HPC username
```

The **Status** chip shows:

| State | Meaning |
|---|---|
| **Not checked** | you have not run a check yet |
| **Checking…** | a check is running (the button is disabled) |
| **Verified** | connected, and the remote username matches your configured HPC username |
| **Identity mismatch** | connected, but the remote username is **not** the one you configured — the run log shows both |
| **Failed** | could not connect or authenticate — see the run log |

Resolving **Identity mismatch**:

- confirm the **HPC username** field is your actual username on that resource;
- confirm the SSH key you registered belongs to the **intended account**;
- if using the Connector, confirm it is **paired to your current CryoStack
  session** (the Connector card shows **Connected**).

### Run protection

When you submit a **remote** run, CryoStack performs a **fresh** access
verification at submit time — it re-runs the identity check and blocks the run
on a mismatch, an unverified or incomplete configuration, a missing credential,
or (for the Connector path) an offline connector. A green **Check SSH Access**
earlier is a useful UX signal but is **not** blindly trusted for execution.

### Security and isolation

- CryoStack application state (workspace, run history, settings) is scoped to
  your **authenticated CryoStack user**.
- HPC settings are stored **per user × compute resource**.
- SSH credentials are **namespaced by user × resource × HPC identity**.
- Connector pairing sessions are **owner-bound** — a session belongs to the
  CryoStack user who created it.
- SSH private keys, bootstrap passwords, pairing codes, and relay tokens are
  **never written into run provenance** or any saved configuration.

## 10. Preparing and launching runs

### Environment preparation

Some backends need a one-time setup on the remote resource:

- **Remote + ICESEE-Spack.** Use **Check environment** for a fast probe
  (repository, activation, `ISSM_DIR`, executables). Use **Prepare
  environment** to install or repair it — this runs as a durable setup job on
  the resource, not synchronously in the browser. After preparation, a deep
  verification confirms the environment is genuinely usable before it is
  marked **Ready**. A scientific run is blocked until the live check reports
  Ready, with a clear message.
- **Remote + Container (tested image).** No preparation step.
- **ISSM + MATLAB licensing.** ISSM runs MATLAB inside the container. The
  MATLAB license is a property of the compute resource, injected at run time.
  If the selected resource has no license configured, the run fails fast with
  a clear message before MATLAB is launched.
  - **Remote:** the license is the compute-resource profile's network
    license server (`MLM_LICENSE_FILE=<port>@<host>`), passed to the
    container with `apptainer exec --env`. It is never logged or persisted.
  - **Cloud (AWS Batch):** "Container image ready" is **not** "ISSM runtime
    ready". The tested image ships no license and a campus license server is
    not reachable from AWS Fargate. You supply a cloud-reachable mechanism
    by creating an **AWS Secrets Manager** secret *in your own AWS account*
    whose value is the `MLM_LICENSE_FILE` string (a license server you can
    reach from the Batch VPC, or a MathWorks online-licensing token), and
    giving CryoStack only that secret's **ARN**. Prepare Cloud then wires the
    ARN into the ISSM job definition (`containerProperties.secrets`) and AWS
    Batch injects the value when the container starts. The license value
    never reaches CryoStack, Git, the image, an S3 run artifact, a run
    manifest, a command preview, or a log — only the (non-secret) ARN is
    stored, on your AWS connection. The Review card shows an explicit **ISSM
    runtime** row (Ready / *Needs a MATLAB license*) distinct from the
    container row.

### Launching

Before submitting, confirm the model and example, the run target, the
execution mode and backend, your HPC access (Section&nbsp;9 — **Check SSH
Access** should read **Verified**), and any scheduler resources. Submit the
run. CryoStack re-verifies remote access at submit time, then the Run log
reports staging, the submission command, the scheduler job id, and progress.

## 11. Run monitoring and history

- **Runs panel.** Lists your run history with model, date, and status. Select
  a run to make it the active run for logs and results.
- **Run log.** Shows connector activity, file staging, the submission command,
  the job id, standard output and error, warnings, failures, and output
  locations. A scheduler job keeps running after you close the browser, as
  long as submission completed.
- **Files panel.** Shows the selected run's workspace files.
- **Isolation.** You only see your own runs. A run id owned by another user is
  simply absent from your history.

## 12. Results

CryoLauncher discovers **what a completed ISSM run actually produced**, rather
than assuming every example has the same outputs.

### Preview Results

Select a completed run, open the **Results** tab, and click **Preview
Results**. CryoLauncher:

1. synchronizes the run's outputs from the remote resource into a local cache
   for that run;
2. reads the structured result package;
3. populates the field-visualization panel;
4. renders an initial recommended plot.

If the outputs have not been fetched yet, the panel says so and offers a
**Fetch results** button. The controller never performs remote transfers
itself — fetching is always the execution backend's responsibility.

### Preview Results vs Render

- **Preview Results** — fetch/synchronize, discover, populate the selectors,
  and show a useful initial preview.
- **Render** — draw the specific Solution / Field / Timestep currently
  selected.

### Legacy runs

Runs produced before structured export still work: their existing figures and
model file are shown, with a note that the structured selector is unavailable
for that run. Old results are never silently rewritten.

## 13. Visualization

The **Field visualization** panel is model-neutral: it only knows
Solution → Field → Timestep and delegates the scientific rendering to the
model.

- **Solution selector.** Lists the solution(s) the run actually produced
  (for example `StressbalanceSolution`, `TransientSolution`,
  `ThermalSolution`). Only what exists in the run appears.
- **Field selector.** Lists the fields in the selected solution, most useful
  first (for a stress-balance run, `Vel` and `Pressure` before the rest).
  Changing the solution repopulates the field list.
- **Timestep selector.** Shown only for transient results. It offers
  **Final** plus each available timestep, and defaults to Final. For a field
  that was only computed at some timesteps, only those are offered.
- **Field types, at a user level:**
  - *nodal* spatial fields (defined at mesh vertices) — rendered as a
    triangulation field map;
  - *elemental* spatial fields (defined per element) — rendered as an
    element-coloured map;
  - *scalar transient diagnostics* (a single number per timestep, e.g. ice
    volume) — rendered as a time series;
  - *static scalar diagnostics* and other shapes — reported with a clear
    reason rather than a broken plot.
- **Deterministic rendering.** The same selection always produces the same
  plot. Rendering does not require MATLAB or a live model installation, and
  figures with masked / non-finite regions (common on ice fronts) are drawn
  with those regions omitted rather than failing.
- **Not everything is plottable.** Available solutions and fields come from
  the actual run. Unusual result shapes are handled explicitly — an
  unsupported field shows a short reason and never breaks the Results tab.

## 14. Downloads

From the Results controls:

- **Download Results** — the full structured output package as an archive.
- **Download Figures** — only the rendered figures.

Downloads operate on the local cache for the selected run, so run Preview
Results (or Fetch results) first.

## 15. Reproducibility and provenance

Each run records provenance so it can be understood later:

- the source example and whether a working copy was staged;
- Basic-mode overrides that were applied (which parameters, which values);
- datasets that were staged into the run;
- the container image or software environment used, resolved to a specific
  identity (a tested image is pinned by digest);
- the run's status and timing.

Sensitive values — credentials and the MATLAB license value — are treated as
runtime configuration only and are never written into provenance, the run
manifest, or the logs.

### Result format (reference)

The structured result package is a transport-neutral directory:

```text
outputs/
  metadata.json          # what the run produced: solutions, fields, shapes
  mesh/mesh.h5           # mesh coordinates and connectivity
  fields/<Solution>/...  # one file per exported field
  model/md_final.mat    # the full model, for MATLAB-based analysis
  figures/              # rendered figures (initially empty)
```

You normally never interact with these files directly — the Results tab and
the download controls do it for you. `metadata.json` is the authoritative
description of what a run produced.

## 16. Troubleshooting

:::{raw} html
<div class="cryostack-troubleshooting">

  <details>
    <summary>The Results selectors are empty</summary>
    <p>
      Click <b>Preview Results</b> (or <b>Fetch results</b>) for the selected
      run. The selectors populate only after the run's outputs are
      synchronized into the local cache. If the panel says the run is a legacy
      run, structured visualization is not available for it.
    </p>
  </details>

  <details>
    <summary>A Basic-mode run is blocked before submission</summary>
    <p>
      A curated parameter is out of range or not applicable to the example's
      solver. The message names the parameter; adjust or disable it.
    </p>
  </details>

  <details>
    <summary>ICESEE-Spack run is blocked as "not ready"</summary>
    <p>
      Run <b>Check environment</b>, then <b>Prepare environment</b> if needed.
      A scientific run is only allowed once the live probe reports Ready.
    </p>
  </details>

  <details>
    <summary>ISSM run fails immediately on a MATLAB license error</summary>
    <p>
      The selected compute resource has no MATLAB license configured. Choose a
      resource that does, or contact the platform administrators.
    </p>
  </details>

  <details>
    <summary>Connector not connected</summary>
    <p>
      Confirm the connector is running on your workstation and paired to your
      <em>current</em> CryoStack session. Click <b>Open Connector Setup</b>
      again to refresh the session, then quit and relaunch the connector so it
      picks up the newest session.
    </p>
  </details>

  <details>
    <summary>Pairing code expired</summary>
    <p>
      Pairing codes are one-time and expire with the session. Click
      <b>Open Connector Setup</b> to generate a new one, then pair again.
    </p>
  </details>

  <details>
    <summary>SSH: Permission denied</summary>
    <p>
      Your CryoStack public key is not (yet) registered for this account.
      Use <b>Password bootstrap</b> once, or register the public key manually
      through your institution's portal, then <b>Check SSH Access</b>. Never
      paste a private key anywhere.
    </p>
  </details>

  <details>
    <summary>Identity mismatch</summary>
    <p>
      You connected, but the remote username is not the one you configured.
      Check the <b>HPC username</b> field, check the key you registered belongs
      to the intended account, and check the connector is paired to your
      current session. The run is blocked until this matches.
    </p>
  </details>

  <details>
    <summary>Remote working directory missing or not writable</summary>
    <p>
      Set <b>Remote working directory</b> to a path your HPC identity owns and
      can write (often under <code>scratch</code> or <code>work</code>).
      CryoStack never substitutes another location.
    </p>
  </details>

  <details>
    <summary>Slurm account required</summary>
    <p>
      This resource requires an allocation. Enter your project's Slurm
      <b>Account</b> in <em>Allocation &amp; notifications</em> and resubmit.
    </p>
  </details>

  <details>
    <summary>VPN / MFA required</summary>
    <p>
      Some resources need an institutional VPN, MFA, or a campus network before
      SSH works. These are resource requirements, not CryoStack settings.
      Connect your VPN, then use the CryoStack Connector (which runs on your
      workstation and inherits that access).
    </p>
  </details>

  <details>
    <summary>Public key registered but SSH still fails</summary>
    <p>
      Confirm you registered the <em>public</em> key (the <code>.pub</code>
      line), that it was added to the intended account, and that the change was
      saved/applied on the portal. Then check for a VPN/MFA requirement. Re-run
      <b>Check SSH Access</b>.
    </p>
  </details>

  <details>
    <summary>Connector platform not listed for download</summary>
    <p>
      The setup page only offers platforms present in
      <code>/downloads/connectors/manifest.json</code>. If yours is absent, a
      build has not been published for it yet — use another platform or contact
      the platform administrators.
    </p>
  </details>

  <details>
    <summary>macOS: connector installed in /Applications is unresponsive</summary>
    <p>
      Known issue on some systems. Run the connector directly from the
      downloaded disk image instead. If copy/paste into the pairing field also
      misbehaves, type the code.
    </p>
  </details>

  <details>
    <summary>An example or field you expected is missing</summary>
    <p>
      The example picker only lists runnable examples, and the Field selector
      only lists what the run actually produced. Confirm the run completed and
      that the analysis you expected was enabled.
    </p>
  </details>

</div>
:::

## Related documentation

- [Getting Started](getting_started)
- [CryoLauncher Resources](resources)
- [CryoStack Documentation](https://cryostack.eas.gatech.edu/documentation.html)
- [Open ICESEE](https://cryostack.eas.gatech.edu/icesee-gui/)

:::{raw} html
  </div>
</div>
:::
