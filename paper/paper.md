---
title: 'CryoStack: A modular cyberinfrastructure stack for cryosphere data, models, data assimilation, and heterogeneous computing'
tags:
  - Python
  - cryosphere
  - scientific gateways
  - ice-sheet modeling
  - data assimilation
  - radar data
  - reproducible workflows
  - high-performance computing
authors:
  - name: Brian Kyanjo
    orcid: 0000-0002-0995-1051
    affiliation: "1"
    corresponding: true
  - name: Alexander A. Robel
    orcid: 0000-0003-4520-0105
    affiliation: "1"
affiliations:
  - name: School of Earth and Atmospheric Sciences, Georgia Institute of Technology, Atlanta, GA, USA
    index: 1
date: 2 September 2026
bibliography: paper.bib
---

# Summary

CryoStack is an open-source cyberinfrastructure stack for assembling
reproducible cryosphere workflows from scientific applications, user
workspaces, data catalogs, experiment records, and heterogeneous execution
resources. The software is organized around a shared gateway rather than a
single scientific code. Its current applications are **CryoLauncher** for
configuring and running ice-sheet models; **ICESEE** for ensemble-based state
and parameter estimation [@kyanjo2026icesee]; **LIVIST** (Living Ice Sheet
Temperature) for exploring Antarctic englacial-temperature products inferred
from radar and constrained by boreholes; and **Frozen Legacies** for discovering
and working with historical Antarctic radar observations and derived products.

The present implementation combines an Nginx and `aiohttp` gateway, Jupyter
Book documentation, Voilà scientific interfaces, a React/TypeScript data
application, password and external-provider authentication, per-user workspaces
and experiment histories, role-based administration, an HPC connector and
command relay with per-session capability secrets, remote Slurm execution,
and an implemented AWS Batch path for one model. Two ice-sheet models are
described by a capability registry and export transport-neutral result
packages with model-free readers and deterministic visualization. A
dependency-aware deployment registry builds applications in a declared order,
validates artifacts and prerequisites, selects the required service restart
scope, and performs route-level health checks.

CryoStack grew from deployment tooling for ICESEE into a wider software stack
for the computational cryosphere. The resulting design treats the scientific
experiment, dataset, and application as related but independent objects. A
scientific application retains its domain-specific interface while reusing
identity, persistence, execution, deployment, and administrative services.
Likewise, a compute backend implements a common lifecycle without being
embedded in a particular frontend. This paper describes the implemented
architecture, the connector-mediated bridge to protected HPC resources, the
model capability registry and result contract, the data-preservation workflow
provided by Frozen Legacies, the ongoing modular migration of CryoLauncher,
an experimental human-in-the-loop run assistant, and the boundary between
current capabilities and work still required for broad community operation.

CryoStack is available at <https://cryostack.eas.gatech.edu/> and its source
is maintained at <https://github.com/ICESEE-project/CryoStack>.

# Statement of Need

Cryosphere research increasingly combines large observational collections,
interactive interpretation, numerical ice-sheet models, inverse methods,
ensemble simulations, and scalable computing. These components have different
software and resource requirements. Data discovery and quality control benefit
from interactive maps and browser interfaces. Model development may occur on
a workstation. Ensemble assimilation and production simulations commonly
require MPI-enabled libraries, batch schedulers, or cloud resources. Historical
radar holdings additionally require dataset-specific ingestion, geolocation,
quality-control tools, and preservation of provenance.

Today these stages are frequently delivered as separate repositories and
manual procedures. A researcher may need to install compiled model
dependencies, translate data formats, reproduce an undocumented graphical
workflow, write scheduler scripts, transfer inputs, track job identifiers,
retrieve outputs, and remember which parameters and environment created a
result. The work is repeated when the model, data product, institution, or
compute system changes. This integration burden slows collaboration and
disproportionately affects students and groups without dedicated
research-software or HPC support.

Existing community software provides strong capabilities within individual
parts of this lifecycle. ISSM provides continental-scale ice-sheet modeling
and inversion [@larour2012issm], Icepack provides composable glacier-flow
modeling in Python [@shapero2021icepack], and DART and PDAF provide mature
general-purpose data-assimilation capabilities [@anderson2009dart;
@nerger2013pdaf]. ICESEE adds model-agnostic ensemble Kalman filtering tailored
to ice-sheet applications, multiple filter variants, MPI parallelism, and
couplings to ISSM and Icepack [@kyanjo2026icesee]. These scientific packages
do not, by themselves, provide a common access and operations layer spanning
identity, data discovery, model configuration, remote execution, experiment
history, and application deployment.

CryoStack addresses this missing layer. It is intended for researchers moving
between exploratory and production workflows, collaborators who do not share
the same computing environment, radar scientists preserving difficult legacy
observations, and instructors who need a consistent entry point for
computational examples. Browser access reduces the initial interaction cost,
while remote execution preserves the use of resources already authorized for
the user. The architectural goal is not to hide the scientific software or
institutional policy. It is to make the transitions among applications, data,
and resources explicit, repeatable, and inspectable.

# Software Architecture

CryoStack separates access and operations, scientific applications, execution
backends, and reproducible software environments (Figure 1). The separation
has become more explicit as the code base has evolved: identity and experiment
persistence live outside the applications; per-user workspace roots are
enforced by a containment check rather than by convention; a capability
registry states, in one place, what CryoStack can do with each model; the
Control Center reads shared operational state; CryoLauncher is being
decomposed into frontend panels and backend managers; cloud-provider code
implements abstract driver contracts; and deployable applications are declared
in a registry rather than hard-coded in a single service script.

![CryoStack's current layered architecture. A shared gateway and operations plane supplies identity, per-user workspaces, experiments, administration, deployment, and health services to four scientific applications. Shared contracts cover model capabilities, structured results, and visualization. Modeling and data-assimilation workflows can use local, connector-mediated HPC, or AWS Batch execution backends over reproducible Spack and container environments.](cryostack_architecture.png)

**Figure 1:** CryoStack platform architecture. Solid components are present in
the repository. The AWS Batch path is implemented for both CryoLauncher/ISSM
and ICESEE; ISSM awaits qualification on a controlled account, and ICESEE's
verified coverage is limited to a single example at NP=1 (single-process
execution).

## Gateway, routing, and process composition

Nginx terminates public connections and routes both HTTP and WebSocket traffic
to an `aiohttp` application gateway. The gateway serves the Jupyter Book site,
proxies Voilà applications, exposes the authentication and experiment APIs,
routes the React-based LIVIST frontend, serves Frozen Legacies, and integrates
the Control Center. Jupyter technologies provide a useful bridge between
executable Python and browser interfaces [@kluyver2016jupyter], while the
gateway presents applications under one platform rather than as unrelated
notebook servers.

The gateway also manages the processes behind the interactive applications and
proxies their HTTP and WebSocket connections. Static and generated applications
are described in `deployment/applications.yaml`. Each declaration can specify
dependencies, working directory, build commands, expected artifacts, routes,
health targets, and restart scope. The deployment engine computes a
dependency order, rejects cycles and missing dependencies, verifies required
commands and artifacts, and restarts only the affected process group. Separate
preflight and health-check tools allow a deployment to fail before interrupting
the live service and verify expected status codes after a change. This registry
is important for a growing stack: adding an application becomes a declared
deployment operation rather than another special case in a monolithic script.

## Identity, workspaces, and experiment persistence

CryoStack provides local password accounts and optional GitHub and ORCID
authentication. Passwords are salted and hashed with `scrypt`. GitHub OAuth
uses a state record and PKCE; ORCID uses an authorization-code flow with a
state-bound, expiring transaction. External identities are normalized behind
a provider interface and linked to internal user records. Session cookies are
HTTP-only and can be marked secure according to deployment context. Redirects
after authentication are restricted to same-site relative paths.

The persistence layer stores users, sessions, linked identities,
schema-versioned saved configurations, per-application workspace state,
experiments, and experiment events in SQLite with foreign-key enforcement and
write-ahead logging. An experiment stores an immutable configuration snapshot
alongside application, backend, job and cluster identifiers, working and
output directories, log path, exit state, errors, metadata, and timestamps.
Status transitions create timeline events. Application bridges let
CryoLauncher and ICESEE create and update these records without duplicating
the storage implementation.

Workspace state is isolated per authenticated user. The trusted identity is
the one the gateway resolves from the session, never a value supplied by a
client. Each user is given an owner root derived from that identity, and file
operations within an application are confined to that root by an explicit
containment check; canonical examples remain read-only and are copied into a
user-owned working copy before any edit or run. Remote and local run
directories for CryoLauncher and ICESEE are likewise created under the calling
user's namespace, so two users acting in the same interval cannot overwrite
each other's inputs or outputs.

This layer is more than a login screen. A user can return to a saved workspace,
reuse a named configuration, inspect an experiment after the interactive
kernel has gone away, and relate scheduler state to the configuration that
produced it. The current schema forms the basis for fuller provenance; it does
not yet capture every environment digest, input checksum, or scientific
diagnostic required for archival reproducibility.

## Model capability registry

CryoStack ships adapters for two ice-sheet models, ISSM and Icepack. What the
platform can actually do with each of them — whether a curated configuration
subset exists, whether runs export a structured result package and under which
contract, whether that package can be read without the model's runtime,
whether deterministic visualization is available, whether the model requires
MATLAB, and which execution modes and backends apply — is stated once in a
capability registry. Import-time assertions keep the registry consistent with
the adapters, the cloud runtime's list of supported models, and the
visualization dispatch, so a claim in the registry cannot silently drift from
the code it summarizes. The gateway, the result and visualization layers, and
the experimental run assistant all read capabilities from this registry rather
than from per-module conditionals.

## Control Center and role-based administration

The Control Center turns the shared database into an operations interface. Its
dashboard summarizes users, active sessions, authentication providers,
applications, configurations, workspaces, experiment states, and recorded
events. User views expose linked identities, sessions, recent experiments,
and configurations. Experiment views reconstruct configuration and metadata,
calculate run time, and show the event timeline. Diagnostic views report the
Python and SQLite state, experiment storage, configured GitHub and ORCID
providers, and whether AWS environment information is present.

Access is governed by a role hierarchy of developer, maintainer, administrator,
and owner. Role assignment rules prevent administrators from modifying peer
administrators or owners, restrict the roles each actor may grant, and protect
the final owner from removal. Administrative changes create audit events. The
current Control Center establishes an operational foundation; automated
resource probes, richer service-level indicators, and durable policy-backed
audit export remain future work.

# Scientific Applications

## CryoLauncher

CryoLauncher provides a form-driven environment for ice-sheet experiments.
Users select a model, a native example, a run target, a software environment,
an execution mode, and scheduler resources. The interface previews the
resulting command and execution summary before submission, records status,
exposes logs, and packages model outputs and figures for download. The model
set follows the capability registry: ISSM and Icepack. Lightweight examples
for teaching and system testing, including Lorenz-96, are provided through
ICESEE rather than through the CryoLauncher model registry.

The interface has recently been restructured from a large notebook-oriented
module toward a frontend package composed of reusable panels. Run settings,
runtime controls, status, run plan, command preview, log and result tabs, output
workspace, and cloud-environment configuration are now separate components
with shared cards, forms, layout, status badges, widgets, and theme modules.
State objects isolate run settings and runtime information from presentation.
During this "strangler" migration, the established gateway callbacks continue
to own parts of the execution state while new components wrap them. This
incremental approach preserves working scientific paths while replacing the
monolith behind stable UI boundaries.

The same separation is taking place below the interface. A common
`ExecutionBackend` contract defines submit, status, logs, and terminate
operations and returns backend-independent result and status objects. Remote
and cloud wrappers adapt established implementations to that contract. Remote
driver interfaces distinguish connector and direct SSH access. Container
metadata, Docker build and publication, and model-image declarations are
provider-independent. Some paths still delegate to legacy modules, and remote
log handling has not yet fully migrated; these boundaries are intentionally
visible in the code rather than hidden as completed abstractions.

## Ice-sheet models: ISSM and Icepack

Each model adapter owns example discovery, run-target selection, the batch
script for a scheduler run, a curated "Basic" configuration subset, and a
result exporter. For ISSM, Basic mode exposes a validated set of solver-aware
`md` model parameters; overrides are written into a per-run working copy as an
appended MATLAB step, and the canonical example is never modified. For Icepack,
Basic mode exposes ice temperature and timestep count, applied by an exact,
fail-closed substitution of a Python literal in the working copy; an example
that derives these quantities rather than assigning a literal is refused before
submission rather than run incorrectly. Non-finite override values are rejected
by both validators.

The two models differ in ways CryoStack does not attempt to hide. ISSM runs a
MATLAB entry script and needs a MATLAB license for the container backend;
Icepack runs a Firedrake-based tutorial as a notebook or script and needs no
proprietary license. The adapters expose these differences through the
capability registry rather than through scattered checks on the model name.

## ICESEE

ICESEE supplies ensemble state-estimation and parameter-inference workflows.
Its integrated scientific library supports ensemble Kalman filtering and
deterministic variants, parallel ensemble execution, parallel I/O, and the
ISSM and Icepack couplings described in [@kyanjo2026icesee]. CryoStack does not
reimplement these algorithms. It makes their configuration, execution state,
workspace, and remote-resource pathways available through the shared platform.
A learner can begin with Lorenz-96, while a researcher can stage a model-coupled
ensemble to Slurm using the same connector infrastructure as CryoLauncher.
ICESEE does not yet emit a structured result package under a CryoStack
contract; its outputs are the HDF5 files the framework writes, and the
diagnostics a data-assimilation study needs (error and spread time series,
innovations, analysis increments, rank histograms) are not part of a shared
schema.

## LIVIST

LIVIST (Living Ice Sheet Temperature) is an interactive application for
Antarctic englacial-temperature products inferred from radar observations and
constrained by borehole measurements. It is not a LiDAR application. The
React/TypeScript frontend and its user and API documentation are built and
served through the CryoStack deployment registry. LIVIST demonstrates that a
specialized data product can retain its own implementation and documentation
while sharing the platform's routing and application context.

## Frozen Legacies

Frozen Legacies extends CryoStack from contemporary model and data interfaces
to the preservation and reuse of historical Antarctic radar observations. The
current application registers datasets through YAML manifests and adapter
classes. A dataset declaration identifies its source, campaign, institution,
description, products, and downloads. The build pipeline converts registered
observations to a catalog and GeoJSON, constructs observation points and
flight geometries, and separates flight segments when geographic jumps imply
distinct survey passes. The web interface provides a zoomable Antarctic map,
flight lines, observation points, dataset metadata, and links to products and
documentation.

The initial adapter targets LYRA-derived records from historical airborne
radar surveys. The integrated Frozen Legacy Tools cover complementary
interpretation paths: ASTRA for guided A-scope picking, ARIES for automated
Z-scope interpretation, TERRA for interactive polygon-based tracing, and URSA
for automated A-scope signal retrieval. These tools produce geolocated picks,
travel-time or power measurements, ice-thickness estimates, quality-control
figures, and processing records. CryoStack currently makes the catalog and
documentation discoverable and packages the tools; it does not yet execute
every desktop workflow as a browser-native, provenance-captured service.

Frozen Legacies is architecturally significant because it exercises a second
kind of extensibility. A new model needs an execution adapter, whereas a new
historical collection needs a dataset manifest and ingestion adapter. Both can
reuse identity, documentation, deployment, storage, and experiment/provenance
services. This provides a practical path toward linking preserved observations
to model initialization, validation, and assimilation without collapsing data
curation and simulation into one application.

# Results, Packaging, and Visualization

A completed ISSM or Icepack run is exported to a transport-neutral result
package: an `outputs/` tree containing a metadata file, mesh geometry, per-field
arrays, and any figures the run produced. Each package declares a schema
identifier (`cryostack.issm.results`, `cryostack.icepack.results`) and version.
The exporters degrade rather than fail: an Icepack tutorial whose final state
is not a plottable field, or a run that produced only figures, yields a package
that records what it could and what it could not, and a science run is never
turned into a failed run because postprocessing found nothing to export.

A reader for each schema loads the package without the model's runtime — no
MATLAB for ISSM, no Firedrake for Icepack — and answers a small set of
questions: which fields are present, their units, the mesh, a field's values,
and a recommended set of plots. Both readers satisfy a shared result-package
protocol, and a shared visualization layer renders fields and time series
deterministically from the neutral package. The gateway's results panel selects
the reader and visualizer for a run's model through the same protocol, so a
third model would gain a results view by providing a conforming exporter and
reader rather than by extending the panel. The Icepack exporter linearizes
Firedrake fields to a first-order nodal representation for display and records
that it has done so; its behavior on real Firedrake output still needs
confirmation on an HPC or container run.

# HPC Connector and Remote Execution

CryoStack supports local execution and two remote-HPC access modes. Direct
mode invokes SSH and rsync from the application host when network policy and
reachability allow it. Connector mode is intended for clusters reachable only
from a user's workstation, VPN, or approved edge environment. An automatic
mode first checks direct access and can fall back to the connector. In all
cases the target institution remains responsible for accounts, VPN and
multifactor policy, scheduler policy, and allocation enforcement.

![CryoStack HPC bridge. CryoLauncher and ICESEE create a session and send commands through a FastAPI relay. A packaged workstation connector maintains an outbound WebSocket and performs SSH, rsync, archive, and Slurm operations using the user's authorized local access.](cryostack_hpc_bridge.png)

**Figure 2:** Connector-mediated control and data path to a protected HPC
resource. The relay binds each session to an authenticated CryoStack user and
issues per-session capability secrets; it still holds that state in a single
process, and the production-hardening needs are described below.

Four software roles participate in a connector-mediated run:

1. CryoLauncher or ICESEE requests a connector session for the authenticated
   user and receives a session identifier, a pairing code, and the capability
   secrets described below.
2. Nginx routes connector HTTP and WebSocket traffic to a FastAPI relay served
   by Uvicorn. The relay tracks online connectors and pending command futures.
3. A packaged connector on macOS, Linux, or Windows exchanges the one-time
   pairing code for a session secret and opens an outbound secure WebSocket.
   The workstation can use the user's existing VPN, SSH configuration, and
   institutional network position.
4. The application posts a command type and JSON payload, authorized by the
   session's control secret and scoped to its owning user. The relay adds a
   command identifier, forwards it to the matching connector, and resolves the
   waiting request when the correlated result arrives. An earlier live session
   for the same user is superseded.

The connector implements host checks, SSH execution, rsync upload and
download, archive staging and retrieval, Slurm submission, scheduler queries
and cancellation, log tailing, public-key reporting, and optional SSH-key
bootstrap. Server-side SSH credentials for a resource are namespaced by the
combination of CryoStack user, resource, and remote username, so two users
configuring the same cluster do not share a key file. Remote launchers stage
the selected native example, prepare a run directory, activate either an
ICESEE-Spack environment or an Apptainer image, write an application-specific
batch script, invoke `sbatch`, parse the job identifier, and use `squeue`,
`sacct`, and `scancel` for lifecycle operations. Automatic log polling,
experiment-status updates, and result and figure bundles are delivered to the
modular output workspace.

The relay never opens SSH connections itself. Private keys remain on the
workstation, and the connector invokes local OpenSSH and rsync tools. This
removes the need for an inbound connection from the public platform to the
workstation or cluster. It does not make the current protocol production-safe
by itself. The connector still exposes a generic shell command type in
addition to the typed operations; session and pending-command state live in
one relay process rather than a durable store; sessions are not yet bound to a
registered resource policy with expiry and revocation; and per-command
ownership, path constraints, replay protection, and auditable authorization
need systematic enforcement. An optional password-assisted key bootstrap also
passes a one-time secret through the hosted control path even though it is not
persisted. Sites that prohibit this flow must disable it and use their
institutional key-registration process.

# Cloud and Container Architecture

The cloud subsystem is organized around provider-independent driver contracts.
Moving an application between execution backends reuses the same
scientific/application configuration rather than requiring a separate
backend-specific one, although backend-specific execution and infrastructure
settings, and validation maturity, still differ by application and backend.
Abstract cloud and execution interfaces separate frontend actions from provider
operations. The AWS driver exposes identity and capability inspection;
discovery and preparation of VPC, subnet, security-group, IAM, S3, ECR, and
AWS Batch resources; and job submission, status, log, and termination
operations. S3 preparation enables default encryption and blocks public
access. ECR support discovers or prepares model-image repositories. Docker
build, tagging, pushing, and image metadata are separated from AWS so the
container workflow is not tied to one registry. All AWS calls are issued
through the `aws` command-line tool with ambient credentials; the code holds no
static keys and creates no long-lived credential.

CryoLauncher includes a structured cloud-environment card for region, profile,
S3 prefix, Batch queue, job definition, and job name, and an end-to-end AWS
Batch submission path for ISSM. A submission validates the cloud configuration,
runs the model preflight including the MATLAB-license gate, stages a user-owned
working copy to S3, submits a Batch job, parses the job identifier, and
registers the run against the user's experiment history; status, logs, and
termination flow back through the common execution result. This path is
implemented but not yet qualified: it runs against a single account-wide bucket
without per-user object isolation, accepts a caller-supplied Batch job
definition rather than an allow-listed one, and lacks the budget, quota,
cleanup, and failure-recovery controls a shared service needs. The same AWS
driver and provisioning architecture also now serves ICESEE rather than a
second, independent cloud stack; connecting a personal AWS account uses a
connection-scoped CloudFormation onboarding flow, so independently created
CryoStack AWS connections do not depend on one globally fixed execution-role
name. ICESEE's Lorenz-96 example has been executed end to end through this
shared path at NP=1 (single-process execution), but this does not extend to
ICESEE's other examples or to multi-process execution, and it does not
substitute for the ISSM qualification described above: architectural reach
across applications is currently broader than what has been validated end
to end for either one. ISSM cloud runs additionally require a MATLAB
license to be configured for the cloud profile, and the reference
deployment does not provide one.

Two environment strategies complement these execution backends. ICESEE-Spack
uses Spack [@gamblin2015spack] to resolve source builds against site compilers,
MPI implementations, and system libraries. ICESEE-Containers uses Docker and
Apptainer for preconfigured execution; Apptainer follows the mobility-of-compute
model developed for scientific containers [@kurtzer2017singularity]. The
container publication layer can build a declared image and push it to a
configured registry; the reference model images are currently digest-pinned
under a personal registry namespace and should be republished under a project
account. The Apptainer runtime path remains partly in the legacy remote runner
and is a target of the ongoing backend migration.

# Reproducible Experiment Lifecycle

A current remote experiment proceeds through the following lifecycle:

1. The user authenticates, selects CryoLauncher or ICESEE, and restores or
   edits an application workspace.
2. The application validates the selected model, example, parameters,
   environment, execution mode, and scheduler resources and previews the run
   plan.
3. CryoStack snapshots the configuration and creates an experiment and initial
   event record.
4. Direct SSH or the connector stages inputs and submits the generated Slurm
   script using the selected Spack or container environment.
5. The scheduler job identifier and paths are attached to the experiment.
   Manual or automatic polling maps backend state into CryoStack's queued,
   running, completed, failed, or cancelled states and appends timeline events.
6. Logs and result archives are returned to the output workspace, where the
   user can inspect or download them and reuse the saved configuration. For
   ISSM and Icepack the outputs include the structured result package and its
   visualizations.

This lifecycle already preserves substantially more context than an isolated
job script. Full archival reproducibility will require immutable environment
digests, input and output checksums, data-transformation records, scientific
diagnostic definitions, adapter versions, and exportable run manifests. The
current code provides concrete objects and event hooks into which those fields
can be added.

# Human-in-the-Loop Run Assistance (Experimental)

CryoStack includes an experimental agent layer that lets an assistant help a
scientist assemble a run without becoming the authority that executes it. A
user request is turned into a declarative run plan; CryoStack validates that
plan against the same rules the manual interface uses (remote-identity
verification, Slurm-resource validation, the model's Basic-mode parameter
spec, and the model and backend preflight); a canonical digest is computed over
the plan's scientific and resource fields, and an optional fingerprint is
computed over the content of the referenced example, run target, and datasets;
the human then approves the plan, and only an approved plan whose live digest
still matches the approved digest can reach the existing execution
infrastructure. Editing any scientific or resource field after approval
invalidates the approval.

The assistant is advisory. Its tools are read-only and permission-capped below
the level required to prepare or submit anything; there is no tool that runs a
shell command, writes an arbitrary path, or injects environment variables; and
the language model, whatever the provider, only proposes tool calls that the
registry and the human accept or reject. The interface to a model provider is a
small protocol with a deterministic rule-based implementation shipped by
default and no vendor SDK in the core. A run-submission backend that composes
the existing remote pipeline for an approved plan is implemented and tested
against fakes, but it is not wired into the gateway; the only agent surface in
the running platform is an opt-in "Run Assistant (Beta)" panel that builds and
records an approved plan and has no submission control. Live agent-driven
submission is therefore not enabled. This capability is described here as an
emerging extension, and its current limitations are listed below.

# Availability, Verification, and Limitations

CryoStack is distributed under the MIT License; newly modularized source files
also carry BSD-3-Clause identifiers, and the integrated applications retain
their own licenses. This inconsistency should be reconciled before a formal
platform release. Users must cite and comply with the scientific models,
datasets, and applications used in an experiment. The repository includes the
gateway, authentication and persistence services, Control Center, application
interfaces, connector packages, cloud and container modules, deployment
registry, documentation, Frozen Legacies integration, LIVIST submodule, and a
pinned ICESEE source snapshot.

The current automated test suite includes more than 1,800 passing Python
tests spanning the gateway, authentication, Control Center, frontend
panels, model adapters, connector, cloud modules, and deployment engine,
plus a browser-facing connector-page test set. A separate offline
acceptance command
(`python -m cryostack_src.acceptance --offline`) runs read-only invariant
checks — agent safety properties, capability-registry and result-contract
consistency, cloud restrictions and absence of static credentials, per-user
workspace isolation, the public documentation table of contents, and connector
build metadata — and reports which checks pass and which still require a person
at a terminal. At the documented revision it reports fifteen checks passing,
none failing, and two requiring live verification.

Verification does not yet extend to scientific correctness or to the paths that
need real infrastructure. Deployment preflight and health checks verify
structure and route availability, not model results. The remote backend still
delegates parts of its behavior to legacy modules, remote logs have not fully
moved behind the common backend contract, and cloud lifecycle operations
delegate to a legacy AWS Batch module. The following are known limitations:

- **Institutional authentication.** The connector reaches Georgia Tech PACE,
  but PACE rejects simple password authentication and requires the
  institution's multifactor flow. The password-assisted key bootstrap has not
  been exercised against that flow, and the reference deployment cannot yet
  complete a real PACE run without manual key registration.
- **Connector distribution.** The packaged connector binaries are built from a
  prior revision; a connector behind the current relay protocol must be rebuilt
  and republished before a remote run is attempted with it.
- **Icepack result exporter.** The container-side Firedrake exporter is tested
  against a mocked Firedrake only. Its namespace scrape, first-order
  interpolation, and connectivity handling must be confirmed on a real Icepack
  run in the target container.
- **ICESEE result contract.** ICESEE has no CryoStack result-package schema,
  run-directory abstraction, or provenance record, and its data-assimilation
  diagnostics are not computed or persisted in a shared form. A results view
  for ICESEE requires a scientific exporter, not additional wiring.
- **Agent execution.** The submission backend for approved plans is implemented
  and tested but not connected to the gateway; agent-initiated submission over
  direct SSH is blocked because direct SSH uses a shared service identity; and a
  cloud submission backend for the agent layer is deliberately absent pending
  job-definition allow-listing, a re-derived license check, and per-user S3
  isolation.
- **Cloud qualification.** The AWS Batch path for ISSM needs qualification on a
  controlled account: per-user storage isolation, an allow-listed job
  definition, budget and quota enforcement, lifecycle cleanup, failure-recovery
  tests, and cost attribution.
- **MATLAB licensing.** ISSM's MATLAB dependency blocks its container and cloud
  paths wherever a license is not configured; the reference cloud profile has
  none.
- **Connector protocol surface.** The relay's generic shell command type, its
  process-local session and pending-command state, the unbound one-time
  password bootstrap, and the absence of per-command replay and ownership
  checks must be addressed before multi-user public operation.
- **Persistence scale.** SQLite is appropriate for the current single-node
  deployment; a horizontally scaled service will require a transactional shared
  database and a durable task and session store.

These limitations define the difference between the present research software
stack and sustained community cyberinfrastructure. The implemented components
demonstrate the integration model and support controlled use. Broad deployment
requires formal adapter schemas, scientific qualification tests, hardened
connector and cloud protocols, machine-readable provenance, expanded
observational ingestion, accessibility and user evaluation, documented
operations, and community governance.

# Acknowledgements

This work was supported in part by U.S. National Science Foundation CAREER
award 2235920. The authors thank Renette Jones-Ivey from the University at Buffalo for help with the initial
Jupyter Book backend and Eliza Dawson for developing the LIVIST backend
integrated into CryoStack. Frozen Legacies incorporates historical radar data
and software developed by their respective contributors; contributor and
dataset attribution will be completed in the archival release metadata.

# References
