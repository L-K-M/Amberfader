// Shared protocol vectors: every file in protocol/examples named valid-*
// must pass the bundled schema; invalid-* must fail. The Python suite runs
// the identical corpus — drift here means the contract is lying somewhere.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  validateMessage,
  validatePlayerState,
  validateSearchSongsResult,
} from "../../src/protocol/validate";

const EXAMPLES = join(__dirname, "../../../protocol/examples");
const files = readdirSync(EXAMPLES).filter((f) => f.endsWith(".json")).sort();

function load(name: string): unknown {
  return JSON.parse(readFileSync(join(EXAMPLES, name), "utf8"));
}

describe("shared example vectors", () => {
  it("corpus is non-trivial", () => {
    expect(files.length).toBeGreaterThanOrEqual(20);
    expect(files.some((f) => f.startsWith("invalid-"))).toBe(true);
  });

  for (const f of files.filter((x) => x.startsWith("valid-"))) {
    it(`${f} validates`, () => {
      const msg = load(f);
      expect(validateMessage(msg), `expected ${f} to validate`).toBe(true);
    });
  }

  for (const f of files.filter((x) => x.startsWith("invalid-"))) {
    it(`${f} is rejected`, () => {
      expect(validateMessage(load(f))).toBe(false);
    });
  }
});

describe("def validators", () => {
  it("valid-response-state's result is a PlayerState", () => {
    const msg = load("valid-response-state.json") as { result: unknown };
    expect(validatePlayerState(msg.result)).toBe(true);
  });
  it("valid-response-search's result is a SearchSongsResult", () => {
    const msg = load("valid-response-search.json") as { result: unknown };
    expect(validateSearchSongsResult(msg.result)).toBe(true);
  });
  it("non-finite numbers are impossible to smuggle (schema + JSON)", () => {
    expect(
      validatePlayerState({
        bindingToken: "t",
        revision: 1,
        track: null,
        status: "playing",
        contentKind: "track",
        positionSeconds: Number.NaN,
        durationSeconds: 1,
        playbackRate: 1,
        volume: 0.5,
        muted: false,
        capabilities: [],
      }),
    ).toBe(false);
  });
});
