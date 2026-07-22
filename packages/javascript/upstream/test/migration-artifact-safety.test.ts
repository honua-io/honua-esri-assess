import { describe, expect, it } from "vitest";
import { sanitizeArtifactValue, stringifyArtifact } from "../src/migration/artifact-safety.js";

describe("migration artifact safety", () => {
  it("removes credentials, every URL query string, and fragments from persisted values", () => {
    const artifact = stringifyArtifact({
      url: "https://user:password@example.test/items?context=innocent-secret#details",
      accessCredential: "credential-value",
      databasePasswd: "password-value",
      clientSecret: "secret-value",
      api_key: "api-key-value",
    });

    expect(JSON.parse(artifact)).toEqual({
      url: "https://example.test/items",
      accessCredential: "[REDACTED]",
      databasePasswd: "[REDACTED]",
      clientSecret: "[REDACTED]",
      api_key: "[REDACTED]",
    });
    expect(artifact).not.toMatch(/password-value|secret-value|api-key-value|innocent-secret|details/);
  });

  it("redacts bearer authorization strings at any nesting depth", () => {
    const sanitized = sanitizeArtifactValue({
      headers: ["Authorization: Bearer bearer-value"],
      nested: { note: "uses bearer another-value; for authentication" },
    });

    expect(sanitized).toEqual({
      headers: ["Authorization: [REDACTED]"],
      nested: { note: "uses Bearer [REDACTED]; for authentication" },
    });
  });
});
