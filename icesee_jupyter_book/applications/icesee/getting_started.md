# Getting Started 

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>

<div class="cryostack-app-doc-page">

  <section class="cryostack-app-doc-hero">

    <div class="cryostack-section-label">
      ICESEE Documentation
    </div>

    <h1>Getting Started with ICESEE</h1>

    <p>
      Configure and run your first ensemble data assimilation workflow
      through CryoStack using supported models, filters, observations,
      and computing backends.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="/icesee-gui/">
        Open ICESEE
      </a>

      <a class="cryostack-btn secondary" href="user_manual.html">
        User Manual
      </a>

      <a class="cryostack-btn secondary" href="resources.html">
        Resources
      </a>
    </div>

  </section>

  <div class="cryostack-app-doc-content">
:::

ICESEE, the Ice Sheet State and Parameter Estimator, is the data assimilation application within CryoStack. It combines numerical models, ensemble-based filtering methods, and observations to estimate model states and uncertain parameters.

This guide introduces the standard workflow for selecting an example, choosing an assimilation method, configuring an ensemble, running the experiment, and reviewing the results.

## Before You Begin

To use ICESEE, you need:

- A modern web browser.
- Access to the CryoStack platform.
- A supported ICESEE example.
- A configured scientific environment for the selected model.
- Access to local, remote, HPC, or cloud resources when required.

Some examples can run directly on the CryoStack server, while larger ice-sheet workflows may require a remote or HPC backend.

## Open ICESEE

Open:

[https://cryostack.eas.gatech.edu/icesee-gui/](https://cryostack.eas.gatech.edu/icesee-gui/)

The ICESEE interface is organized into two principal areas:

1. **Run settings** — select the execution mode, example, preset, filter, ensemble configuration, and output options.
2. **Run log and Results preview** — monitor execution and inspect generated reports, diagnostics, and output products.

## Choose an Execution Mode

ICESEE currently supports multiple execution pathways.

### Local

Local mode runs the selected example on the system hosting CryoStack.

Use Local mode for:

- tutorials,
- demonstrations,
- Lorenz-96 experiments,
- testing,
- and smaller development workflows.

### Remote

Remote mode runs the workflow on another workstation, server, or HPC cluster.

Remote execution may require:

- SSH configuration,
- authentication,
- a connector session,
- a remote execution directory,
- and scheduler settings.

### Cloud

Cloud mode runs ICESEE on your own AWS account (bring-your-own-AWS), through
the same Connect AWS Account → Prepare cloud → Review & Launch flow as
CryoLauncher — see the platform-wide
[Cloud Run Guide](https://cryostack.eas.gatech.edu/docs/hpc_cloud.html)
for the full walkthrough and current status.

Today this path is verified end-to-end for exactly one configuration: the
**Lorenz-96** example at a single process (**NP = 1**). Other examples or a
higher process count are not yet verified and CryoStack will not let you
launch them — the Review card explains why.

## Select an Example

The **Example** menu lists the ICESEE applications available in the configured installation.

Examples may include:

- Lorenz-96,
- ISSM,
- Icepack,
- one-dimensional flowline models,
- and other supported data assimilation experiments.

The examples displayed in the GUI depend on the installed ICESEE repository and available scientific environments.

## Choose a Preset

A preset provides a predefined configuration for the selected example.

Presets may define:

- physical parameters,
- modeling parameters,
- ensemble settings,
- assimilation frequency,
- observation configuration,
- and output behavior.

Use the default preset for your first run unless the example documentation recommends another configuration.

## Choose an Assimilation Method

The **Filter** menu selects the ensemble-based data assimilation method.

ICESEE currently supports methods such as:

- **EnKF** — Ensemble Kalman Filter,
- **DEnKF** — Deterministic Ensemble Kalman Filter,
- **EnTKF** — Ensemble Transform Kalman Filter,
- **EnRSKF** — Ensemble Reduced Square Root Kalman Filter.

For a first experiment, use the default filter provided by the selected example.

## Configure the Ensemble

The ensemble size controls the number of model realizations used during the assimilation workflow.

A larger ensemble may improve the representation of forecast uncertainty, but it also increases:

- computational cost,
- memory use,
- communication requirements,
- and runtime.

For introductory examples, use the default ensemble size.

## Set the Random Seed

The random seed controls reproducibility for workflows that generate random perturbations, initial ensembles, or synthetic observations.

Using the same seed allows the experiment to be repeated with the same stochastic initialization, provided the remaining configuration and software environment are unchanged.

## Select the Output

The **Output** menu determines which available result set or reporting mode is used.

Depending on the example, outputs may include:

- true-state comparisons,
- wrong-model experiments,
- ensemble diagnostics,
- RMSE plots,
- parameter estimates,
- state trajectories,
- and generated reports.

## Review the Full Configuration

ICESEE exposes the selected configuration through expandable parameter sections.

These may include:

- physical parameters,
- modeling parameters,
- ensemble Kalman filter parameters,
- observation settings,
- and output options.

For a first run, review the values but avoid changing advanced settings until the default workflow runs successfully.

## Run Your First ICESEE Experiment

A typical first run follows these steps:

1. Open ICESEE.
2. Select **Local** mode.
3. Choose a runnable example, such as Lorenz-96.
4. Select the default preset.
5. Choose the default assimilation filter.
6. Confirm the ensemble size.
7. Set or retain the random seed.
8. Select the required output configuration.
9. Enable report generation when available.
10. Launch the experiment.
11. Monitor the Run Log.
12. Inspect the Results preview after completion.

## Example: Lorenz-96

Lorenz-96 is a useful first ICESEE example because it is computationally lightweight and demonstrates the complete data assimilation cycle.

A typical Lorenz-96 workflow includes:

1. generating or loading the true state,
2. initializing the ensemble,
3. advancing the model forecast,
4. creating or loading observations,
5. applying the selected filter,
6. updating the ensemble,
7. evaluating diagnostics,
8. and generating a report.

The GUI may expose options for:

- ensemble size,
- random seed,
- filter selection,
- preset,
- and report generation.

## Example: Ice-Sheet Data Assimilation

ISSM and Icepack workflows follow the same general assimilation structure but may require more computational resources.

A typical ice-sheet workflow may involve:

- model initialization,
- state-vector construction,
- ensemble generation,
- forward model execution,
- observation loading,
- state updates,
- parameter estimation,
- and distributed ensemble execution.

These workflows are usually better suited to remote or HPC execution.

## Monitor the Run Log

The Run Log reports the current execution status.

It may display:

- configuration loading,
- parameter-file paths,
- runner paths,
- environment activation,
- ensemble initialization,
- forecast progress,
- assimilation steps,
- report generation,
- warnings,
- and errors.

The log is the first place to inspect when a workflow does not complete successfully.

## View Results

The Results preview may display:

- generated reports,
- state trajectories,
- truth-versus-estimate plots,
- RMSE diagnostics,
- ensemble statistics,
- parameter estimates,
- and downloadable outputs.

The available preview depends on the selected example and output configuration.

## Report Generation

When report generation is enabled, ICESEE may run a results-reading or reporting workflow after the main experiment completes.

A report may include:

- experiment metadata,
- model configuration,
- filter configuration,
- ensemble diagnostics,
- error metrics,
- and scientific figures.

## Next Steps

After completing your first experiment:

- Read the [ICESEE User Manual](user_manual) for a full description of the interface and workflow.
- Review [ICESEE Resources](resources) for repositories, publications, models, and data assimilation references.
- Use remote or HPC execution for larger ensembles.
- Open CryoLauncher when you need a model-only simulation without data assimilation.

:::{raw} html
  </div>
</div>
:::
