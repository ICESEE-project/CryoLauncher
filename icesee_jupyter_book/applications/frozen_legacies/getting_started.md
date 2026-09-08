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
      Frozen Legacies Documentation
    </div>

    <h1>Getting Started with Frozen Legacies</h1>

    <p>
      Explore restored Antarctic airborne radar observations,
      survey flight tracks, and LYRA-derived geophysical products
      through the CryoStack platform.
    </p>

    <div class="cryostack-docs-actions">

      <a
        class="cryostack-btn primary"
        href="/frozen-legacies/"
      >
        Open Frozen Legacies
      </a>

      <a
        class="cryostack-btn secondary"
        href="user_manual.html"
      >
        User Manual
      </a>

      <a
        class="cryostack-btn secondary"
        href="developer.html"
      >
        Developer Guide
      </a>

    </div>

  </section>

  <div class="cryostack-app-doc-content">
:::

Frozen Legacies is the historical airborne radar exploration application within CryoStack. It provides a map-based interface for browsing registered Antarctic radar datasets, selecting survey flights, inspecting individual observations, and reviewing associated geophysical quantities.

The application is organized around a simple hierarchy:

```text
Dataset
   ↓
Flight
   ↓
Observation
```

This guide introduces the standard workflow for opening Frozen Legacies, selecting a dataset, exploring flights, and inspecting radar observations.

## Before You Begin

To use Frozen Legacies, you need:

- A modern web browser.
- Access to the CryoStack platform.
- At least one Frozen Legacies dataset registered in the deployment.
- Network access to any external data or image storage required by the selected dataset.

The currently registered dataset contains restored Antarctic airborne radar observations and LYRA-derived quantities.

## Open Frozen Legacies

Open:

[https://cryostack.eas.gatech.edu/frozen-legacies/](https://cryostack.eas.gatech.edu/frozen-legacies/)

The Frozen Legacies interface is organized into two principal areas:

1. **Antarctic map** — displays survey flight tracks and georeferenced radar observations.
2. **Dataset Explorer** — provides dataset and flight controls and displays information for the selected observation.

The navigation bar at the top provides access to:

- Frozen Legacies,
- Getting Started,
- User Manual,
- Developer Guide,
- and your CryoStack account.

## Explore the Antarctic Map

The main application area displays Antarctica using an Antarctic Polar Stereographic map.

The map provides spatial context for:

- airborne survey tracks,
- radar observation locations,
- the South Pole,
- and available geographic reference features.

Use the map controls to zoom in and out.

You can also pan across the map to inspect other regions.

## Select a Dataset

Use the **Dataset** menu in the Dataset Explorer to choose a registered radar collection.

Selecting a dataset updates:

- the available flight list,
- the displayed flight tracks,
- the visible radar observations,
- and the associated dataset metadata.

The current release includes:

**Frozen Legacies LYRA Radar Observations**

Additional datasets can be incorporated through the Frozen Legacies dataset registry.

## Select a Flight

Use the **Flight** menu to choose a survey flight.

When a flight is selected:

- the selected flight track is emphasized,
- unrelated flight tracks are de-emphasized,
- observations are filtered to the selected flight,
- and the map moves to the selected survey area.

Select **All flights** to return to the complete dataset view.

## Inspect an Observation

Click an observation point on the Antarctic map.

The Dataset Explorer will display the available record information.

Depending on the dataset, the selected observation may include:

- observation identifier,
- dataset,
- flight number,
- CBD value,
- frame number,
- latitude,
- longitude,
- echo status,
- ice thickness,
- bed signal-to-noise ratio,
- surface temperature,
- reflectivity,
- attenuation,
- specularity,
- source-file provenance,
- and associated scientific products.

## Observation Status

Observation markers may use different colors to indicate the quality of the radar return.

For the current LYRA-derived observations, statuses may include:

- **Good** — a usable bed return was identified.
- **Weak bed** — the bed return is present but weak.
- **No bed** — no reliable bed return was identified.

The selected observation panel reports the corresponding status.

## Review Dataset Metadata

When an observation is selected, the Dataset Explorer also exposes information about the parent dataset.

This may include:

- collection title,
- dataset identifier,
- campaign,
- institution,
- product family,
- source information,
- and future citation or DOI metadata.

This keeps the observation connected to its scientific provenance.

## Review LYRA-Derived Quantities

The current LYRA dataset may provide derived quantities including:

- ice thickness,
- bed SNR,
- surface temperature,
- reflectivity,
- attenuation,
- and specularity.

These values are displayed when available for the selected observation.

Not every dataset is required to provide the same quantities.

## Radar Preview

The observation panel includes a radar preview area.

When radar imagery becomes available for an observation, the corresponding radar product can be displayed directly in this section.

Until imagery is available, Frozen Legacies displays a placeholder while preserving the rest of the observation metadata.

## Scientific Products

Frozen Legacies is designed to associate scientific products directly with observations.

A dataset may expose products such as:

- radargrams,
- processed echograms,
- source CSV records,
- derived radar products,
- image products,
- and future scientific data formats.

Available products depend on the dataset manifest and storage backend.

## Downloads

Frozen Legacies supports dataset-defined downloads.

Depending on the collection, downloads may include:

- observation records,
- observation GeoJSON,
- flight-track GeoJSON,
- source CSV files,
- radar imagery,
- and other derived products.

Not every dataset is required to provide every download type.

## Dataset Provenance

Each observation retains provenance information connecting it to its original source.

This may include:

- source file,
- flight,
- frame,
- dataset identifier,
- and campaign metadata.

This information is useful when tracing a displayed radar record back to the original processed dataset.

## Current Dataset

The current Frozen Legacies deployment includes the **Frozen Legacies LYRA Radar Observations** collection.

It contains restored Antarctic airborne radar observations and LYRA-derived geophysical quantities.

The frontend itself is dataset-independent. Additional radar collections can be registered without rewriting the core map interface.

## Typical Workflow

A typical Frozen Legacies session follows these steps:

1. Open Frozen Legacies.
2. Select a dataset.
3. Choose a flight or retain **All flights**.
4. Explore the survey area on the Antarctic map.
5. Click an observation marker.
6. Review the observation status.
7. Inspect geographic and LYRA-derived quantities.
8. Review the source provenance.
9. Open available radar imagery or scientific products.
10. Download available products when required.

## Map Reset

Selecting **All flights** returns the application to the broader Antarctic dataset view.

Selecting an individual flight automatically focuses the map on the corresponding survey geometry.

## Authentication

Frozen Legacies is openly accessible — it does not require a CryoStack
account to browse flights, observations, or radar products. It does not yet
provide any account-specific features (saved views, experiments, or
personal settings); those exist for CryoStack's execution-oriented
applications (CryoLauncher, ICESEE), not for this archive viewer.

## Next Steps

After becoming familiar with the application:

- Read the [Frozen Legacies User Manual](user_manual) for a more complete description of the interface and available scientific information.
- Read the [Developer Guide](developer) if you need to add datasets, adapters, products, or storage backends.
- Return to <a href="/frozen-legacies/">Frozen Legacies</a> to continue exploring the available radar observations.

:::{raw} html
  </div>
</div>
:::