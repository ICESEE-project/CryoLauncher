"""Shared visual styles for CryoStack Voilà applications."""

from __future__ import annotations

import ipywidgets as W


_SHARED_APPLICATION_CSS = """
<style>

/* =========================================================
   CryoStack application page
   ========================================================= */

.cryostack-application-page,
.icesee-page {
    width: 100%;

    font-family:
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Roboto,
        Arial,
        sans-serif;
}


/* =========================================================
   Page title and introduction
   ========================================================= */

.cryostack-application-title,
.icesee-title {
    margin: 4px 0 6px;

    color: #1f2937;

    font-size: 20px;
    font-weight: 700;
    line-height: 1.25;
}

.cryostack-application-subtitle,
.icesee-subtitle {
    max-width: 900px;
    margin-bottom: 10px;

    color: rgba(15, 23, 42, 0.68);

    font-size: 14px;
    line-height: 1.5;
}


/* =========================================================
   Section headings
   ========================================================= */

.cryostack-section-heading,
.icesee-h {
    margin: 2px 0 14px;

    color: #1f2937;

    font-size: 18px;
    font-weight: 750;
    line-height: 1.3;
}


/* =========================================================
   Cards
   ========================================================= */

.cryostack-application-card,
.icesee-card {
    padding: 18px;

    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 16px;

    background: #ffffff;

    box-shadow:
        0 8px 24px rgba(15, 23, 42, 0.04);
}


/* =========================================================
   Form labels and supporting text
   ========================================================= */

.cryostack-form-label,
.icesee-lbl {
    padding-top: 8px;

    color: rgba(15, 23, 42, 0.78);

    font-weight: 600;
}

.cryostack-subtle,
.icesee-subtle {
    margin-bottom: 6px;

    color: rgba(15, 23, 42, 0.56);

    font-size: 12px;
    line-height: 1.45;
}


/* =========================================================
   Status chips
   ========================================================= */

.cryostack-status,
.icesee-status {
    display: inline-block;

    padding: 8px 14px;

    border: 1px solid rgba(15, 23, 42, 0.10);
    border-radius: 999px;

    font-weight: 700;
    line-height: 1;
}

.cryostack-status-idle,
.icesee-idle {
    background: rgba(15, 23, 42, 0.04);
    color: #475569;
}

.cryostack-status-running,
.icesee-running {
    background: rgba(37, 99, 235, 0.12);
    color: #1d4ed8;

    /* a subtle pulse so an in-flight operation reads as "working",
       without a fake progress bar or percentage. */
    animation: cryostack-status-pulse 1.4s ease-in-out infinite;
}

@keyframes cryostack-status-pulse {
    0%, 100% { opacity: 1; }
    50%      { opacity: 0.55; }
}

@media (prefers-reduced-motion: reduce) {
    .cryostack-status-running,
    .icesee-running { animation: none; }
}

.cryostack-status-done,
.icesee-done {
    background: rgba(22, 163, 74, 0.14);
    color: #15803d;
}

.cryostack-status-failed,
.icesee-fail {
    background: rgba(220, 38, 38, 0.14);
    color: #b91c1c;
}


/* =========================================================
   Configuration summaries
   ========================================================= */

.cryostack-summary,
.icesee-summary {
    padding: 14px 16px;

    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 14px;

    background:
        linear-gradient(
            to bottom,
            rgba(15, 23, 42, 0.015),
            rgba(15, 23, 42, 0.03)
        );

    color: rgba(15, 23, 42, 0.78);

    line-height: 1.75;
}

/* Each row is "<div><span class="...-key">Label:</span> Value</div>" --
   shared by CryoLauncher's own Run Plan summary and ICESEE's (Run Plan
   and the Workspace Selected-Run card). A flex row with a fixed-width
   label column keeps every label/value pair aligned and gives the value
   clear breathing room instead of the label and value running together. */
.cryostack-summary > div,
.icesee-summary > div {
    display: flex;
    align-items: baseline;
    gap: 8px;
    overflow-wrap: anywhere;
}

.cryostack-summary-key,
.icesee-summary-k {
    color: rgba(15, 23, 42, 0.90);

    font-weight: 700;

    flex: 0 0 auto;
    min-width: 150px;
}


/* =========================================================
   Main two-column application layout
   ========================================================= */

.cryostack-application-grid,
.icesee-grid {
    display: flex;
    width: 100%;
    /* columns align at the top; each keeps its own natural height so the
       short left card never caps the Workspace column (see theme.py). */
    align-items: flex-start;
    gap: 24px;
}

.cryostack-application-left,
.icesee-left {
    flex: 0 0 46%;
    min-width: 0;
}

.cryostack-application-right,
.icesee-right {
    flex: 0 0 54%;
    min-width: 0;
}


/* =========================================================
   Action rows
   ========================================================= */

.cryostack-actions,
.icesee-actions {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}


/* =========================================================
   Code and command previews
   ========================================================= */

.cryostack-application-page pre,
.icesee-page pre,
pre.cryostack-code-block {
    overflow-x: auto;

    padding: 12px;

    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 10px;

    background: #f6f8fa;

    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
}


/* =========================================================
   Shared account placement inside application menus
   ========================================================= */

.cryostack-application-nav-actions {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: flex-end;

    margin-left: auto;
}

.cryostack-application-nav-actions
.cryostack-global-account {
    width: auto !important;
    margin: 0 !important;
}

.cryostack-application-nav-actions
.cryostack-global-account-menu {
    z-index: 5000 !important;
}


/* =========================================================
   Standard widget spacing
   ========================================================= */

.cryostack-application-card
.widget-box,
.icesee-card
.widget-box {
    max-width: 100%;
}


/* =========================================================
   Responsive layout
   ========================================================= */

@media (max-width: 1050px) {
    .cryostack-application-grid,
    .icesee-grid {
        flex-direction: column;
    }

    .cryostack-application-left,
    .cryostack-application-right,
    .icesee-left,
    .icesee-right {
        flex: 1 1 auto;
        width: 100%;
    }
}

@media (max-width: 700px) {
    .cryostack-application-card,
    .icesee-card {
        padding: 14px;
        border-radius: 13px;
    }

    .cryostack-application-title,
    .icesee-title {
        font-size: 18px;
    }

    .cryostack-section-heading,
    .icesee-h {
        font-size: 16px;
    }
}


/* =========================================================
   Dark theme
   ========================================================= */

html[data-theme="dark"]
.cryostack-application-page,
html[data-theme="dark"]
.icesee-page {
    color: #e2e8f0;
}

html[data-theme="dark"]
.cryostack-application-title,
html[data-theme="dark"]
.icesee-title,
html[data-theme="dark"]
.cryostack-section-heading,
html[data-theme="dark"]
.icesee-h {
    color: #f8fafc;
}

html[data-theme="dark"]
.cryostack-application-subtitle,
html[data-theme="dark"]
.icesee-subtitle,
html[data-theme="dark"]
.cryostack-subtle,
html[data-theme="dark"]
.icesee-subtle {
    color: #94a3b8;
}

html[data-theme="dark"]
.cryostack-application-card,
html[data-theme="dark"]
.icesee-card {
    border-color: rgba(226, 232, 240, 0.12);
    background: #111827;

    box-shadow:
        0 8px 24px rgba(0, 0, 0, 0.22);
}

html[data-theme="dark"]
.cryostack-summary,
html[data-theme="dark"]
.icesee-summary {
    border-color: rgba(226, 232, 240, 0.12);
    background: rgba(30, 41, 59, 0.72);
    color: #cbd5e1;
}

html[data-theme="dark"]
.cryostack-summary-key,
html[data-theme="dark"]
.icesee-summary-k {
    color: #f1f5f9;
}

html[data-theme="dark"]
.cryostack-application-page pre,
html[data-theme="dark"]
.icesee-page pre,
html[data-theme="dark"]
pre.cryostack-code-block {
    border-color: rgba(226, 232, 240, 0.12);
    background: #0f172a;
    color: #e2e8f0;
}


/* =========================================================
   CryoStack application — small-screen foundation
   ---------------------------------------------------------
   Shared responsive rules for the Voila application shell
   (Run settings, accordions, Workspace tabs, Results panel,
   file editor, logs). Keyed on the layout classes and the
   ipywidgets DOM so every panel inherits the behaviour.
   ========================================================= */

/* Never let a widget or a long path widen the page. */
.cryostack-application-page,
.icesee-page,
.icesee-grid,
.cryostack-application-grid {
    max-width: 100%;
    overflow-x: hidden;
}

.cryostack-application-page .jupyter-widgets,
.icesee-page .jupyter-widgets {
    min-width: 0;
    max-width: 100%;
}

/* Two-column layout: stack on tablet / mobile. The Workspace column keeps
   its natural height and page scrolling at every width; sticky positioning
   (desktop only, see theme.py) is disabled here. */
@media (max-width: 1050px) {
    .cryostack-right-workspace,
    .icesee-right {
        height: auto !important;
        max-height: none !important;
        min-height: 0 !important;
        overflow: visible !important;
        position: static !important;
    }
}

@media (max-width: 900px) {
    .cryostack-application-grid,
    .icesee-grid {
        gap: 16px;
    }
}

/* Label / control rows: stack the label above the control on narrow screens.
   Covers form_pair() rows and the Results Solution/Field/Timestep rows. */
@media (max-width: 600px) {
    .cryostack-field-row.widget-hbox,
    .cryostack-field-row {
        flex-direction: column !important;
        align-items: stretch !important;
        gap: 4px !important;
    }

    .cryostack-field-row > .widget-html,
    .cryostack-field-row > .jupyter-widgets:first-child {
        width: auto !important;
        min-width: 0 !important;
    }

    /* ipywidgets inline hbox pairs (label + input) */
    .cryostack-application-page .widget-inline-hbox,
    .icesee-page .widget-inline-hbox {
        flex-wrap: wrap;
    }

    .cryostack-application-page .widget-inline-hbox .widget-label,
    .icesee-page .widget-inline-hbox .widget-label {
        min-width: 0 !important;
        width: 100% !important;
        text-align: left !important;
        white-space: normal;
    }
}

/* Inputs use the full available width on small screens. */
@media (max-width: 700px) {
    .cryostack-application-page .widget-text,
    .cryostack-application-page .widget-textarea,
    .cryostack-application-page .widget-dropdown,
    .cryostack-application-page .widget-inttext,
    .cryostack-application-page .widget-floattext,
    .icesee-page .widget-text,
    .icesee-page .widget-textarea,
    .icesee-page .widget-dropdown,
    .icesee-page .widget-inttext,
    .icesee-page .widget-floattext {
        width: 100% !important;
    }

    /* Button groups wrap instead of overflowing. */
    .cryostack-application-page .widget-hbox,
    .icesee-page .widget-hbox {
        flex-wrap: wrap;
    }
}

/* Tabs (Workspace / Results / Run log): keep the tab bar usable without
   widening the page -- scroll the bar, never the page. */
.cryostack-application-page .lm-TabBar-content,
.cryostack-application-page .p-TabBar-content,
.icesee-page .lm-TabBar-content,
.icesee-page .p-TabBar-content {
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    flex-wrap: nowrap;
}

.cryostack-application-page .lm-TabBar-tab,
.cryostack-application-page .p-TabBar-tab,
.icesee-page .lm-TabBar-tab,
.icesee-page .p-TabBar-tab {
    flex: 0 0 auto;
}

/* Logs and text output: scroll inside the panel, wrap long lines. */
.cryostack-live-log,
.cryostack-output-tab .jp-OutputArea,
.cryostack-output-tab .widget-output {
    max-width: 100%;
    overflow: auto;
}

.cryostack-application-page .jp-OutputArea-output pre,
.cryostack-application-page .widget-output pre,
.icesee-page .jp-OutputArea-output pre,
.icesee-log pre,
.icesee-out pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
}

@media (max-width: 700px) {
    .cryostack-live-log,
    .cryostack-output-workspace {
        max-height: 60vh;
    }

    /* File / code editor: full viewport width. */
    .cryostack-application-page .widget-textarea textarea,
    .icesee-page .widget-textarea textarea {
        width: 100% !important;
        min-width: 0 !important;
    }
}

/* Accordions: full width, no inner horizontal scroll. */
.cryostack-application-page .widget-accordion,
.icesee-page .widget-accordion,
.cryostack-application-page .widget-accordion .widget-accordion-child,
.icesee-page .widget-accordion .widget-accordion-child {
    max-width: 100%;
    min-width: 0;
}

@media (max-width: 430px) {
    .cryostack-application-card,
    .icesee-card {
        padding: 12px;
        border-radius: 12px;
    }

    .cryostack-application-title,
    .icesee-title {
        font-size: 16px;
    }

    .cryostack-section-heading,
    .icesee-h {
        font-size: 15px;
    }

    .cryostack-application-page pre,
    .icesee-page pre,
    pre.cryostack-code-block {
        font-size: 12px;
        padding: 10px;
    }
}


/* =========================================================
   B4 -- grouped form panels (Remote Connection, Slurm resources)
   ========================================================= */

.cryostack-group-title {
    margin: 2px 0 6px;

    color: rgba(15, 23, 42, 0.82);

    font-size: 13px;
    font-weight: 750;
    letter-spacing: 0.02em;
    text-transform: uppercase;
}

.cryostack-field-label {
    margin-bottom: 2px;
    color: rgba(15, 23, 42, 0.80);
    font-size: 13px;
    font-weight: 650;
}

.cryostack-help {
    margin-top: 2px;
    color: rgba(15, 23, 42, 0.52);
    font-size: 12px;
    line-height: 1.4;
}

.cryostack-field {
    flex: 1 1 0;
    min-width: 0;
}

.cryostack-field-row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    gap: 14px;
    width: 100%;
}

/* Slurm 3-up numeric grid: 3 -> 2 -> 1 as width drops. */
.cryostack-slurm-numeric-grid {
    display: grid !important;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 14px;
    width: 100%;
}

@media (max-width: 768px) {
    .cryostack-slurm-numeric-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 430px) {
    .cryostack-slurm-numeric-grid {
        grid-template-columns: minmax(0, 1fr);
    }
}


/* =========================================================
   B4 -- Remote Connection status chip
   ========================================================= */

.cryostack-conn-status {
    display: inline-flex;
    align-items: center;
    gap: 8px;

    padding: 6px 12px;

    border: 1px solid rgba(15, 23, 42, 0.12);
    border-radius: 999px;

    font-size: 13px;
    font-weight: 700;
}

.cryostack-conn-status__dot { font-size: 11px; line-height: 1; }

.cryostack-conn-status.is-unchecked { background: rgba(15, 23, 42, 0.04); color: #475569; }
.cryostack-conn-status.is-unchecked .cryostack-conn-status__dot { color: #94a3b8; }

.cryostack-conn-status.is-checking { background: rgba(37, 99, 235, 0.10); color: #1d4ed8; }
.cryostack-conn-status.is-checking .cryostack-conn-status__dot { color: #2563eb; }

.cryostack-conn-status.is-verified { background: rgba(22, 163, 74, 0.14); color: #15803d; }
.cryostack-conn-status.is-verified .cryostack-conn-status__dot { color: #16a34a; }

.cryostack-conn-status.is-mismatch { background: rgba(217, 119, 6, 0.16); color: #b45309; }
.cryostack-conn-status.is-mismatch .cryostack-conn-status__dot { color: #d97706; }

.cryostack-conn-status.is-failed { background: rgba(220, 38, 38, 0.14); color: #b91c1c; }
.cryostack-conn-status.is-failed .cryostack-conn-status__dot { color: #dc2626; }

.cryostack-conn-status.is-key-unregistered { background: rgba(217, 119, 6, 0.16); color: #b45309; }
.cryostack-conn-status.is-key-unregistered .cryostack-conn-status__dot { color: #d97706; }


/* The Authentication-method toggle must never clip "Password bootstrap
   (one-time)": let the control size to its content instead of a fixed width. */
.cryostack-remote-connection-panel .widget-togglebuttons {
    width: auto !important;
    max-width: 100%;
}

.cryostack-remote-connection-panel .widget-togglebuttons .widget-toggle-buttons,
.cryostack-remote-connection-panel .widget-togglebuttons .jupyter-widgets {
    flex-wrap: wrap;
}

.cryostack-remote-connection-panel .widget-togglebuttons button {
    white-space: nowrap;
    width: auto;
    min-width: max-content;
}


/* =========================================================
   B4 -- connector card, diagnostics, manual key registration
   ========================================================= */

.cryostack-connector-card {
    padding: 12px 14px;
    border: 1px solid rgba(37, 99, 235, 0.16);
    border-radius: 12px;
    background: rgba(37, 99, 235, 0.04);
}

.cryostack-diag {
    font-size: 12px;
    line-height: 1.7;
    color: rgba(15, 23, 42, 0.62);
    word-break: break-all;
}

.cryostack-diag__k { font-weight: 700; color: rgba(15, 23, 42, 0.78); }

.cryostack-reg-steps {
    margin: 6px 0 8px;
    padding-left: 20px;
    font-size: 13px;
    line-height: 1.6;
    color: rgba(15, 23, 42, 0.78);
}

.cryostack-portal-link,
a.cryostack-portal-link {
    display: inline-block;
    margin-top: 4px;
    padding: 7px 12px;
    border-radius: 8px;
    background: #2563eb;
    color: #ffffff;
    font-weight: 700;
    font-size: 13px;
    text-decoration: none;
}


/* =========================================================
   B4 -- narrow-width behaviour for the grouped panels
   ========================================================= */

@media (max-width: 768px) {
    .cryostack-field-row {
        flex-direction: column;
        align-items: stretch;
        gap: 10px;
    }

    .cryostack-remote-connection-panel .cryostack-field,
    .cryostack-slurm-resources-panel .cryostack-field {
        width: 100%;
        flex: 1 1 auto;
    }

    .cryostack-conn-actions {
        flex-wrap: wrap;
    }

    .cryostack-conn-actions .widget-button {
        width: 100%;
    }

    .cryostack-remote-connection-panel .widget-text,
    .cryostack-remote-connection-panel .widget-dropdown,
    .cryostack-remote-connection-panel .widget-inttext,
    .cryostack-remote-connection-panel .widget-togglebuttons {
        width: 100% !important;
    }

    .cryostack-advanced-accordion,
    .cryostack-advanced-accordion .widget-accordion-child {
        width: 100%;
        max-width: 100%;
    }
}

@media (max-width: 430px) {
    .cryostack-group-title { font-size: 12px; }
}

@media (max-width: 360px) {
    .cryostack-conn-status { width: 100%; justify-content: center; }
}


/* =========================================================
   B4 -- dark theme for the new components
   ========================================================= */

html[data-theme="dark"] .cryostack-group-title,
html[data-theme="dark"] .cryostack-field-label { color: #e2e8f0; }
html[data-theme="dark"] .cryostack-help,
html[data-theme="dark"] .cryostack-diag { color: #94a3b8; }
html[data-theme="dark"] .cryostack-diag__k { color: #cbd5e1; }
html[data-theme="dark"] .cryostack-connector-card {
    border-color: rgba(37, 99, 235, 0.30);
    background: rgba(37, 99, 235, 0.12);
}
html[data-theme="dark"] .cryostack-reg-steps { color: #cbd5e1; }

</style>
"""


def shared_application_styles() -> W.HTML:
    """Return the shared CSS used by CryoStack Voilà applications."""

    widget = W.HTML(value=_SHARED_APPLICATION_CSS)
    widget.layout = W.Layout(width="100%")

    return widget