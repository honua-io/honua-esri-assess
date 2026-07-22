const REDACTED_SECRET = "[REDACTED]";
const CREDENTIAL_KEY_PATTERN = /password|passwd|secret|token|authorization|api[-_]?key|credential/i;

export function sanitizeArtifactValue<T>(value: T): T {
  if (typeof value === "string") {
    return sanitizeArtifactString(value) as T;
  }
  if (Array.isArray(value)) {
    return value.map((entry) => sanitizeArtifactValue(entry)) as T;
  }
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value).map(([key, entry]) => [
        key,
        isCredentialKey(key) ? REDACTED_SECRET : sanitizeArtifactValue(entry),
      ]),
    ) as T;
  }
  return value;
}

export function stringifyArtifact(value: unknown): string {
  return `${JSON.stringify(sanitizeArtifactValue(value), null, 2)}\n`;
}

function sanitizeArtifactString(value: string): string {
  const sanitizedUrl = sanitizeHttpUrl(value);
  if (sanitizedUrl !== undefined) {
    return sanitizedUrl;
  }
  return value
    .replace(/\bBearer\s+[^\s,;]+/gi, `Bearer ${REDACTED_SECRET}`)
    .replace(/([?&](?:token|api[_-]?key|access[_-]?token|auth[_-]?token)=)[^&#\s]*/gi, `$1${REDACTED_SECRET}`)
    .replace(/("(?:token|api[_-]?key|access[_-]?token|auth[_-]?token)"\s*:\s*")([^"]*)(")/gi, `$1${REDACTED_SECRET}$3`)
    .replace(/((?:token|api[_-]?key|access[_-]?token|auth[_-]?token)\s*[=:]\s*)([^,\s]+)/gi, `$1${REDACTED_SECRET}`);
}

function sanitizeHttpUrl(value: string): string | undefined {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return undefined;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return undefined;
  }
  parsed.username = "";
  parsed.password = "";
  parsed.search = "";
  parsed.hash = "";
  return parsed.toString();
}

function isCredentialKey(key: string): boolean {
  return CREDENTIAL_KEY_PATTERN.test(key);
}
