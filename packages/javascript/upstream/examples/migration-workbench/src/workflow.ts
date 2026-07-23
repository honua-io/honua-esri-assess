import type { AssertionMatrixRow, BehaviorAssertion, JsonValue } from "./types.js";

export function createAssertionMatrix(
  assertions: readonly BehaviorAssertion[],
  browserObservations: unknown,
): readonly AssertionMatrixRow[] {
  return assertions.map((assertion) => {
    const browserObserved = readJsonPath(browserObservations, assertion.path);
    return {
      ...assertion,
      browserObserved,
      browserPassed: browserObserved !== undefined && jsonValuesEqual(assertion.expected, browserObserved),
    };
  });
}

export function readJsonPath(value: unknown, path: string): JsonValue | undefined {
  if (!path.startsWith("$")) return undefined;
  let current: unknown = value;
  let cursor = 1;
  const tokenPattern = /\.([A-Za-z0-9_-]+)|\[(\d+)\]/gu;

  for (const match of path.matchAll(tokenPattern)) {
    if (match.index !== cursor) return undefined;
    cursor = match.index + match[0].length;
    if (match[1] !== undefined) {
      if (!current || typeof current !== "object" || Array.isArray(current)) return undefined;
      current = (current as Record<string, unknown>)[match[1]];
    } else {
      if (!Array.isArray(current)) return undefined;
      current = current[Number(match[2])];
    }
  }

  if (cursor !== path.length || !isJsonValue(current)) return undefined;
  return current;
}

export function jsonValuesEqual(left: JsonValue, right: JsonValue): boolean {
  if (left === right) return true;
  if (Array.isArray(left)) {
    return (
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((item, index) => jsonValuesEqual(item, right[index]))
    );
  }
  if (left && right && typeof left === "object" && typeof right === "object" && !Array.isArray(right)) {
    const leftEntries = Object.entries(left);
    const rightRecord = right as Readonly<Record<string, JsonValue>>;
    return (
      leftEntries.length === Object.keys(rightRecord).length &&
      leftEntries.every(([key, item]) => key in rightRecord && jsonValuesEqual(item, rightRecord[key]))
    );
  }
  return false;
}

function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return true;
  }
  if (Array.isArray(value)) return value.every(isJsonValue);
  return Boolean(value) && typeof value === "object" && Object.values(value).every(isJsonValue);
}
