import { describe, expect, it } from "vitest";
import {
  formatAxisMs,
  formatAxisNumber,
  formatAxisPercent,
  formatBytes,
  formatClock,
  formatMs,
  formatPercent,
  formatRate,
} from "./format";

describe("format", () => {
  it("formats milliseconds with sensible precision", () => {
    expect(formatMs(0.42)).toBe("0.42 ms");
    expect(formatMs(12.34)).toBe("12.3 ms");
    expect(formatMs(250.4)).toBe("250 ms");
    expect(formatMs(1234)).toBe("1.23 s");
    expect(formatMs(Number.NaN)).toBe("–");
  });

  it("formats rates and percentages", () => {
    expect(formatRate(9.87)).toBe("9.9");
    expect(formatRate(1234.5)).toBe("1,235");
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(0.00001)).toBe("<0.01%");
    expect(formatPercent(0.0123)).toBe("1.23%");
    expect(formatPercent(0.5)).toBe("50.0%");
  });

  it("formats clock times", () => {
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(65.9)).toBe("1:05");
    expect(formatClock(3725)).toBe("1:02:05");
    expect(formatClock(-3)).toBe("0:00");
  });

  it("formats axis ticks compactly", () => {
    expect(formatAxisMs(0)).toBe("0");
    expect(formatAxisMs(50)).toBe("50 ms");
    expect(formatAxisMs(2.5)).toBe("2.5 ms");
    expect(formatAxisMs(1500)).toBe("1.5 s");
    expect(formatAxisPercent(0)).toBe("0%");
    expect(formatAxisPercent(0.25)).toBe("0.25%");
    expect(formatAxisPercent(12)).toBe("12%");
    expect(formatAxisNumber(50)).toBe("50");
    expect(formatAxisNumber(2.5)).toBe("2.5");
    expect(formatAxisNumber(1200)).toBe("1,200");
  });

  it("formats bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 ** 2)).toBe("5.0 MB");
  });
});
