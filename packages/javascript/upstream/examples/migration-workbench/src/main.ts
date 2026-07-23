import { SampleCleanupRegistry } from "../../_kit/cleanup.js";
import { mountSamplePresentation } from "../../_kit/presentation.js";
import { loadMigrationWorkbenchArtifacts } from "./artifacts.js";
import { createMigrationWorkbenchViewModel, formatArtifactCommand } from "./model.js";
import type {
  CodemodKindMetric,
  EvidenceMetric,
  JsonValue,
  ManualTodo,
  MigrationGate,
  MigrationWorkbenchViewModel,
  UnsupportedModule,
} from "./types.js";

import "../../_kit/presentation.css";
import "./styles.css";

declare const __HONUA_SAMPLE_SDK_MODE__: "source" | "packed";
declare const __HONUA_SDK_VERSION__: string;

interface WorkbenchRuntime {
  ready: boolean;
  disposed: boolean;
  sdkMode: "source" | "packed";
  sdkVersion: string;
  model?: MigrationWorkbenchViewModel;
  error?: string;
  dispose(): Promise<void>;
}

declare global {
  interface Window {
    __HONUA_MIGRATION_WORKBENCH__?: WorkbenchRuntime;
    __HONUA_MIGRATION_WORKBENCH_DISPOSE__?: () => Promise<void>;
  }
}

const cleanup = new SampleCleanupRegistry();
const bootstrapController = new AbortController();
cleanup.add(() => bootstrapController.abort());

const runtime: WorkbenchRuntime = {
  ready: false,
  disposed: false,
  sdkMode: __HONUA_SAMPLE_SDK_MODE__,
  sdkVersion: __HONUA_SDK_VERSION__,
  dispose,
};

const presentation = mountSamplePresentation({
  sampleId: "migration-workbench",
  evidence: {
    mode: "committed artifact replay",
    fixture: "arcgis-source-app",
    artifacts: "manifest-bound SHA-256 evidence",
    network: "loopback fixture only",
  },
  onDispose: dispose,
});
cleanup.add(() => presentation.root.remove());
cleanup.listen(window, "beforeunload", () => void dispose(), { once: true });

window.__HONUA_MIGRATION_WORKBENCH__ = runtime;
window.__HONUA_MIGRATION_WORKBENCH_DISPOSE__ = dispose;
cleanup.add(() => {
  delete window.__HONUA_MIGRATION_WORKBENCH_DISPOSE__;
});

void bootstrap();

async function dispose(): Promise<void> {
  bootstrapController.abort();
  await cleanup.dispose();
  runtime.ready = false;
  runtime.disposed = true;
  runtime.model = undefined;
}

async function bootstrap(): Promise<void> {
  try {
    const [artifacts, generatedTarget] = await Promise.all([
      loadMigrationWorkbenchArtifacts({ signal: bootstrapController.signal }),
      import("./generated/migrated-main.js"),
    ]);
    bootstrapController.signal.throwIfAborted();
    const model = createMigrationWorkbenchViewModel(artifacts, generatedTarget.default);
    render(model);
    runtime.model = model;
    runtime.ready = true;
    presentation.updateEvidence({
      mode: `${runtime.sdkMode} SDK ${runtime.sdkVersion}`,
      fixture: model.fixture,
      artifacts: `${model.artifactSet} ? ${model.files.length} manifest-bound files ? ${model.assertions.length} browser assertions`,
      network: model.source.credentialsRequired ? "credentials declared" : "credential-free loopback replay",
    });
  } catch (error) {
    if (bootstrapController.signal.aborted) return;
    const message = error instanceof Error ? error.message : String(error);
    const errorPanel = getElement<HTMLElement>("#load-error");
    errorPanel.hidden = false;
    errorPanel.textContent = `Migration evidence could not be loaded: ${message}`;
    setText("#runtime-status", "Failed");
    getElement<HTMLElement>("#runtime-status").dataset.status = "failed";
    runtime.error = message;
    presentation.showError(error);
  }
}

function render(model: MigrationWorkbenchViewModel): void {
  setText("#fixture-name", model.fixture);
  setText("#target-name", model.target);
  setText("#artifact-set", model.artifactSet);
  const browserAssertionsPassed = model.assertions.filter(
    (assertion) => assertion.passed && assertion.browserPassed,
  ).length;
  setText(
    "#runtime-status",
    model.browserProofPassed
      ? `${browserAssertionsPassed} / ${model.assertions.length} passed`
      : `${browserAssertionsPassed} / ${model.assertions.length} passed ? review mismatches`,
  );
  getElement<HTMLElement>("#runtime-status").dataset.status = model.browserProofPassed ? "passed" : "failed";

  renderSource(model);
  renderCompatibility(model);
  renderAssertions(model);
  renderWidgets(model);
  renderMapLibre(model);
  renderCommands(model);
  renderArtifacts(model);
  getElement<HTMLPreElement>("#migration-diff").textContent = model.diff;
}

function renderSource(model: MigrationWorkbenchViewModel): void {
  getElement<HTMLElement>("#source-facts").innerHTML = [
    fact("Repository fixture", model.source.path),
    fact("Authorship", model.source.authorship),
    fact("License scope", model.source.licenseScope),
    fact("Source upload", model.source.sourceUpload ? "Yes" : "No"),
    fact("Credentials required", model.source.credentialsRequired ? "Yes" : "No"),
    fact("Generated", model.generatedAt),
  ].join("");
}

function renderCompatibility(model: MigrationWorkbenchViewModel): void {
  setText("#compat-readiness", model.compatibility.readiness);
  getElement<HTMLElement>("#compat-readiness").dataset.status = model.compatibility.passed ? "passed" : "failed";
  renderMetrics("#compat-metrics", model.compatibility.metrics);
  renderGates("#compat-gates", model.compatibility.gates);
  renderResiduals("#compat-residuals", model.compatibility.manualTodos, model.compatibility.unsupportedModules);
  renderMappings("#compat-mappings", model.compatibility.mappings);
}

function renderAssertions(model: MigrationWorkbenchViewModel): void {
  const passed = model.assertions.filter((assertion) => assertion.passed && assertion.browserPassed).length;
  setText("#assertion-summary", `${passed} / ${model.assertions.length} browser checks passed`);
  getElement<HTMLElement>("#assertion-summary").dataset.status = model.browserProofPassed ? "passed" : "failed";
  getElement<HTMLElement>("#assertion-matrix").innerHTML = `
    <table>
      <thead><tr><th scope="col">Assertion</th><th scope="col">Expected</th><th scope="col">Stored run</th><th scope="col">Stored status</th><th scope="col">Browser run</th><th scope="col">Browser status</th></tr></thead>
      <tbody>${model.assertions
        .map(
          (assertion) => `<tr>
            <th scope="row"><code>${escapeHtml(assertion.path)}</code></th>
            <td><code>${escapeHtml(formatJson(assertion.expected))}</code></td>
            <td><code>${escapeHtml(formatJson(assertion.observed))}</code></td>
            <td><span class="row-status" data-status="${assertion.passed ? "passed" : "failed"}">${
              assertion.passed ? "Pass" : "Fail"
            }</span></td>
            <td><code>${escapeHtml(formatJson(assertion.browserObserved))}</code></td>
            <td><span class="row-status" data-status="${assertion.browserPassed ? "passed" : "failed"}">${
              assertion.browserPassed ? "Pass" : "Fail"
            }</span></td>
          </tr>`,
        )
        .join("")}</tbody>
    </table>`;
}

function renderWidgets(model: MigrationWorkbenchViewModel): void {
  const summary = model.widgets.summary;
  renderMetrics("#widget-metrics", [
    metric("widget-total", "Usage sites", summary.totalSites, "neutral", "Widget CLI report"),
    metric("widget-automated", "Automated", summary.automatedSites, "good", "Widget usage sites"),
    metric("widget-assisted", "Assisted", summary.assistedSites, "warning", "Widget usage sites"),
    metric(
      "widget-manual",
      "Manual",
      summary.manualSites,
      summary.manualSites === 0 ? "good" : "danger",
      "Widget usage sites",
    ),
  ]);
  setText("#widget-summary", model.widgets.summaryLine);
  getElement<HTMLElement>("#widget-guidance").innerHTML = `
    <table>
      <thead><tr><th scope="col">Widget</th><th scope="col">Bucket</th><th scope="col">Disposition</th><th scope="col">Target</th><th scope="col">Sites</th><th scope="col">Guidance</th></tr></thead>
      <tbody>${model.widgets.widgets
        .map(
          (widget) => `<tr>
            <th scope="row">${escapeHtml(widget.widget)}</th>
            <td><span class="row-status" data-status="${escapeHtml(widget.bucket)}">${escapeHtml(widget.bucket)}</span></td>
            <td>${escapeHtml(widget.disposition)}</td>
            <td><code>${escapeHtml(widget.target)}</code></td>
            <td>${widget.count}</td>
            <td><a href="${escapeHtml(guideHref(widget.guideLink))}">${escapeHtml(widget.guideLink)}</a></td>
          </tr>`,
        )
        .join("")}</tbody>
    </table>`;
}

function renderMapLibre(model: MigrationWorkbenchViewModel): void {
  setText("#maplibre-readiness", model.maplibre.readiness);
  getElement<HTMLElement>("#maplibre-readiness").dataset.status =
    model.maplibre.manualTodos.length === 0 && model.maplibre.unsupportedModules.length === 0 ? "passed" : "warning";
  renderMetrics("#maplibre-metrics", model.maplibre.metrics);
  renderGates("#maplibre-gates", model.maplibre.gates);
  renderResiduals("#maplibre-residuals", model.maplibre.manualTodos, model.maplibre.unsupportedModules);
  renderMappings("#maplibre-mappings", model.maplibre.mappings);
}

function renderCommands(model: MigrationWorkbenchViewModel): void {
  getElement<HTMLElement>("#command-list").innerHTML = model.commands
    .map(
      (command) => `<article class="command-card">
        <div><strong>${escapeHtml(command.id)}</strong><span>exit ${command.exitCode}</span></div>
        <pre tabindex="0">${escapeHtml(formatArtifactCommand(command.executable, command.argv))}</pre>
      </article>`,
    )
    .join("");
}

function renderArtifacts(model: MigrationWorkbenchViewModel): void {
  getElement<HTMLElement>("#artifact-files").innerHTML = `
    <table>
      <thead><tr><th scope="col">Artifact</th><th scope="col">Media type</th><th scope="col">Bytes</th><th scope="col">SHA-256</th></tr></thead>
      <tbody>${model.files
        .map(
          (file) => `<tr>
            <th scope="row">${
              file.href
                ? `<a href="${escapeHtml(file.href)}">${escapeHtml(file.repositoryPath)}</a>`
                : `${escapeHtml(file.repositoryPath)} <small>(bundled runtime module)</small>`
            }</th>
            <td>${escapeHtml(file.mediaType)}</td>
            <td>${file.bytes.toLocaleString("en-US")}</td>
            <td><code class="hash">${escapeHtml(file.sha256)}</code></td>
          </tr>`,
        )
        .join("")}</tbody>
    </table>`;
  getElement<HTMLElement>("#patch-proof").innerHTML = [
    fact("Apply check", passFail(model.patchProof.applyCheckPassed)),
    fact("Applied tree equals target", passFail(model.patchProof.targetTreeEqual)),
    fact("Generated entry exact", passFail(model.patchProof.directEntryComparisonPassed)),
    fact("Target tree SHA-256", model.patchProof.targetTreeSha256),
  ].join("");
}

function renderMetrics(selector: string, metrics: readonly EvidenceMetric[]): void {
  getElement<HTMLElement>(selector).innerHTML = metrics
    .map(
      (item) => `<article class="metric-card" data-metric-id="${escapeHtml(item.id)}" data-tone="${item.tone}">
        <span>${escapeHtml(item.label)}</span>
        <strong>${escapeHtml(item.value)}</strong>
        <small>${escapeHtml(item.scope)}</small>
      </article>`,
    )
    .join("");
}

function renderGates(selector: string, gates: readonly MigrationGate[]): void {
  getElement<HTMLElement>(selector).innerHTML = gates
    .map(
      (gate) => `<article class="evidence-row">
        <span class="row-status" data-status="${gate.passed ? "passed" : "failed"}">${gate.passed ? "Pass" : "Not passed"}</span>
        <div><strong>${escapeHtml(gate.gate)}</strong><p>${escapeHtml(gate.detail)}</p></div>
      </article>`,
    )
    .join("");
}

function renderResiduals(
  selector: string,
  manualTodos: readonly ManualTodo[],
  unsupportedModules: readonly UnsupportedModule[],
): void {
  const rows = [
    `<article class="evidence-row zero-row"><span class="count-badge">${manualTodos.length}</span><div><strong>Manual findings</strong><p>${
      manualTodos.length === 0 ? "None reported by the CLI." : "Every manual finding is listed below."
    }</p></div></article>`,
    ...manualTodos.map(
      (todo) => `<article class="evidence-row">
        <span class="row-status" data-status="warning">${escapeHtml(todo.difficulty)}</span>
        <div><strong>${escapeHtml(todo.kind)} ? ${escapeHtml(todo.file)}:${todo.line}:${todo.column}</strong><p>${escapeHtml(todo.reason)}</p></div>
      </article>`,
    ),
    `<article class="evidence-row zero-row"><span class="count-badge">${unsupportedModules.length}</span><div><strong>Unsupported modules</strong><p>${
      unsupportedModules.length === 0 ? "None reported by the CLI." : "Every unsupported module is listed below."
    }</p></div></article>`,
    ...unsupportedModules.map(
      (module) => `<article class="evidence-row">
        <span class="count-badge">${module.count}</span>
        <div><strong><code>${escapeHtml(module.modulePath)}</code></strong><p>${escapeHtml(module.usageStyle)}</p></div>
      </article>`,
    ),
  ];
  getElement<HTMLElement>(selector).innerHTML = rows.join("");
}

function renderMappings(selector: string, mappings: readonly ({ readonly kind: string } & CodemodKindMetric)[]): void {
  getElement<HTMLElement>(selector).innerHTML = `
    <table>
      <thead><tr><th scope="col">Kind</th><th scope="col">Total</th><th scope="col">Auto</th><th scope="col">Manual</th></tr></thead>
      <tbody>${mappings
        .map(
          (mapping) => `<tr data-zero="${mapping.total === 0}">
            <th scope="row"><code>${escapeHtml(mapping.kind)}</code></th>
            <td>${mapping.total}</td><td>${mapping.autoMigrated}</td><td>${mapping.manual}</td>
          </tr>`,
        )
        .join("")}</tbody>
    </table>`;
}

function metric(
  id: string,
  label: string,
  value: number | string,
  tone: EvidenceMetric["tone"],
  scope: string,
): EvidenceMetric {
  return { id, label, value, tone, scope };
}

function guideHref(path: string): string {
  return `https://github.com/honua-io/honua-sdk-js/blob/trunk/${path}`;
}

function fact(label: string, value: string): string {
  return `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`;
}

function passFail(value: boolean): string {
  return value ? "Passed" : "Failed";
}

function formatJson(value: JsonValue | undefined): string {
  return value === undefined ? "missing" : JSON.stringify(value);
}

function setText(selector: string, value: string): void {
  getElement<HTMLElement>(selector).textContent = value;
}

function getElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Missing required element: ${selector}`);
  return element;
}

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
