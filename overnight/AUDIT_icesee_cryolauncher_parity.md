# ICESEE ↔ CryoLauncher experience-parity audit (read-only)

Coordinating session, 2026-09-07. Branch `gatech_vm_backend`.
Covers the `/overnight` directive Phases 6 (ICESEE parity), 7 (shared
components), and 8 (ecosystem theme). Phases 1–5 landed as commits
`18790cb`, `9004034`, `2009fe2`, `b6abe17` (see `MORNING_REPORT_overnight.md`).

This is a **read-only** audit. No ICESEE gateway code was changed in this pass:
`icesee_jupyter_book/ui/icesee_gateway.py` is 2797 lines of live
data-assimilation workflow with a *different persistence backend* than
CryoLauncher, and a responsible port is a dedicated, multi-commit effort — not
an autonomous overnight rewrite. The directive's own rule applies: "choose the
least invasive robust approach; document the reasoning; test it; continue."

---

## A / B / C concept map

### A. Reusable ecosystem concepts (already shared, or safe to share)

| Concept | State today |
|---|---|
| Shared application shell (`build_application_header`) | **Shared.** Both gateways import it. |
| Remote Connection panel (`shared_remote_connection_panel`) | **Shared.** |
| Slurm Resources panel (`shared_slurm_resources_panel`) | **Shared.** |
| SSH key manager (`shared_ssh_widgets.build_ssh_key_manager`) | **Shared.** |
| Slurm validation (`shared_validation.validate_slurm_resources`) | **Shared.** |
| Observer-guard / `UIRefreshCoordinator` | **Shared.** |
| Responsive stylesheet (`shared_app_styles.shared_application_styles`) | **Shared** (single stylesheet, no per-gateway visual system). |
| Application menus (`application_menus`) | **Shared.** |
| Accordion section structure (Remote / Backend / Slurm / SSH) | **Structurally identical**, hand-built in each gateway. |
| Connector relay client, B3 Run gate, access-state machine | **Shared.** |
| Per-user settings persistence (`make_state_io`, trusted `HTTP_X_CRYOSTACK_USER_ID`) | **Shared.** |
| Compute profiles / `initial_remote_fields` | **Shared.** |

### B. CryoLauncher-specific concepts ICESEE does **not** have yet

| Concept | CryoLauncher | ICESEE today | Gap class |
|---|---|---|---|
| Local per-user **run directory** isolation | `WorkspaceManager` owner root, per `run_id` | process-global `BOOK/icesee_runs/<sec-ts>/` — no user component (documented in `AUDIT_icesee_platform.md`; still open) | **SAFE / high-value** |
| Local **run history** (RunInfo + manifest cards) | `build_workspace_history_panel` + `.cryostack-run.json` manifests + `run_history.py` selected-run card | **Absent.** `experiment_bridge.create()` POSTs to `/api/v1/experiments` through the browser session; there is no local record, no re-selection, no per-run card | **SAFE (additive)** |
| **Manifest v2** provenance (container + software + metadata, round-trip) | `cryostack_src/workspace/manifest.py` | **Absent** for ICESEE runs | **SAFE (additive)** — schema already tolerates `software: {}` |
| Transport-neutral **ResultPackage** (`outputs/{metadata,mesh,fields,model,figures}`) | `discover_results()` / `ResultPackage` per model | **Absent.** Ad-hoc `rglob("*.png" / "*.h5")` preview | **DA-CARE** — needs a DA/ensemble output schema, not the glaciological tier-1 allow-list |
| **Visualization panel** (`render_field` / `render_timeseries`) | `cryostack_src/visualization/` + Results panel | **Absent** | **DA-CARE** — depends on the DA schema |
| **Execution-mode / compute-backend** vocabulary as first-class rows | formalised this pass (Phase 3) | tab-index dispatch (`mode_tabs`), 6 bespoke `submit_remote_example*` helpers | **DA-CARE** — see execution note below |
| Cloud backend = provisioned `CloudBridge`/`CloudManager`/`AWSDriver` + digest-pinned CryoStack image | C4/C5/C7 | legacy `core/cloud_runner.py`: user-typed queue/job-def, user-supplied Batch image via `ICESEE_S3_RUN` / `ICESEE_RUN_SCRIPT` | **ICESEE-SPECIFIC for now** — needs a provisioned `cryostack-icesee` image + job def before any port |
| **Download** control on every run | per-run `_auto_download` blob | remote-only zip; local mode has no download button | **SAFE (helper) / DA-CARE (wiring)** |
| Basic / Advanced / Agent·Beta interaction modes | `ui_mode_dd` | **None** — ICESEE has one mode | intentionally ICESEE-specific; a future "Basic" could curate the `params.yaml` grid |
| `model_dd` (Icepack / ISSM) | present | **None** — ICESEE forecast model is chosen inside `params.yaml` / preset | ICESEE-SPECIFIC |
| AWS diagnostics menu from persisted `metadata["aws_resources"]` | `cloud/diagnostics.py` (pure) | **Absent** | **DA-CARE** — arrives with the cloud-backend port |

### C. ICESEE-specific data-assimilation concepts (keep first-class, never generify)

Forecast model; ensemble (`ens_sl` / `Nens`); observations (`freq_obs`,
`obs_*_time`, `sig_obs`); DA method / filter (`filter_alg_dd`:
`EnKF | DEnKF | EnTKF | EnRSKF`); state variables vs estimated parameters
(`num_state_vars` / `num_param_vars`, `vec_inputs` / `observed_vars`,
`joint_/state_/parameter_estimation`); DA cycles; initialization → forecast →
analysis/update; `parallel_flag` (`serial | MPI | MPI_model`); `execution_mode`
(0/1/2); per-example `params.yaml` with a dynamically-built per-key widget grid;
`preset_dd`; `mode_tabs` (`W.Tab`: Local (GHUB) / Remote / Cloud);
`seed`, `inflation_factor`, `localization_flag`; ensemble output diagnostics.

**The `params.yaml` DA contract is unchanged and out of scope.** Sections
`physical-parameters`, `modeling-parameters`, `enkf-parameters`. Do not touch.

---

## Phase 7 — shared-component audit

Genuinely identical presentation that could become a **small** shared component
(prefer "small shared component + application-specific composition" over a large
generic abstraction with dozens of conditionals):

| Candidate | Where it lives now | Recommendation |
|---|---|---|
| Status badge (`cryostack-run-badge-<status>`) | inline in `workspace/run_history.py`; ICESEE has no equivalent | Extract `shared_run_badge(status)` **when** ICESEE gains run history — not before (one caller today). |
| Execution-mode / compute-backend label maps (`{"aws": "AWS Batch (Fargate)"}`, `{"cloud": "Cloud", ...}`) | one live map site (`run_history.py::show_selection`); `cloud_environment.py` and `cloud_run_controller.py` use the string in prose, not as a label map | **Do not extract yet** — a shared `labels.py` for a single map caller is premature. Extract `execution_mode_label` / `compute_backend_label` when ICESEE run history becomes the second caller (audit step 3). |
| Selected-run identity card (Model / Example / Source / Run target / Execution mode / Compute backend / Job ID / Status) | `run_history.py::show_selection` | Keep composed in the gateway; the row list is CryoLauncher-shaped. |
| Software-stack card (`software_stack_html`) | `run_history.py` | Fine as-is; ICESEE-Spack carries no resolved stack, so ICESEE would render an empty card — not worth sharing yet. |
| AWS diagnostics presentation (`aws_diagnostics_html` / `cloud/diagnostics.py`) | already a clean pure module | Already shareable; ICESEE adopts it with the cloud-backend port. |
| Artifact gallery / figure cards | `cryostack_src/models/icepack` + Results panel | Glaciological-figure-shaped; ICESEE ensemble output is different — do not share the composition, only (later) the card CSS. |
| Empty-state component (`icesee-subtle` + message) | CSS class shared; markup duplicated | Low value; leave. |

**Conclusion:** no extraction is worth doing independently of the ICESEE port.
Every shareable component today has exactly one caller; sharing now would add an
abstraction with no second consumer. Each candidate should follow the consumer,
not precede it. No new framework. (The genuinely reusable pure modules —
`cloud/diagnostics.py`, `shared_app_styles`, the `shared_*` panels — are
*already* shared.)

## Phase 8 — ecosystem theme

Both apps already load the **same** `shared_application_styles()` stylesheet and
the same `build_application_header` (fixed **CryoStack** wordmark above a
distinct application name). Typography, spacing, card geometry, badge and button
hierarchy, and nav conventions are therefore already aligned by construction.
The doc books (`icesee_jupyter_book/docs/`) share the Jupyter-Book theme and
vocabulary (CryoStack, CryoLauncher, ICESEE, Getting Started, User Manual,
Developer Guide). **No theme work is needed or advisable** — the risk is
divergence, and the single-stylesheet rule already prevents it. Priority order
per the directive (clarity → scientific usability → consistency →
maintainability → aesthetics) is satisfied.

---

## Recommended incremental sequence for the dedicated ICESEE session

1. **Run isolation** (SAFE): give `local_runner.run_dir` a per-user component
   from `resolve_workspace_user` / `user_run_root` (both already imported in
   `icesee_gateway.py`). Pure, testable, closes a real multi-user data-exposure
   gap flagged since `AUDIT_icesee_platform.md`.
2. **Local run history** (SAFE, additive): a `WorkspaceManager`-backed run
   record + manifest v2 write on ICESEE run start, and a
   `build_workspace_history_panel` instance in the ICESEE Workspace tab. The
   panel is already model-neutral. No change to `experiment_bridge` (keep the
   web-API experiment record in parallel during migration). This is also where
   `execution_mode_label` / `compute_backend_label` become worth extracting —
   the panel is the second caller.
3. **DA ResultPackage schema** (DA-CARE): design
   `cryostack_src/models/icesee/results.py` around ensemble/analysis outputs
   (state trajectories, spread, RMSE vs truth, per-cycle diagnostics) — a
   distinct schema, not the glaciological tier-1 allow-list. Then an ICESEE
   visualization panel on that schema.
4. **Cloud-backend port** (ICESEE-SPECIFIC → shared): provision a
   `cryostack-icesee` image + job definition, then move ICESEE cloud from
   `core/cloud_runner.py` to `CloudBridge`, inheriting provenance, diagnostics,
   and the C7 BYO-AWS credential boundary for free.

Steps 1–2 are low-risk and independently valuable; 3–4 are genuine
science-and-infra projects that must not be rushed.
