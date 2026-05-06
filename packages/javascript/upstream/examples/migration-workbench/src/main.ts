import { loadMigrationWorkbenchConfig } from "./config.js";
import {
  applyLiveImportProgress,
  createFixtureMigrationWorkbenchWorkflow,
  createWorkbenchReport,
  missingCloudImportConfig,
  runHonuaCloudImportJob,
  serializeWorkbenchMarkdownReport,
  serializeWorkbenchReport,
} from "./model.js";
import type {
  MigrationWorkbenchWorkflow,
  WorkbenchImportItem,
  WorkbenchStageId,
  WorkbenchStageStatus,
} from "./types.js";

import "./styles.css";

interface WorkbenchRuntime {
  readonly ready: boolean;
  readonly mode: string;
  readonly reportId: string;
  selectStage(stageId: WorkbenchStageId): void;
  startLiveImport(): Promise<void>;
  exportJson(): string;
}

declare global {
  interface Window {
    __HONUA_MIGRATION_WORKBENCH__?: WorkbenchRuntime;
  }
}

const config = loadMigrationWorkbenchConfig();
let workflow: MigrationWorkbenchWorkflow = createFixtureMigrationWorkbenchWorkflow(config);
let activeStageId: WorkbenchStageId = "scan";
let exportUrls: string[] = [];

function getElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Missing required element: ${selector}`);
  return element;
}

function setText(selector: string, value: string): void {
  getElement<HTMLElement>(selector).textContent = value;
}

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function statusLabel(status: string): string {
  return status
    .split("-")
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function render(): void {
  const report = createWorkbenchReport(workflow);
  const json = serializeWorkbenchReport(report);
  const markdown = serializeWorkbenchMarkdownReport(report);

  setText("#mode-badge", workflow.mode === "live" ? "Live Opt-In" : "Demo");
  getElement<HTMLElement>("#mode-badge").dataset.mode = workflow.mode;
  setText("#workflow-title", workflow.source.title);
  setText("#source-title", workflow.source.title);
  setText("#source-fixture", workflow.fixtureName);
  setText("#source-portal", workflow.source.sourcePortal);
  setText("#source-profile", workflow.source.compatibilityProfile);
  setText("#summary-readiness", workflow.readiness);
  setText("#summary-manual", String(report.summary.manualActionCount));
  setText("#summary-blocked", String(report.summary.blockedActionCount));
  setText("#summary-reconciliation", workflow.reconciliation.status);

  renderStages();
  renderStageDetail();
  renderContentItems();
  renderImportItems();
  renderActionItems();
  renderArtifacts();
  renderExports(json, markdown);
  getElement<HTMLPreElement>("#report-preview").textContent = json.slice(0, 1_800);
}

function renderStages(): void {
  const stageList = getElement<HTMLElement>("#stage-list");
  stageList.innerHTML = workflow.stages
    .map(
      (stage) => `
        <button class="stage-button" type="button" data-stage="${escapeHtml(stage.id)}" data-active="${
          stage.id === activeStageId ? "true" : "false"
        }">
          <span>
            <strong>${escapeHtml(stage.title)}</strong>
            <small>${escapeHtml(stage.summary)}</small>
          </span>
          <em data-status="${escapeHtml(stage.status)}">${escapeHtml(statusLabel(stage.status))}</em>
        </button>
      `,
    )
    .join("");

  for (const button of Array.from(stageList.querySelectorAll<HTMLButtonElement>(".stage-button"))) {
    button.addEventListener("click", () => {
      activeStageId = button.dataset.stage as WorkbenchStageId;
      render();
    });
  }
}

function renderStageDetail(): void {
  const detail = getElement<HTMLElement>("#stage-detail");
  const stage = workflow.stages.find((item) => item.id === activeStageId) ?? workflow.stages[0];
  if (!stage) return;
  detail.dataset.status = stage.status;
  detail.innerHTML = `
    <div class="section-heading split">
      <div>
        <p class="eyebrow">Active stage</p>
        <h2>${escapeHtml(stage.title)}</h2>
      </div>
      <span class="status-pill" data-status="${escapeHtml(stage.status)}">${escapeHtml(statusLabel(stage.status))}</span>
    </div>
    <p class="stage-summary">${escapeHtml(stage.summary)}</p>
    <dl class="metric-grid">
      ${stage.metrics
        .map(
          (metric) => `
            <div data-tone="${escapeHtml(metric.tone ?? "neutral")}">
              <dt>${escapeHtml(metric.label)}</dt>
              <dd>${escapeHtml(metric.value)}</dd>
            </div>
          `,
        )
        .join("")}
    </dl>
    <ul class="message-list">
      ${stage.userMessages.map((message) => `<li>${escapeHtml(message)}</li>`).join("")}
    </ul>
  `;
}

function renderContentItems(): void {
  const list = getElement<HTMLElement>("#content-list");
  list.innerHTML = workflow.contentItems
    .map(
      (item) => `
        <article class="item-row" data-status="${escapeHtml(item.status)}">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.userMessage)}</p>
            <code>${escapeHtml(item.artifactPath)}</code>
          </div>
          <span>${escapeHtml(statusLabel(item.status))}</span>
        </article>
      `,
    )
    .join("");
}

function renderImportItems(): void {
  const list = getElement<HTMLElement>("#import-list");
  const startButton = getElement<HTMLButtonElement>("#start-live-import");
  const runnable = workflow.mode === "live" && workflow.importItems.some((item) => item.status === "configured");
  startButton.disabled = !runnable;
  startButton.textContent = workflow.mode === "live" ? "Start Live" : "Demo Only";

  list.innerHTML = workflow.importItems
    .map(
      (item) => `
        <article class="item-row" data-status="${escapeHtml(item.status)}">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.userMessage)}</p>
            <code>${escapeHtml(item.tableName)} ? layer ${escapeHtml(item.layerId)}</code>
          </div>
          <span>${escapeHtml(item.statusLabel)}</span>
        </article>
      `,
    )
    .join("");
}

function renderActionItems(): void {
  const list = getElement<HTMLElement>("#action-list");
  list.innerHTML = workflow.actionItems
    .map(
      (item) => `
        <article class="action-row" data-severity="${escapeHtml(item.severity)}">
          <span>${escapeHtml(item.severity.toUpperCase())}</span>
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.userMessage)}</p>
            <small>${escapeHtml(item.nextStep)}</small>
          </div>
        </article>
      `,
    )
    .join("");
}

function renderArtifacts(): void {
  const list = getElement<HTMLElement>("#artifact-list");
  list.innerHTML = workflow.artifacts
    .map(
      (artifact) => `
        <a href="${escapeHtml(artifact.href)}">
          <strong>${escapeHtml(artifact.label)}</strong>
          <span>${escapeHtml(artifact.description)}</span>
        </a>
      `,
    )
    .join("");
}

function renderExports(json: string, markdown: string): void {
  for (const url of exportUrls) URL.revokeObjectURL(url);
  exportUrls = [];
  const jsonUrl = URL.createObjectURL(new Blob([json], { type: "application/json" }));
  const markdownUrl = URL.createObjectURL(new Blob([markdown], { type: "text/markdown" }));
  exportUrls.push(jsonUrl, markdownUrl);

  const jsonLink = getElement<HTMLAnchorElement>("#json-export");
  jsonLink.href = jsonUrl;
  jsonLink.download = `${workflow.reportId}.json`;

  const markdownLink = getElement<HTMLAnchorElement>("#markdown-export");
  markdownLink.href = markdownUrl;
  markdownLink.download = `${workflow.reportId}.md`;
}

async function startLiveImport(): Promise<void> {
  const target = workflow.importItems.find((item) => item.status === "configured");
  if (!target) {
    const missing = missingCloudImportConfig(workflow.cloudImport);
    window.alert(`Live import is not ready: ${missing.join(", ") || "no configured import item"}`);
    return;
  }

  workflow = applyLiveImportProgress(workflow, {
    item: {
      ...target,
      status: "running",
      statusLabel: "Polling Honua Cloud",
      userMessage: "Honua Cloud import job is running and the workbench is polling status.",
    },
  });
  activeStageId = "import";
  render();

  try {
    const progress = await runHonuaCloudImportJob(workflow.cloudImport);
    workflow = applyLiveImportProgress(workflow, {
      ...progress,
      item: {
        ...progress.item,
        id: target.id,
        title: target.title,
        artifactPath: target.artifactPath,
      },
    });
  } catch (error) {
    workflow = applyLiveImportProgress(workflow, {
      item: {
        ...target,
        status: "failed",
        statusLabel: "Live import failed",
        userMessage: error instanceof Error ? error.message : String(error),
      },
    });
  }
  render();
}

getElement<HTMLButtonElement>("#start-live-import").addEventListener("click", () => {
  void startLiveImport();
});

window.__HONUA_MIGRATION_WORKBENCH__ = {
  ready: true,
  mode: workflow.mode,
  reportId: workflow.reportId,
  selectStage(stageId: WorkbenchStageId): void {
    activeStageId = stageId;
    render();
  },
  startLiveImport,
  exportJson(): string {
    return serializeWorkbenchReport(createWorkbenchReport(workflow));
  },
};

render();
