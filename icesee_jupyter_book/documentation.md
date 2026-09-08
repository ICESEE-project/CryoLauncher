# Documentation

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

    <h1>Find your way around CryoStack.</h1>

    <p>
      CryoStack is the umbrella platform that connects cryosphere modeling and
      data-assimilation applications to reproducible software environments and
      computing resources. This page is the map — pick where to go next.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="applications/icesheets/getting_started.html">
        CryoLauncher Getting Started
      </a>

      <a class="cryostack-btn secondary" href="resources.html">
        Resources
      </a>
    </div>

  </section>

  <section id="get-started" class="cryostack-section">

    <div class="cryostack-section-label">
      Get Started
    </div>

    <h2>New to CryoStack?</h2>

    <p class="cryostack-section-intro">
      CryoStack applications share one shape: configure, execute, monitor,
      visualize, download. Start with an application.
    </p>

    <div class="cryostack-docs-summary-grid">

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CS</div>
        <h3>CryoStack overview</h3>
        <p>
          What CryoStack is and how the browser, applications, environments,
          and backends fit together — see the <a href="index.html">home page</a>
          and <a href="about.html">About</a>.
        </p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CL</div>
        <h3>CryoLauncher Getting Started</h3>
        <p>
          Run your first ice-sheet simulation and inspect the structured
          results — <a href="applications/icesheets/getting_started.html">open the guide</a>.
        </p>
      </div>

    </div>

  </section>

  <section id="applications" class="cryostack-section">

    <div class="cryostack-section-label">
      Applications
    </div>

    <h2>Choose an application.</h2>

    <p class="cryostack-section-intro">
      Each application maintains its own documentation. Maturity differs — see
      the badges.
    </p>

    <div class="cryostack-docs-app-grid">

      <article class="cryostack-docs-app-card">

        <div class="cryostack-card-eyebrow">Numerical Modeling</div>
        <div class="cryostack-card-tag">Simulation</div>

        <h3>CryoLauncher</h3>

        <p>
          Run supported ice-sheet models through a browser interface, with a
          guided or an advanced workspace workflow, on remote and HPC
          resources.
        </p>

        <div class="cryostack-mini-list">
          <span>ISSM</span>
          <span>Icepack</span>
          <span>Containers</span>
          <span>Spack</span>
        </div>

        <div class="cryostack-docs-card-actions">
          <a href="/icesheets/" data-requires-auth="true">Open Application</a>
          <a href="applications/icesheets/getting_started.html">Getting Started</a>
          <a href="applications/icesheets/user_manual.html">User Manual</a>
          <a href="applications/icesheets/resources.html">Resources</a>
        </div>

      </article>

      <article class="cryostack-docs-app-card">

        <div class="cryostack-card-eyebrow">State and Parameter Estimation</div>
        <div class="cryostack-card-tag green">Data Assimilation</div>

        <h3>ICESEE</h3>

        <p>
          Run ensemble data-assimilation workflows with supported numerical
          models for state estimation and parameter inference.
        </p>

        <div class="cryostack-mini-list green-list">
          <span>EnKF</span>
          <span>DEnKF</span>
          <span>EnTKF</span>
          <span>EnRSKF</span>
        </div>

        <div class="cryostack-docs-card-actions">
          <a href="/icesee-gui/" data-requires-auth="true">Open Application</a>
          <a href="applications/icesee/getting_started.html">Getting Started</a>
          <a href="applications/icesee/user_manual.html">User Manual</a>
          <a href="applications/icesee/resources.html">Resources</a>
        </div>

      </article>

      <article class="cryostack-docs-app-card">

        <div class="cryostack-card-eyebrow">Scientific Data Products</div>
        <div class="cryostack-card-tag green">Interactive Explorer</div>

        <h3>LIVIST</h3>

        <p>
          Explore Antarctic ice-sheet temperature products inferred from radar
          observations and constrained by borehole measurements.
        </p>

        <div class="cryostack-mini-list green-list">
          <span>Radar</span>
          <span>Boreholes</span>
          <span>Temperature</span>
          <span>Antarctica</span>
        </div>

        <div class="cryostack-docs-card-actions">
          <a href="/livist/" data-requires-auth="true">Open Application</a>
          <a href="/livist/docs/livist_user_manual/">User Manual</a>
          <a href="/livist/docs/api/">Python Documentation</a>
          <a href="https://source.coop/englacial/ice-sheet-temperature" target="_blank" rel="noopener noreferrer">Data Repository</a>
        </div>

      </article>

      <article class="cryostack-docs-app-card">

        <div class="cryostack-card-eyebrow">Historical Radar Archive</div>
        <div class="cryostack-card-tag gray">Data Explorer</div>

        <h3>Frozen Legacies</h3>

        <p>
          Explore historical Antarctic airborne radar surveys, flight tracks,
          and processed SPRI–NSF–TUD campaign observations.
        </p>

        <div class="cryostack-mini-list green-list">
          <span>Historical Radar</span>
          <span>Ross Ice Shelf</span>
          <span>Ice Thickness</span>
        </div>

        <div class="cryostack-docs-card-actions">
          <a href="/frozen-legacies/" data-requires-auth="false">Open Application</a>
          <a href="applications/frozen_legacies/getting_started.html">Getting Started</a>
          <a href="applications/frozen_legacies/user_manual.html">User Manual</a>
          <a href="applications/frozen_legacies/developer.html">Developer Guide</a>
        </div>

      </article>

    </div>

  </section>

  <section id="execution" class="cryostack-section">

    <div class="cryostack-section-label">
      Execution
    </div>

    <h2>Where runs execute.</h2>

    <p class="cryostack-section-intro">
      Applications connect to computing resources through consistent execution
      backends. Details and settings are in the CryoLauncher User Manual.
    </p>

    <div class="cryostack-docs-environments">

      <div>
        <h3>Remote / HPC <span class="cryostack-status supported">Supported</span></h3>
        <p>
          Linux servers and Slurm-managed clusters (such as Georgia Tech PACE)
          over SSH or the CryoStack Connector —
          <a href="applications/icesheets/user_manual.html#execution-modes-and-backends">execution guide</a>.
        </p>
      </div>

      <div>
        <h3>Containers <span class="cryostack-status supported">Supported</span></h3>
        <p>
          Digest-pinned tested Docker / OCI images and local SIF builds —
          see <a href="https://github.com/ICESEE-project/ICESEE-Containers" target="_blank" rel="noopener noreferrer">ICESEE-Containers</a>.
        </p>
      </div>

      <div>
        <h3>ICESEE-Spack</h3>
        <p>
          Managed Spack environments with a first-time check-and-prepare
          workflow —
          <a href="applications/icesheets/user_manual.html#preparing-and-launching-runs">preparing runs</a>,
          <a href="https://github.com/ICESEE-project/ICESEE-Spack" target="_blank" rel="noopener noreferrer">ICESEE-Spack</a>.
        </p>
      </div>

      <div>
        <h3>Cloud <span class="cryostack-status dev">In validation</span></h3>
        <p>
          Bring-your-own AWS account, connected once through a CloudFormation
          role and used with temporary credentials only. Infrastructure
          provisioning (storage, container registry, AWS Batch) and the run
          contract are wired for CryoLauncher and ICESEE; the full onboarding
          and operational lifecycle is still being validated end-to-end —
          see the <a href="docs/hpc_cloud.html">Cloud Run Guide</a>.
        </p>
      </div>

    </div>

  </section>

  <section id="user-workflows" class="cryostack-section">

    <div class="cryostack-section-label">
      User Workflows
    </div>

    <h2>How you work in CryoLauncher.</h2>

    <div class="cryostack-docs-environments">

      <div>
        <h3>Basic &amp; Advanced</h3>
        <p>
          Guided, validated configuration
          (<a href="applications/icesheets/user_manual.html#basic-mode">Basic</a>)
          versus a user-owned workspace editor
          (<a href="applications/icesheets/user_manual.html#advanced-mode">Advanced</a>).
        </p>
      </div>

      <div>
        <h3>My Workspace</h3>
        <p>
          Private, persistent, user-isolated examples and files;
          application examples stay read-only —
          <a href="applications/icesheets/user_manual.html#application-examples-vs-my-workspace">examples</a>.
        </p>
      </div>

      <div>
        <h3>Datasets</h3>
        <p>
          A reusable dataset area, referenced from examples and staged with the
          run —
          <a href="applications/icesheets/user_manual.html#dataset-management">dataset guide</a>.
        </p>
      </div>

      <div>
        <h3>Results &amp; visualization</h3>
        <p>
          Structured result discovery and deterministic Solution / Field /
          Timestep rendering —
          <a href="applications/icesheets/user_manual.html#results">results</a>,
          <a href="applications/icesheets/user_manual.html#visualization">visualization</a>.
        </p>
      </div>

    </div>

  </section>

  <section id="developers" class="cryostack-section">

    <div class="cryostack-section-label">
      Developers
    </div>

    <h2>Building on CryoStack.</h2>

    <p class="cryostack-section-intro">
      CryoStack separates the web interface, application layer, execution
      backends, and scientific data sources so each can evolve independently.
    </p>

    <div class="cryostack-docs-environments">

      <div>
        <h3>Source code</h3>
        <p>
          The gateway, application layer, connector, and deployment live in the
          <a href="https://github.com/ICESEE-project/CryoLauncher" target="_blank" rel="noopener noreferrer">CryoLauncher repository</a>,
          under the <a href="https://github.com/ICESEE-project" target="_blank" rel="noopener noreferrer">ICESEE project</a>.
        </p>
      </div>

      <div>
        <h3>Application developer docs</h3>
        <p>
          Application-specific developer documentation lives with each app — for
          example the
          <a href="applications/frozen_legacies/developer.html">Frozen Legacies Developer Guide</a>.
        </p>
      </div>

      <div>
        <h3>CryoStack Developer Guide</h3>
        <p>
          The <a href="docs/developer_guide.html">Developer Guide</a> covers
          the platform architecture, application development, the shared
          application-shell UI, model adapters, the result and visualization
          contracts, testing, building a connector locally, and the
          contribution workflow. Operating a deployment (production connector
          publishing, release store, nginx, service administration) is a
          separate, role-restricted Maintainer Guide.
        </p>
      </div>

    </div>

  </section>

  <section id="reference" class="cryostack-section cryostack-docs-next">

    <div class="cryostack-section-label">
      Reference
    </div>

    <h2>Look something up.</h2>

    <p>
      <a href="resources.html">Resources</a> — an ecosystem-wide index of
      applications, models, environments, datasets, and repositories.<br>
      <a href="docs/hpc_cloud.html">Cloud Run Guide</a> — connecting your own
      AWS account and launching, monitoring, and retrieving a cloud run.<br>
      <a href="applications/icesheets/user_manual.html#troubleshooting">Troubleshooting</a> —
      common CryoLauncher issues and fixes.<br>
      <a href="about.html#citation">Citation</a> and
      <a href="about.html">About</a> — why CryoStack exists, design principles,
      and how to cite it.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="#applications">Browse Applications</a>
      <a class="cryostack-btn secondary" href="docs/hpc_cloud.html">Cloud Run Guide</a>
    </div>

  </section>

</div>
:::
