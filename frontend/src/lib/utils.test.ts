import { describe, expect, it } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
  it("merges conditional, nested and conflicting classes", () => {
    expect(cn("p-2", false, ["p-4"], { hidden: false, block: true })).toBe("p-4 block");
    expect(cn("hover:p-2", "hover:p-4", "p-1")).toBe("hover:p-4 p-1");
  });
});
