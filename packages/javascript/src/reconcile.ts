export interface ReconcilePlan { source: string; target: string; layerId: number; sampleSize: number; mode: "plan" }
export function createReconcilePlan(source: string, target: string, layerId: number, sampleSize = 100): ReconcilePlan {
  if (!Number.isInteger(layerId) || layerId < 0) throw new Error("layerId must be a non-negative integer");
  return { source, target, layerId, sampleSize, mode: "plan" };
}
