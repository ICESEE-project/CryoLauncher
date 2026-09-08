# CryoStack

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>
:::

:::{raw} html
<div class="cryostack-home">

  <section class="cryostack-hero-simple">
    <div class="cryostack-hero-content">

      <div class="cryostack-kicker">
        Cryosphere Computing Platform
      </div>

      <h1>CryoStack</h1>

      <p class="cryostack-hero-description">
        The umbrella platform that connects cryosphere modeling and data
        assimilation applications to reproducible software environments and
        computing resources — from a laptop to an HPC cluster.
      </p>

      <div class="cryostack-hero-statements">
        <span>Run simulations.</span>
        <span>Assimilate observations.</span>
        <span>Explore scientific datasets.</span>
        <span>Scale from laptops to supercomputers.</span>
      </div>

      <div class="cryostack-actions">
        <a
          class="cryostack-btn primary"
          href="documentation.html">
          Documentation
        </a>

        <a
          class="cryostack-btn secondary"
          href="#applications">
          Explore Applications
        </a>
      </div>

      <div class="cryostack-capabilities">
        <span>Simulation</span>
        <span>Data Assimilation</span>
        <span>Data Products</span>
        <span>HPC Computing</span>
      </div>
    </div>

  </section>

  <section id="applications" class="cryostack-section">
    <div class="cryostack-section-label">CryoStack Ecosystem</div>

    <h2>Choose the workflow that fits your research.</h2>

    <p class="cryostack-section-intro">
      CryoStack brings together numerical modeling, data assimilation,
      and scientific data products within one connected platform.
    </p>

    <div class="cryostack-grid">

      <div class="cryostack-card featured">
        <div class="cryostack-card-eyebrow">Numerical Modeling</div>
        <div class="cryostack-card-tag">Model Simulation</div>

        <h3>CryoLauncher</h3>

        <p>
          Run supported ice-sheet models directly through an interactive
          browser interface.
        </p>

        <div class="cryostack-mini-list">
          <span>ISSM</span>
          <span>Icepack</span>
          <span>Containers</span>
          <span>Spack</span>
        </div>

        <a
          class="cryostack-card-btn"
          href="/icesheets/"
          data-requires-auth="true"
        >
          Open Modeling GUI
        </a>
      </div>

      <div class="cryostack-card featured">
        <div class="cryostack-card-eyebrow">State and Parameter Estimation</div>
        <div class="cryostack-card-tag green">
          Data Assimilation
        </div>

        <h3>ICESEE</h3>

        <p>
          Run coupled ICESEE workflows for state estimation, parameter
          inference, and ensemble-based data assimilation with supported
          ice-sheet models.
        </p>

        <div class="cryostack-mini-list green-list">
          <span>EnKF</span>
          <span>DEnKF</span>
          <span>EnTKF</span>
          <span>EnRSKF</span>
        </div>

        <a
          class="cryostack-card-btn green-btn"
          href="/icesee-gui/"
          data-requires-auth="true"
        >
          Open ICESEE GUI
        </a>
      </div>

      <div class="cryostack-card">
        <div class="cryostack-card-eyebrow">Scientific Data Products</div>
        <div class="cryostack-card-tag green">
          Interactive Explorer
        </div>

        <h3>Living Ice Sheet Temperature</h3>

        <p>
          Explore Antarctic ice-sheet temperatures inferred from radar
          sounding observations and constrained by borehole measurements.
        </p>

        <div class="cryostack-mini-list green-list">
          <span>Radar</span>
          <span>Attenuation</span>
          <span>Boreholes</span>
          <span>Antarctica</span>
        </div>

        <a
          class="cryostack-card-btn green-btn"
          href="/livist/"
          data-requires-auth="false"
        >
          Open LIVIST
        </a>
      </div>

      <div class="cryostack-card">
        <div class="cryostack-card-eyebrow">Scientific Data Products</div>
        <div class="cryostack-card-tag">
          Historical Radar Archive
        </div>

        <h3>Frozen Legacies</h3>

        <p>
          Explore historical Antarctic airborne radar surveys,  flight tracks, radar-derived products, and processed SPRI-NSF-TUD campaign observations.
        </p>

        <div class="cryostack-mini-list green-list">
          <span>Historical Radar</span>
          <span>Ross Ice Shelf</span>
          <span>LYRA</span>
          <span>Ice Thickness</span>
        </div>

        <a
          class="cryostack-card-btn green-btn"
          href="/frozen-legacies/"
          data-requires-auth="false"
          > 
          Open Frozen Legacies
        </a>
      </div>

    </div>
  </section>

  <section class="cryostack-section cryostack-workflow-section">

    <div class="cryostack-section-label">
      How CryoStack Works
    </div>

    <h2>Configure, execute, monitor, visualize, download.</h2>

    <p class="cryostack-section-intro">
      CryoStack is the infrastructure that connects scientific applications to
      reproducible software environments and computational resources. Each
      application follows the same shape.
    </p>

    <div class="cryostack-workflow">

      <div class="cryostack-workflow-card">
        <div class="cryostack-workflow-number">01</div>
        <div class="cryostack-workflow-icon">CFG</div>
        <h3>Configure</h3>
        <p>
          Choose a model and example and set the scientific options through a
          guided or an advanced workflow in your own workspace.
        </p>
      </div>

      <div class="cryostack-workflow-arrow" aria-hidden="true">
        →
      </div>

      <div class="cryostack-workflow-card">
        <div class="cryostack-workflow-number">02</div>
        <div class="cryostack-workflow-icon">RUN</div>
        <h3>Execute</h3>
        <p>
          Submit the run to a remote server, an HPC cluster, or a container,
          against a reproducible software environment.
        </p>
      </div>

      <div class="cryostack-workflow-arrow" aria-hidden="true">
        →
      </div>

      <div class="cryostack-workflow-card">
        <div class="cryostack-workflow-number">03</div>
        <div class="cryostack-workflow-icon">MON</div>
        <h3>Monitor</h3>
        <p>
          Follow staging, the scheduler job, and progress in a run log and
          run history that persist across sessions.
        </p>
      </div>

      <div class="cryostack-workflow-arrow" aria-hidden="true">
        →
      </div>

      <div class="cryostack-workflow-card">
        <div class="cryostack-workflow-number">04</div>
        <div class="cryostack-workflow-icon">VIZ</div>
        <h3>Visualize</h3>
        <p>
          Discover what the run actually produced and render fields and
          diagnostics deterministically in the browser.
        </p>
      </div>

      <div class="cryostack-workflow-arrow" aria-hidden="true">
        →
      </div>

      <div class="cryostack-workflow-card">
        <div class="cryostack-workflow-number">05</div>
        <div class="cryostack-workflow-icon">DL</div>
        <h3>Download</h3>
        <p>
          Take the structured result package or the rendered figures for
          further analysis.
        </p>
      </div>

    </div>

    <div class="cryostack-exec-status">
      <span><b>Remote / HPC</b> <span class="cryostack-status supported">Supported</span></span>
      <span><b>Containers</b> <span class="cryostack-status supported">Supported</span></span>
      <span><b>Cloud</b> <span class="cryostack-status dev">In development</span></span>
    </div>

  </section>

  <section class="cryostack-section cryostack-value-section">

      <div class="cryostack-section-label">
        Platform Capabilities
      </div>

      <h2>Why CryoStack?</h2>

      <p class="cryostack-section-intro">
        CryoStack reduces the technical barriers associated with scientific
        software deployment, remote computing, and application integration,
        allowing users to focus on cryosphere research.
      </p>

      <div class="cryostack-value-grid">

        <div class="cryostack-value-card">
          <div class="cryostack-value-icon">WEB</div>

          <h3>Browser First</h3>

          <p>
            Access modeling, data assimilation, and visualization tools directly
            from a modern web browser without managing complex local installations.
          </p>
        </div>

        <div class="cryostack-value-card">
          <div class="cryostack-value-icon">HPC</div>

          <h3>HPC Ready</h3>

          <p>
            Connect applications to workstations, remote servers, Slurm clusters,
            and cloud computing resources while keeping the interface consistent.
          </p>
        </div>

        <div class="cryostack-value-card">
          <div class="cryostack-value-icon">MOD</div>

          <h3>Modular by Design</h3>

          <p>
            Integrate new cryosphere applications and scientific workflows without
            redesigning the entire platform.
          </p>
        </div>

        <div class="cryostack-value-card">
          <div class="cryostack-value-icon">OPEN</div>

          <h3>Built for Open Science</h3>

          <p>
            Support reproducible research through community models, open-source
            software, shared datasets, containers, and documented workflows.
          </p>
        </div>

      </div>

    </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Available Now
    </div>

    <h2>What CryoStack does today.</h2>

    <p class="cryostack-section-intro">
      Capabilities that are implemented and in use, primarily through the
      CryoLauncher / ISSM path.
    </p>

    <div class="cryostack-feature-row">

      <div>
        <h3>User-isolated workspaces</h3>
        <p>
          Each authenticated user has a private workspace for examples,
          edits, and datasets that persists across sessions and is never
          visible to other users.
        </p>
      </div>

      <div>
        <h3>Reproducible environments</h3>
        <p>
          Runs execute against tested container images or managed Spack
          environments rather than an ad hoc local install.
        </p>
      </div>

      <div>
        <h3>Software &amp; container provenance</h3>
        <p>
          Every run records the environment it used, resolved to a specific
          identity — a tested image is pinned by verified digest.
        </p>
      </div>

      <div>
        <h3>Structured scientific results</h3>
        <p>
          Completed ISSM runs export a transport-neutral result package that
          describes exactly which solutions and fields were produced.
        </p>
      </div>

      <div>
        <h3>Deterministic visualization</h3>
        <p>
          Fields and diagnostics are rendered in the browser from the result
          package — the same selection always produces the same plot.
        </p>
      </div>

      <div>
        <h3>Downloadable outputs</h3>
        <p>
          Take the full structured result package or just the rendered
          figures for offline analysis.
        </p>
      </div>

    </div>

  </section>

  <section class="cryostack-section cryostack-updates-section">

    <div class="cryostack-section-label">
      Platform Updates
    </div>

    <h2>Recent developments.</h2>

    <p class="cryostack-section-intro">
      Major work completed as CryoStack matures. Cloud execution is actively
      under development and is not yet available for real runs.
    </p>

    <div class="cryostack-updates-grid">

      <article class="cryostack-update-card">
        <div class="cryostack-update-status">CryoLauncher</div>

        <h3>Basic and Advanced workflows</h3>

        <p>
          A guided, validated configuration surface and a user-owned
          workspace editor, with per-user examples and datasets that stay
          isolated between users.
        </p>

        <a href="applications/icesheets/user_manual.html">
          User Manual →
        </a>
      </article>

      <article class="cryostack-update-card">
        <div class="cryostack-update-status">Execution</div>

        <h3>Tested container and Spack execution</h3>

        <p>
          Docker / OCI runs use a digest-pinned tested image; the
          ICESEE-Spack backend has a first-time environment check and
          prepare workflow before a run is allowed.
        </p>

        <a href="applications/icesheets/user_manual.html#execution-modes-and-backends">
          Execution guide →
        </a>
      </article>

      <article class="cryostack-update-card">
        <div class="cryostack-update-status">Results</div>

        <h3>Structured ISSM results and visualization</h3>

        <p>
          Completed runs export a structured result package, and CryoLauncher
          discovers and deterministically renders the solutions, fields, and
          timesteps a run actually produced.
        </p>

        <a href="applications/icesheets/user_manual.html#results">
          Results guide →
        </a>
      </article>

      <article class="cryostack-update-card">
        <div class="cryostack-update-status">In development</div>

        <h3>Cloud execution</h3>

        <p>
          AWS Batch infrastructure provisioning and the cloud run contract
          are in place. Real cloud scientific execution has not been accepted
          yet — use Remote execution.
        </p>

        <a href="documentation.html">
          Documentation →
        </a>
      </article>

    </div>
  </section>

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

        <a href="index.html">Home</a>
        <a href="documentation.html">Documentation</a>
        <a href="resources.html">Resources</a>
        <a href="about.html">About</a>
      </div>

      <div class="cryostack-footer-group">
        <h3>Applications</h3>

        <a href="/icesheets/">CryoLauncher</a>
        <a href="/icesee-gui/">ICESEE</a>
        <a href="/livist/">LIVIST</a>
      </div>

      <div class="cryostack-footer-group">
        <h3>Community</h3>

        <a
          href="https://github.com/ICESEE-project/CryoLauncher"
          target="_blank"
          rel="noopener noreferrer">
          GitHub
        </a>

        <a
          href="https://github.com/ICESEE-project"
          target="_blank"
          rel="noopener noreferrer">
          ICESEE Project
        </a>

        <a
          href="https://github.com/ICESEE-project/CryoLauncher/issues"
          target="_blank"
          rel="noopener noreferrer">
          Report an Issue
        </a>
      </div>

    </div>

    <div class="cryostack-footer-bottom">

      <div>
        Developed by ICCL and PGSL at the Georgia Institute of Technology.
      </div>

      <div class="cryostack-footer-meta">
        <span>© 2026 CryoStack</span>
        <span>BSD 2-Clause License</span>
      </div>

    </div>

  </footer>

</div>
:::