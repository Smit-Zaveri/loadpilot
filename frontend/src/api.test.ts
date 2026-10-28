import { describe, expect, it } from "vitest";
import { describeError } from "./api";

describe("describeError", () => {
  it("turns FastAPI validation errors into readable lines", () => {
    const err = describeError(422, {
      detail: [
        { loc: ["body", "load"], msg: "Value error, set 'stages'" },
        { loc: ["body"], msg: "Field required" },
      ],
    });
    expect(err.message).toBe("The test settings aren't valid.");
    expect(err.details).toEqual(["load: Value error, set 'stages'", "Field required"]);
  });

  it("keeps the running run id from a conflict", () => {
    const err = describeError(409, { detail: { message: "another test is already running", run_id: "abc" } });
    expect(err.runId).toBe("abc");
    expect(err.message).toBe("another test is already running");
  });

  it("falls back to the HTTP status", () => {
    expect(describeError(500, null).message).toBe("Request failed (HTTP 500).");
    expect(describeError(404, { detail: "run not found" }).message).toBe("run not found");
  });
});
