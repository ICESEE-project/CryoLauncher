# Resources

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>
:::

:::{raw} html
<div class="cryostack-resources-page">

  <section class="cryostack-resources-hero">

    <div class="cryostack-section-label">
      CryoStack Resources
    </div>

    <h1>Applications, software, data, and support across the ecosystem.</h1>

    <p>
      An ecosystem-wide index. For CryoLauncher-specific depth (examples,
      datasets, result formats), see the
      <a href="applications/icesheets/resources.html">CryoLauncher Resources</a>.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="documentation.html">
        Platform Documentation
      </a>

      <a class="cryostack-btn secondary"
         href="https://github.com/ICESEE-project"
         target="_blank" rel="noopener noreferrer">
        GitHub Organization
      </a>
    </div>

  </section>

  <section id="applications" class="cryostack-section">

    <div class="cryostack-section-label">Scientific Applications</div>
    <h2>CryoStack applications.</h2>

    <div class="cryostack-resource-grid">

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Numerical Modeling</div>
        <h3>CryoLauncher <span class="cryostack-status supported">Supported</span></h3>
        <p>Configure and run supported ice-sheet models in the browser.</p>
        <div class="cryostack-resource-inline-links">
          <a href="/icesheets/">Open</a>
          <a href="applications/icesheets/getting_started.html">Getting Started</a>
          <a href="applications/icesheets/user_manual.html">User Manual</a>
        </div>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Data Assimilation</div>
        <h3>ICESEE</h3>
        <p>Ensemble state estimation and parameter inference with supported models.</p>
        <div class="cryostack-resource-inline-links">
          <a href="/icesee-gui/">Open</a>
          <a href="applications/icesee/getting_started.html">Getting Started</a>
          <a href="applications/icesee/user_manual.html">User Manual</a>
        </div>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Scientific Data</div>
        <h3>LIVIST</h3>
        <p>Antarctic ice-sheet temperature products from radar and boreholes.</p>
        <div class="cryostack-resource-inline-links">
          <a href="/livist/">Open</a>
          <a href="/livist/docs/livist_user_manual/">User Manual</a>
          <a href="/livist/docs/api/">Python Docs</a>
        </div>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Radar Archive</div>
        <h3>Frozen Legacies</h3>
        <p>Historical Antarctic airborne radar surveys and processed products.</p>
        <div class="cryostack-resource-inline-links">
          <a href="/frozen-legacies/">Open</a>
          <a href="applications/frozen_legacies/getting_started.html">Getting Started</a>
          <a href="applications/frozen_legacies/user_manual.html">User Manual</a>
        </div>
      </article>

    </div>
  </section>

  <section id="models" class="cryostack-section">

    <div class="cryostack-section-label">Models</div>
    <h2>Scientific models.</h2>

    <div class="cryostack-resource-grid">

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Ice-Sheet Model</div>
        <h3>ISSM <span class="cryostack-status supported">Supported</span></h3>
        <p>The Ice-sheet and Sea-level System Model — the mature CryoLauncher path.</p>
        <div class="cryostack-resource-inline-links">
          <a href="https://issm.jpl.nasa.gov/" target="_blank" rel="noopener noreferrer">Website</a>
          <a href="https://issmteam.github.io/ISSM-Documentation/" target="_blank" rel="noopener noreferrer">Docs</a>
          <a href="https://github.com/ISSMteam/ISSM" target="_blank" rel="noopener noreferrer">GitHub</a>
        </div>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Ice-Sheet Model</div>
        <h3>Icepack <span class="cryostack-status dev">Experimental</span></h3>
        <p>A Python library on Firedrake. Selectable in CryoLauncher, not yet at ISSM parity.</p>
        <div class="cryostack-resource-inline-links">
          <a href="https://icepack.github.io/" target="_blank" rel="noopener noreferrer">Docs</a>
          <a href="https://github.com/icepack/icepack" target="_blank" rel="noopener noreferrer">GitHub</a>
        </div>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Finite Elements</div>
        <h3>Firedrake / PETSc</h3>
        <p>The finite-element and linear-algebra libraries under Icepack.</p>
        <div class="cryostack-resource-inline-links">
          <a href="https://www.firedrakeproject.org/" target="_blank" rel="noopener noreferrer">Firedrake</a>
          <a href="https://petsc.org/" target="_blank" rel="noopener noreferrer">PETSc</a>
        </div>
      </article>

    </div>
  </section>

  <section id="environments" class="cryostack-section">

    <div class="cryostack-section-label">Software Environments</div>
    <h2>Containers and Spack.</h2>

    <div class="cryostack-resource-grid">

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Containers</div>
        <h3>Tested container images <span class="cryostack-status supported">Supported</span></h3>
        <p>
          CryoLauncher's Docker / OCI path uses a curated image whose stack is
          validated and pinned by verified digest.
        </p>
        <a href="https://github.com/ICESEE-project/ICESEE-Containers" target="_blank" rel="noopener noreferrer">ICESEE-Containers &rarr;</a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Package Management</div>
        <h3>ICESEE-Spack</h3>
        <p>
          Spack-managed environments with a first-time check-and-prepare
          workflow before a run is allowed.
        </p>
        <a href="https://github.com/ICESEE-project/ICESEE-Spack" target="_blank" rel="noopener noreferrer">ICESEE-Spack &rarr;</a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Containers</div>
        <h3>Apptainer &amp; Docker</h3>
        <p>The container runtimes used on HPC systems and for portable builds.</p>
        <div class="cryostack-resource-inline-links">
          <a href="https://apptainer.org/" target="_blank" rel="noopener noreferrer">Apptainer</a>
          <a href="https://www.docker.com/" target="_blank" rel="noopener noreferrer">Docker</a>
        </div>
      </article>

    </div>
  </section>

  <section id="compute" class="cryostack-section">

    <div class="cryostack-section-label">HPC and Compute Resources</div>
    <h2>Where runs execute.</h2>

    <div class="cryostack-resource-grid">

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Execution</div>
        <h3>Remote / HPC <span class="cryostack-status supported">Supported</span></h3>
        <p>SSH and CryoStack Connector access to Linux servers and Slurm clusters.</p>
        <a href="applications/icesheets/user_manual.html#execution-modes-and-backends">Execution guide &rarr;</a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Execution</div>
        <h3>Cloud <span class="cryostack-status dev">In validation</span></h3>
        <p>Bring-your-own AWS account via CloudFormation; infrastructure provisioning is wired, the full lifecycle is still being validated.</p>
        <a href="docs/hpc_cloud.html">Cloud Run Guide &rarr;</a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Scheduler</div>
        <h3>Slurm</h3>
        <p>Reference for the scheduler settings CryoLauncher exposes.</p>
        <a href="https://slurm.schedmd.com/documentation.html" target="_blank" rel="noopener noreferrer">Slurm docs &rarr;</a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Georgia Tech HPC</div>
        <h3>PACE</h3>
        <p>Georgia Tech research computing and HPC services.</p>
        <a href="https://pace.gatech.edu/" target="_blank" rel="noopener noreferrer">Visit PACE &rarr;</a>
      </article>

    </div>
  </section>

  <section id="data-results" class="cryostack-section">

    <div class="cryostack-section-label">Example Workflows, Data, and Results</div>
    <h2>Working with examples, datasets, and outputs.</h2>

    <div class="cryostack-resource-grid">

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Examples</div>
        <h3>Example workflows</h3>
        <p>
          Application examples (read-only) plus your own workspace examples,
          with <code>SquareIceShelf</code> as the recommended first ISSM run.
        </p>
        <a href="applications/icesheets/user_manual.html#application-examples-vs-my-workspace">Examples &rarr;</a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">My Workspace</div>
        <h3>Datasets</h3>
        <p>Upload reusable inputs, reference them from examples, and stage them with a run.</p>
        <a href="applications/icesheets/user_manual.html#dataset-management">Dataset guide &rarr;</a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Results</div>
        <h3>Result formats &amp; visualization</h3>
        <p>
          The structured result package, and deterministic Solution / Field /
          Timestep rendering.
        </p>
        <div class="cryostack-resource-inline-links">
          <a href="applications/icesheets/user_manual.html#result-format-reference">Result format</a>
          <a href="applications/icesheets/user_manual.html#visualization">Visualization</a>
        </div>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Data Products</div>
        <h3>Published datasets</h3>
        <p>Externally hosted scientific data products used by CryoStack's data applications.</p>
        <a href="https://source.coop/englacial/ice-sheet-temperature" target="_blank" rel="noopener noreferrer">
          Ice-sheet temperature data &rarr;
        </a>
      </article>

    </div>
  </section>

  <section id="tutorials" class="cryostack-section">

    <div class="cryostack-section-label">Tutorials</div>
    <h2>Guided walkthroughs.</h2>
    <p class="cryostack-section-intro">
      <span class="cryostack-status planned">Planned</span>
      &nbsp;Dedicated step-by-step tutorials are planned. The
      <a href="applications/icesheets/getting_started.html">CryoLauncher Getting Started</a>
      guide and the
      <a href="applications/icesheets/user_manual.html">User Manual</a>
      currently cover the full workflow.
    </p>

  </section>

  <section id="repositories" class="cryostack-section">

    <div class="cryostack-section-label">Repositories and Citation</div>
    <h2>Source code and how to cite.</h2>

    <div class="cryostack-resource-grid">

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Source Code</div>
        <h3>CryoLauncher</h3>
        <p>The gateway, application layer, connector, and deployment.</p>
        <a href="https://github.com/ICESEE-project/CryoLauncher" target="_blank" rel="noopener noreferrer">View repository &rarr;</a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Organization</div>
        <h3>ICESEE project</h3>
        <p>ICESEE, CryoLauncher, containers, and Spack environments.</p>
        <a href="https://github.com/ICESEE-project" target="_blank" rel="noopener noreferrer">View organization &rarr;</a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Citation</div>
        <h3>Citing CryoStack</h3>
        <p>Cite CryoStack together with the models, datasets, and publications you used.</p>
        <a href="about.html#citation">Citation guidance &rarr;</a>
      </article>

    </div>
  </section>

  <section id="support" class="cryostack-section cryostack-docs-next">

    <div class="cryostack-section-label">Support</div>
    <h2>Get help.</h2>

    <p>
      Use the
      <a href="https://github.com/ICESEE-project/CryoLauncher/issues" target="_blank" rel="noopener noreferrer">CryoLauncher issue tracker</a>
      for platform bugs, connector and remote-execution problems, documentation
      issues, and feature requests. Questions about ISSM, Icepack, Firedrake, or
      PETSc themselves belong on those projects' own support channels.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary"
         href="https://github.com/ICESEE-project/CryoLauncher/issues"
         target="_blank" rel="noopener noreferrer">
        Open Issue Tracker
      </a>
      <a class="cryostack-btn secondary" href="documentation.html">Documentation</a>
    </div>

  </section>

</div>
:::
