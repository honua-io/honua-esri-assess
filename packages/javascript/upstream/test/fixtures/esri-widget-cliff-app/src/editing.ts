import Editor from "@arcgis/core/widgets/Editor";
import FeatureTable from "@arcgis/core/widgets/FeatureTable";

export function createEditingPanel(view: unknown, layer: unknown): { editor: Editor; table: FeatureTable } {
  const editor = new Editor({ view });
  const table = new FeatureTable({ view, layer, container: "tableDiv" });
  return { editor, table };
}

export async function lazyPrint(view: unknown): Promise<void> {
  const { default: Print } = await import("@arcgis/core/widgets/Print");
  const print = new Print({ view });
  void print;
}
