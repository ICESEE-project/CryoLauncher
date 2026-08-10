---
title: 'CryoStack: A browser-first scientific platform for integrated cryosphere data, modeling, and data-assimilation workflows'
tags:
  - Python
  - cryosphere
  - scientific gateways
  - ice-sheet modeling
  - data assimilation
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
date: 9 August 2026
bibliography: paper.bib
---

# Summary

CryoStack is an open-source scientific platform that connects cryosphere data,
numerical models, ensemble data assimilation, and heterogeneous computing
resources through a common browser interface. The platform currently integrates
three complementary applications: **CryoLauncher** for configuring and running
ice-sheet models, **ICESEE** for ensemble-based state and parameter estimation,
and **LIVIST** for exploring Antarctic englacial-temperature products. A shared
gateway supplies navigation, documentation, user workspaces, reusable
configurations, experiment records, and routes to local, remote, Slurm-managed,
and cloud execution environments.

CryoStack grew from deployment tooling for the Ice Sheet State and Parameter
Estimator (ICESEE) [@kyanjo2026icesee] into a broader platform for the
computational cryosphere. It therefore treats a scientific workflow—not an
individual model or algorithm—as the primary unit of interaction. A researcher
can inspect an observational product, configure a model experiment, choose an
execution backend, monitor a run, and return to its configuration and outputs
without learning a different deployment mechanism for every application.
CryoStack is available at <https://cryostack.eas.gatech.edu/> and its source is
maintained at <https://github.com/ICESEE-project/CryoStack>.

# Statement of Need

Cryosphere research increasingly combines large observational products,
numerical ice-sheet models, inverse methods, and ensemble simulations. These
components have very different software and computing requirements. Interactive
data exploration is well suited to the browser, model development may happen on
a workstation, and production experiments commonly require MPI-enabled
libraries and a batch-scheduled cluster. Reproducing such work can require
installing model-specific dependencies, transferring inputs, writing scheduler
scripts, tracking job identifiers, retrieving outputs, and recording the exact
configuration used.

Existing community software provides strong capabilities within individual
parts of this lifecycle. ISSM provides continental-scale ice-sheet modeling and
inversion [@larour2012issm], Icepack provides composable glacier-flow modeling
in Python [@shapero2021icepack], and general data-assimilation frameworks such
as DART and PDAF provide mature ensemble methods [@anderson2009dart;
@nerger2013pdaf]. ICESEE adds model-agnostic ensemble Kalman filtering tailored
to ice-sheet applications, multiple filter variants, MPI parallelism, and
couplings to ISSM and Icepack [@kyanjo2026icesee]. However, the scientific
software alone does not provide a common access layer spanning data discovery,
model configuration, assimilation, and remote execution.

CryoStack fills this integration gap. It is intended for researchers who need
to move between exploratory and production workflows, collaborators who do not
share the same computing environment, and instructors who need a consistent
entry point for computational examples. The browser interface lowers the
initial interaction cost while preserving access to external computing
resources for workloads that cannot or should not run on the web host.

# Platform Design

CryoStack separates the user-facing gateway, scientific applications,
execution backends, and reproducible software environments (Figure 1). This
separation lets each application evolve independently while sharing common
services and deployment pathways.

![CryoStack's layered architecture. The gateway provides a common entry point to three scientific applications, while modeling and data-assimilation workflows can use local, remote HPC, or cloud execution backends. Spack environments and containers provide reproducible software layers.](cryostack_architecture.png){ width=95% }

**Figure 1:** CryoStack platform architecture and principal workflow paths.

## Gateway and workspaces

An Nginx reverse proxy terminates the public connection and forwards traffic to
an `aiohttp` gateway. The gateway serves the Jupyter Book documentation,
proxies HTTP and WebSocket traffic to interactive Voilà applications, and
routes the React-based LIVIST frontend. Jupyter technologies provide an
appropriate bridge between executable scientific Python and browser interfaces
[@kluyver2016jupyter], while the gateway presents the applications under one
site rather than as unrelated notebook servers.

Authenticated workspaces store user profiles, application preferences, saved
configuration documents, and experiment records in SQLite. Saved
configurations are schema-versioned and can be reused across sessions.
Experiment records retain a configuration snapshot together with the selected
backend, status, scheduler job identifier, cluster, working and output paths,
log location, exit status, and timestamps. These records establish the basis
for provenance without requiring each application to implement a separate
account and persistence layer.

## Scientific applications

**CryoLauncher** provides a form-based interface for numerical ice-sheet
experiments. It exposes model parameters and execution choices while retaining
the underlying model's native input and output conventions. The current model
registry includes ISSM, Icepack, a one-dimensional flowline model, and
Lorenz-96 for lightweight demonstrations and system testing. Users can execute
small examples locally or stage larger jobs to configured compute resources.

**ICESEE** exposes ensemble state-estimation and parameter-inference workflows.
Users select a model, ensemble size, observations, filter settings, and compute
target through the same interaction pattern used by CryoLauncher. The
integrated ICESEE library supports the ensemble Kalman filter and deterministic
variants, parallel ensemble execution, and model couplings described in
[@kyanjo2026icesee]. CryoStack does not reimplement those algorithms; it makes
them configurable, executable, and observable through the platform.

**LIVIST** (Living Ice Sheet Temperature) is an interactive explorer for
Antarctic englacial-temperature products inferred from radar observations and
constrained by borehole measurements. Its integration expands CryoStack from a
model-launching environment into a platform that also serves scientific data
and documentation. LIVIST is implemented as a React and TypeScript application
and is routed by the same gateway as the Python applications.

# Execution and Reproducibility

CryoStack supports multiple execution modes behind a common application
interface. Local mode runs lightweight workflows on the application host.
Remote mode stages configuration and input files over SSH, activates the
configured environment, submits a Slurm script, parses the scheduler job
identifier, monitors status, streams logs, and retrieves outputs. For protected
institutional systems, an optional connector runs on the user's workstation and
establishes an outbound WebSocket session with CryoStack. SSH, file transfer,
and Slurm operations then occur from the connector using the user's existing
network and institutional access. The platform also includes deployment
configurations for cloud-hosted Slurm resources.

Two complementary environment strategies support portability. ICESEE-Spack
uses Spack [@gamblin2015spack] to resolve source builds against site-specific
compilers, MPI implementations, and system libraries. This is useful on HPC
systems where performance and compatibility with the local software stack are
important. ICESEE-Containers provides Docker and Apptainer images for portable,
preconfigured execution; Apptainer follows the mobility-of-compute model
developed for scientific containers [@kurtzer2017singularity]. Together, these
paths let a workflow retain a consistent scientific configuration while its
software environment is adapted to a laptop, cloud instance, or institutional
cluster.

A typical remote experiment proceeds as follows:

1. The user selects CryoLauncher or ICESEE and edits a configuration in the
   browser.
2. CryoStack validates and snapshots the configuration and associates it with
   an experiment record.
3. The execution layer stages inputs and either runs locally or submits the job
   to a remote Slurm backend using a Spack or container environment.
4. Job state and logs are returned to the application while scheduler and path
   metadata are recorded in the workspace.
5. The user inspects or downloads outputs and can reuse the saved configuration
   for a subsequent experiment.

# Research and Educational Use

CryoStack offers a single location for workflows at different levels of
complexity. A learner can begin with a Lorenz-96 example and inspect the role of
ensemble size and filter choice. A modeler can configure ISSM or Icepack without
hand-editing every scheduler script. A researcher can use the same interface to
move a tested configuration from a small local run to an MPI-enabled Slurm
environment. LIVIST provides a data-centered entry point that can support
future workflows linking observational products to initialization, validation,
or assimilation.

The platform is deliberately modular. Adding an application requires a
documented route and application adapter rather than modification of every
existing tool. Adding a compute resource requires a backend configuration while
the scientific application and saved configuration schema remain stable. This
design makes CryoStack a foundation for additional cryosphere data services,
models, analysis tools, and workflow backends.

# Availability and Limitations

CryoStack is distributed under the MIT License. The integrated projects retain
their own licenses, and users should cite the scientific models, datasets, and
applications used in an experiment. The source repository includes the gateway,
application interfaces, authentication and persistence services, remote
connector, cloud configuration, documentation, and a pinned copy of ICESEE.

CryoStack does not remove institutional access controls or make all workloads
suitable for browser-host execution. Remote use still requires an authorized
account, network access such as a VPN where applicable, and a compatible
software environment on the target system. At present, backend and
application adapters contain platform-specific configuration that should be
generalized before broad multi-institutional deployment. Planned work includes
formal release archives, expanded automated testing across backends, richer
machine-readable provenance, additional community applications, and clearer
administrator interfaces for registering resources.

# Acknowledgements

This work was supported in part by U.S. National Science Foundation CAREER
award 2235920. The authors thank Renette Jones-Ivey and Justin Simle at Georgia
Tech PACE for infrastructure support and acknowledge the open-source
communities supporting Jupyter, Voilà, Spack, Apptainer, ISSM, Icepack, and the
other scientific software integrated by CryoStack.

# References
