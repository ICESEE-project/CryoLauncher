# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : Shared Theme
# File        : theme.py
#
# Description :
#     Defines shared CryoStack frontend styling used across scientific
#     applications and execution interfaces.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-25
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
Shared CryoStack frontend styling.

This module contains presentation only. Backend and execution behavior
must not be introduced here.
"""


CRYOSTACK_FRONTEND_CSS = r"""
<style>

:root {
  --cryostack-blue: #1264d8;
  --cryostack-blue-soft: #edf5ff;

  --cryostack-text: #172033;
  --cryostack-muted: #66758d;

  --cryostack-border: #dfe6ef;
  --cryostack-border-soft: #edf1f6;

  --cryostack-panel: #ffffff;
  --cryostack-background: #f7f9fc;

  --cryostack-success: #20a45b;
  --cryostack-warning: #d99516;
  --cryostack-danger: #d64242;

  --cryostack-radius: 10px;
}


/* ---------------------------------------------------------
   Global application area
   --------------------------------------------------------- */

.cryostack-ui {
  color: var(--cryostack-text);
  width: 100%;
}

.cryostack-ui * {
  box-sizing: border-box;
}


/* ---------------------------------------------------------
   Section heading
   --------------------------------------------------------- */

.cryostack-section-heading {
  margin-bottom: 12px;
}

.cryostack-section-heading h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--cryostack-text);
}

.cryostack-section-heading p {
  margin: 4px 0 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--cryostack-muted);
}


/* ---------------------------------------------------------
   Cards
   --------------------------------------------------------- */

.cryostack-card {
  background: var(--cryostack-panel);
  border: 1px solid var(--cryostack-border);
  border-radius: var(--cryostack-radius);
  overflow: hidden;
}

.cryostack-card-header {
  padding: 12px 14px;
  border-bottom: 1px solid var(--cryostack-border-soft);
  font-size: 13px;
  font-weight: 700;
  color: var(--cryostack-text);
}

.cryostack-card-body {
  padding: 14px;
}


/* ---------------------------------------------------------
   Detail rows
   --------------------------------------------------------- */

.cryostack-detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;

  padding: 9px 0;
  border-bottom: 1px solid var(--cryostack-border-soft);
}

.cryostack-detail-row:last-child {
  border-bottom: 0;
}

.cryostack-detail-label {
  color: var(--cryostack-muted);
  font-size: 12px;
}

.cryostack-detail-value {
  color: var(--cryostack-text);
  font-size: 12px;
  font-weight: 600;
  text-align: right;
}


/* ---------------------------------------------------------
   Status indicators
   --------------------------------------------------------- */

.cryostack-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;

  padding: 4px 9px;

  border-radius: 999px;

  font-size: 11px;
  font-weight: 700;
}

.cryostack-status::before {
  content: "";
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.cryostack-status-idle {
  background: #f1f4f8;
  color: #64748b;
}

.cryostack-status-idle::before {
  background: #a8b4c4;
}

.cryostack-status-running {
  background: #edf5ff;
  color: #1264d8;
}

.cryostack-status-running::before {
  background: #1264d8;
}

.cryostack-status-ready,
.cryostack-status-success {
  background: #edf9f1;
  color: #16834a;
}

.cryostack-status-ready::before,
.cryostack-status-success::before {
  background: #20a45b;
}

.cryostack-status-warning {
  background: #fff7e7;
  color: #a66800;
}

.cryostack-status-warning::before {
  background: #d99516;
}

.cryostack-status-error,
.cryostack-status-failed {
  background: #fff0f0;
  color: #bf3030;
}

.cryostack-status-error::before,
.cryostack-status-failed::before {
  background: #d64242;
}


/* ---------------------------------------------------------
   Environment state
   --------------------------------------------------------- */

.cryostack-environment-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.cryostack-environment-item {
  padding: 10px 12px;

  border: 1px solid var(--cryostack-border-soft);
  border-radius: 8px;

  background: #fafbfd;
}

.cryostack-environment-item-label {
  color: var(--cryostack-muted);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.cryostack-environment-item-value {
  margin-top: 4px;
  font-size: 12px;
  font-weight: 700;
}


/* ---------------------------------------------------------
   Runtime toolbar
   --------------------------------------------------------- */

.cryostack-runtime-toolbar {
  padding-top: 10px;
  border-top: 1px solid var(--cryostack-border-soft);
}


/* ---------------------------------------------------------
   Advanced details
   --------------------------------------------------------- */

.cryostack-advanced-note {
  margin-top: 8px;
  padding: 8px 10px;

  background: #fafbfd;
  border: 1px solid var(--cryostack-border-soft);
  border-radius: 7px;

  color: var(--cryostack-muted);
  font-size: 11px;
}


/* ---------------------------------------------------------
   Responsive
   --------------------------------------------------------- */

@media (max-width: 900px) {

  .cryostack-environment-grid {
    grid-template-columns: 1fr;
  }

}

/*
 * Two-column application shell.
 *
 * The columns align at the TOP and each grows to its own natural content
 * height. The left (Run settings) card must never determine or cap the
 * height of the right (Workspace) card -- in Agent mode the left card is
 * short, and the Workspace must still show all of its content. There is no
 * equal-height / stretch behaviour and no inner Workspace scrollbar: a tall
 * Workspace scrolls with the page.
 */
.icesee-grid {
    display: grid !important;
    grid-template-columns:
        minmax(0, 46fr)
        minmax(0, 54fr);

    gap: 16px;
    align-items: start;
}

.icesee-left {
    min-width: 0;
    align-self: start;
}

.icesee-right {
    min-width: 0;
    align-self: start;

    /* natural height -- never clipped by the left column */
    height: auto;
    min-height: 0;
    overflow: visible;
}

.icesee-right > .widget-vbox {
    position: static;

    width: 100%;
    height: auto;

    min-width: 0;
    min-height: 0;

    overflow: visible;
}

/*
 * Desktop enhancement: keep the Workspace in view while a very tall Run
 * settings column scrolls. Sticky (not fixed) -- if the Workspace itself is
 * taller than the viewport it scrolls away with the page rather than being
 * trapped. Disabled on tablet / mobile (below).
 */
@media (min-width: 1051px) {
    .cryostack-right-workspace {
        position: sticky;
        top: 12px;
    }
}

@media (max-width: 1050px) {
    .icesee-grid {
        grid-template-columns: 1fr;
    }

    .cryostack-right-workspace,
    .icesee-right {
        position: static;
    }

    /* prefer natural page flow; relax the aggressive nested scrolling and
       keep touch devices out of nested-scroll pain. No horizontal overflow. */
    .cryostack-log-viewer,
    .cryostack-results-viewer {
        max-height: none !important;
        min-height: 220px;
    }

    .cryostack-live-log {
        max-height: none;
    }

    .cryostack-output-workspace,
    .cryostack-workspace-tabs > .widget-tab-contents {
        overflow-x: hidden;
    }
}

.cryostack-output-workspace {
    display: flex;
    flex-direction: column;

    width: 100%;
    height: auto;

    min-height: 0;

    overflow: visible;
}

.cryostack-output-tabs {
    flex: 0 0 auto;

    width: 100%;
    min-height: 0;

    overflow: visible;
}

.cryostack-output-tab {
    display: flex;
    flex-direction: column;

    width: 100%;
    height: auto;

    min-height: 0;

    overflow: visible;
}

.cryostack-right-workspace {
    min-height: 0;
}

/*
 * ipywidgets Tab: <div.widget-tab (flex column)> > <div.widget-tab-contents
 * (flex-grow:1; overflow:auto)>. The default makes the tab body a fixed-size
 * inner scroll region. For a natural-height Workspace the body flows in normal
 * document order and the page scrolls. Only a small floor so an empty tab is
 * not zero-height -- Runs / Files stay compact and are NOT forced to the taller
 * Run Log / Results viewer height.
 */
.cryostack-workspace-tabs.widget-tab,
.cryostack-workspace-tabs {
    height: auto !important;
}

.cryostack-workspace-tabs > .widget-tab-contents {
    flex-grow: 0;
    height: auto !important;
    min-height: 120px;
    overflow: visible !important;
}

/*
 * Run Log / Results viewers -- geometry-aware dynamic height.
 *
 * The viewer-sizing module (workspace/viewer_geometry.js) measures the actual
 * rendered geometry -- visible viewport height, viewer top, left Run Settings
 * column bottom -- and sets ONE scoped custom property:
 *     --cryostack-workspace-viewer-max-height: <px>
 * Priority: natural content height, then useful viewport space, then a
 * secondary desktop balance against the left column (never below a usable
 * minimum). Short content ends naturally (max-height is a cap, not a height,
 * and there is no cap until the script computes one); long content uses the
 * available space, then scrolls internally. `position: relative` anchors the
 * "Jump to latest" control.
 */
.cryostack-log-viewer {
    position: relative;
    min-height: 280px;
    max-height: var(--cryostack-workspace-viewer-max-height, none);
    overflow-y: auto;
    overflow-x: auto;
}

.cryostack-results-viewer {
    position: relative;
    width: 100%;
    min-height: 300px;
    max-height: var(--cryostack-workspace-viewer-max-height, none);
    overflow-y: auto;
    overflow-x: auto;
}

/* Results gallery: each captured figure is a discrete card (title + image +
   filename/labels), not one continuous vertical stream of plots. */
.cryostack-figure-card {
    border: 1px solid rgba(15, 23, 42, 0.14);
    border-radius: 10px;
    padding: 12px 12px 8px;
    background: #ffffff;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
}
.cryostack-figure-card .cryostack-figure-title {
    font-size: 13px;
    font-weight: 700;
    color: #172033;
    margin-bottom: 8px;
    line-height: 1.35;
}
.cryostack-figure-card .cryostack-figure-sub {
    font-size: 11px;
    color: #8a94a6;
    margin-top: 6px;
    line-height: 1.4;
    word-break: break-word;
}
.cryostack-figure-card img {
    display: block;
    max-width: 100%;
    height: auto;
    border-radius: 6px;
}

/* "Jump to latest" -- shown only while the user has scrolled up from the tail;
   sticks to the bottom-right of the Run Log viewer. */
.cryostack-tail-jump {
    position: sticky;
    bottom: 8px;
    left: 100%;
    transform: translateX(-100%);
    margin-right: 8px;
    padding: 4px 12px;
    border: 1px solid rgba(15, 23, 42, 0.18);
    border-radius: 999px;
    background: #2563eb;
    color: #fff;
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.18);
}

.cryostack-tail-jump[hidden] {
    display: none;
}

/* the secondary text output (run summary / sync messages): keep a modest cap */
.cryostack-live-log {
    min-height: 0;
    max-height: 70vh;
    overflow-y: auto;
    overflow-x: auto;
}


.cryostack-workspace-heading {
    box-sizing: border-box;
    min-height: 38px;
    padding: 9px 12px 8px;
    border-bottom: 1px solid var(--cryostack-border-soft);
    background: var(--cryostack-surface, #fff);
    color: var(--cryostack-text, #172033);
    font-size: 14px;
    font-weight: 700;
    line-height: 20px;
}

.cryostack-workspace-tabs > .p-TabBar .p-TabBar-tab,
.cryostack-workspace-tabs > .lm-TabBar .lm-TabBar-tab {
    min-width: 72px;
    padding: 0 12px;
    justify-content: center;
}

.cryostack-workspace-tabs > .p-TabBar .p-mod-current,
.cryostack-workspace-tabs > .lm-TabBar .lm-mod-current {
    color: var(--cryostack-accent, #2563eb);
    font-weight: 700;
    border-bottom: 2px solid var(--cryostack-accent, #2563eb);
}

.cryostack-section-label {
    color: var(--cryostack-text, #172033);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: .02em;
    text-transform: uppercase;
}

.cryostack-selected-label {
    margin-top: 8px;
    padding-top: 10px;
    border-top: 1px solid var(--cryostack-border-soft);
}

.cryostack-run-row {
    box-sizing: border-box;
    min-height: 34px;
    padding: 2px 7px 2px 3px;
    border-left: 3px solid transparent;
    border-radius: 3px;
}

.cryostack-run-row:hover {
    background: var(--cryostack-surface-muted, #f3f6fa);
}

.cryostack-run-row-selected {
    border-left-color: var(--cryostack-accent, #2563eb);
    background: var(--cryostack-surface-muted, #eef4ff);
}

.cryostack-run-select.jupyter-button {
    overflow: hidden;
    padding: 3px 5px;
    border: 0;
    background: transparent;
    box-shadow: none;
    color: var(--cryostack-text, #172033);
    text-align: left;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.cryostack-run-badge {
    display: inline-block;
    min-width: 58px;
    padding: 2px 7px;
    border-radius: 999px;
    background: #e5e7eb;
    color: #374151;
    font-size: 10px;
    font-weight: 700;
    line-height: 16px;
    text-align: center;
}

.cryostack-run-badge-running { background: #dbeafe; color: #1d4ed8; }
.cryostack-run-badge-queued,
.cryostack-run-badge-submitted { background: #fef3c7; color: #92400e; }
.cryostack-run-badge-completed { background: #dcfce7; color: #166534; }
.cryostack-run-badge-failed,
.cryostack-run-badge-cancelled { background: #fee2e2; color: #991b1b; }

.cryostack-run-job {
    color: var(--cryostack-muted, #66758d);
    font: 11px/1.4 monospace;
    white-space: nowrap;
}

.cryostack-selected-run-card {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 7px 14px;
    padding: 10px 12px;
    border: 1px solid var(--cryostack-border-soft);
    border-radius: 6px;
    background: var(--cryostack-surface-muted, #fafbfd);
}

.cryostack-selected-run-card > div {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
}

.cryostack-selected-run-card span:first-child {
    color: var(--cryostack-muted, #66758d);
    font-size: 11px;
}

.cryostack-selected-run-card b {
    overflow: hidden;
    color: var(--cryostack-text, #172033);
    font-size: 11px;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.cryostack-runs-empty { padding: 14px 8px; }

.cryostack-workspace-tree {
    box-sizing: border-box;
    width: 100%;
    min-height: 100%;
    margin: 0;
    padding: 10px;
    overflow: auto;
    border: 1px solid rgba(0, 0, 0, .10);
    border-radius: 4px;
    background: #fafbfd;
    color: #172033;
    font: 12px/1.55 monospace;
    white-space: pre;
}

/* the widget root scrolls (max-height set by the viewer-sizing script); the
   inner output area flows naturally so there is never a double scrollbar. */
.cryostack-live-log .jupyter-widgets-output-area {
    height: auto;
    min-height: 0;
    overflow: visible;
}

</style>
"""
