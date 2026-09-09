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
resources. It connects ice-sheet modeling, ensemble data assimilation, and
the discovery and reuse of historical radar observations behind one shared
platform rather than as separate tools. Its current applications are
**CryoLauncher** for configuring and running ice-sheet models; **ICESEE**
for ensemble-based state and parameter estimation [@kyanjo2026icesee];
**LIVIST** (Living Ice Sheet Temperature) for exploring Antarctic
englacial-temperature products inferred from radar and constrained by
boreholes; and **Frozen Legacies** for discovering and working with
historical Antarctic radar observations and derived products.

CryoStack grew from deployment tooling for ICESEE into a wider stack for the
computational cryosphere. Its design treats the scientific experiment,
dataset, and application as related but independent objects: an application
retains its domain-specific interface while reusing shared identity,
persistence, execution, and deployment services, and a compute backend
implements a common lifecycle without being embedded in a particular
frontend. This lets a researcher move a configured experiment across a
workstation, an institutional HPC cluster, and cloud resources, and lets a
new application or dataset collection join the platform without rebuilding
it.

CryoStack is available at <https://cryostack.eas.gatech.edu/> and its source
is maintained at <https://github.com/ICESEE-project/CryoStack>.

# Statement of need

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
research-software or HPC support. No shared layer currently spans model
configuration, execution, and experiment history across these settings.

CryoStack addresses this missing layer. It is intended for researchers moving
between exploratory and production workflows, collaborators who do not share
the same computing environment, radar scientists preserving difficult legacy
observations, and instructors who need a consistent entry point for
computational examples. Browser access reduces the initial interaction cost,
while remote execution preserves the use of resources already authorized for
the user. The architectural goal is not to hide the scientific software or
institutional policy. It is to make the transitions among applications, data,
and resources explicit, repeatable, and inspectable.

# State of the field

ISSM provides continental-scale ice-sheet modeling and inversion
[@larour2012issm], Icepack provides composable glacier-flow modeling in
Python [@shapero2021icepack], and DART and PDAF provide mature
general-purpose data-assimilation capabilities [@anderson2009dart;
@nerger2013pdaf]. ICESEE adds model-agnostic ensemble Kalman filtering
tailored to ice-sheet applications, multiple filter variants, MPI
parallelism, and couplings to ISSM and Icepack [@kyanjo2026icesee]. Each of
these packages solves a specific scientific or numerical problem well, and
CryoStack does not reimplement any of them.

What none of these packages provides, by itself, is a common access and
operations layer spanning identity, data discovery, model configuration,
remote execution, experiment history, and application deployment across a
heterogeneous set of models and computing environments. CryoStack occupies
this gap: it builds on ISSM, Icepack, and ICESEE rather than competing with
them, and its distinct contribution is the shared layer connecting them to
data, experiments, and heterogeneous execution.

# Software design

CryoStack separates access and operations, scientific applications, execution
backends, and reproducible software environments (Figure 1). Identity and
experiment persistence live outside the applications; per-user workspace
roots are enforced by an explicit containment check rather than by
convention; a capability registry states, in one place, what CryoStack can do
with each model — whether a curated configuration subset exists, whether it
exports a structured result package, requires a proprietary license, and
which execution backends apply; and deployable applications are declared in a
registry rather than hard-coded into a single service. This lets an
application keep its domain-specific interface while reusing identity,
persistence, execution, and deployment services, and lets a compute backend
implement a common submit/status/logs/terminate lifecycle independent of any
one frontend.

![CryoStack's current layered architecture. A shared gateway and operations plane supplies identity, per-user workspaces, experiments, administration, deployment, and health services to four scientific applications. Shared contracts cover model capabilities, structured results, and visualization. Modeling and data-assimilation workflows can use local, connector-mediated HPC, or AWS Batch execution backends over reproducible Spack and container environments.](cryostack_architecture.png)

**Figure 1:** CryoStack platform architecture; solid components are present
in the repository (qualification status of the execution backends is
detailed below).

The persistence layer stores users, sessions, saved configurations,
per-application workspace state, and experiments — an immutable
configuration snapshot with application, backend, job identifiers, output
paths, and a status-event timeline — in SQLite. Canonical examples remain
read-only and are copied into a user-owned working copy before any edit or
run, so two users acting
concurrently cannot overwrite each other's inputs or outputs. A user can
return to a saved workspace, reuse a named configuration, and relate
scheduler state to the configuration that produced it — a basis for fuller
provenance that current fields do not yet fully capture.

The current applications exercise this platform differently. CryoLauncher
configures and runs ISSM and Icepack, each exposing a curated parameter
subset validated before submission and packaging outputs into a
transport-neutral result schema (`cryostack.issm.results`,
`cryostack.icepack.results`) that a model-free reader and a shared
visualization layer can render without the model's own runtime. ICESEE
supplies ensemble state and parameter estimation [@kyanjo2026icesee];
CryoStack does not reimplement its filtering algorithms but exposes its
configuration and execution through the same identity and connector
infrastructure as CryoLauncher — it does not yet emit a result package under
this shared contract, and its data-assimilation diagnostics are not yet part
of a shared schema. LIVIST keeps its own frontend and documentation while
sharing the platform's routing and application context. Frozen Legacies
exercises a second kind of extensibility: a historical radar collection needs
a dataset manifest and ingestion adapter rather than a model execution
adapter, reusing the same identity and deployment services to build a
browsable catalog with geolocated flight lines. Not every application uses
every execution backend; each declares, through the capability registry,
which backends it currently supports.

Execution is abstracted behind a common backend contract implemented by
local, connector-mediated remote-HPC, and AWS Batch drivers, so an
application's scientific configuration does not change when its execution
target does. A packaged workstation connector exchanges SSH, rsync, and
Slurm operations for commands sent over an authenticated relay, so the
platform never holds cluster credentials or opens an inbound connection to
institutional resources; its generic shell command type and process-local
session state remain documented gaps before multi-user public operation. The
AWS driver exposes the same discovery, provisioning, submission, and
status/log/termination operations, using only ambient CLI credentials and no
static keys, over Spack-built [@gamblin2015spack] or Apptainer-containerized
[@kurtzer2017singularity] environments. This shared driver serves both
CryoLauncher/ISSM and ICESEE: a personal AWS account connects through a
connection-scoped CloudFormation onboarding flow, and ICESEE's Lorenz-96
example has run end to end through this path at NP=1 (single-process
execution). That does not extend to ICESEE's other examples, to
multi-process execution, or to the ISSM Batch path, which still runs against
a single account-wide bucket without per-user isolation or an allow-listed
job definition and additionally requires a MATLAB license the reference
deployment does not provide: architectural reach across applications is
currently broader than what has been validated end to end for either one.

An experimental human-in-the-loop layer lets an assistant assemble, not
submit, a run: a request becomes a declarative plan, validated against the
same rules as the manual interface and approved by a human before reaching
execution infrastructure, and its tools are read-only. Reproducibility to
date is protocol-level rather than archival: the lifecycle preserves each
experiment's configuration, backend, and status timeline, and its record
already provides hooks — though not yet populated fields — for environment
digests, checksums, and exportable run manifests.

Verification combines a Python test suite of more than 1,800 tests across the
gateway, authentication, model adapters, connector, and cloud modules with a
separate offline acceptance command checking agent safety properties,
capability-registry consistency, and workspace isolation as read-only
invariants; this confirms structural and functional correctness, not the
scientific correctness of a model run. The codebase is distributed under the
MIT License, though newly modularized source files still carry BSD-3-Clause
identifiers that should be reconciled before a formal release. CryoStack's
core platform and local scientific workflows are complete enough for their
stated research purpose, while the remote-HPC and cloud paths above carry
explicit, documented qualification boundaries rather than an implied general
readiness.

# Research impact statement

CryoStack's evidence to date is functional and architectural rather than
adoption-based, and this section states that directly. Two ice-sheet models
(ISSM, Icepack) are integrated with curated configuration, execution, and a
structured result-and-visualization contract exercised through automated
tests, not merely described. ICESEE's ensemble data-assimilation workflow
[@kyanjo2026icesee], developed under NSF CAREER award 2235920, has run
through CryoStack both locally and end to end on AWS Batch for its
Lorenz-96 example — a real workflow exercised across two execution backends
through the same platform services, not a synthetic placeholder. Frozen
Legacies integrates an actual historical dataset (LYRA-derived airborne radar
records) into a working catalog with geolocation and processing tools, and
LIVIST integrates a deployed radar/borehole temperature-inference
application, showing the platform absorbing two application patterns beyond
model execution. This is backed by a suite of more than 1,800 automated
tests and a separate offline invariant-checking command, both reproducible
by an external reviewer without institutional access. Together, these
establish credible near-term
significance for a reviewer assessing whether CryoStack is functioning,
extensible infrastructure rather than a design proposal; realized external
adoption remains to be demonstrated.

# Acknowledgements

This work was supported in part by U.S. National Science Foundation CAREER
award 2235920. The authors thank Renette Jones-Ivey from the University at
Buffalo for help with the initial Jupyter Book backend and Eliza Dawson for
developing the LIVIST backend integrated into CryoStack. Frozen Legacies
incorporates historical radar data and software developed by their
respective contributors; contributor and dataset attribution will be
completed in the archival release metadata.

# References
