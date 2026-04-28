// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { copyText } from "./clipboard";

type ClipboardMock = { writeText: ReturnType<typeof vi.fn> };

function setSecureContext(value: boolean) {
  Object.defineProperty(window, "isSecureContext", {
    configurable: true,
    get: () => value,
  });
}

function setClipboard(clipboard: ClipboardMock | undefined) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    get: () => clipboard,
  });
}

function mockExecCommand(returnValue: boolean) {
  // jsdom does not implement the (deprecated) document.execCommand, so we
  // install our own. Returning a vi.fn lets tests assert call args.
  const fn = vi.fn((cmd: string) => (cmd === "copy" ? returnValue : false));
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    writable: true,
    value: fn,
  });
  return fn;
}

describe("copyText", () => {
  beforeEach(() => {
    // Default: insecure context with no clipboard API — represents the
    // CP-on-plain-HTTP deploy that the helper must handle.
    setSecureContext(false);
    setClipboard(undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses navigator.clipboard when in a secure context", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setSecureContext(true);
    setClipboard({ writeText });

    const ok = await copyText("hello");

    expect(ok).toBe(true);
    expect(writeText).toHaveBeenCalledWith("hello");
  });

  it("falls back to execCommand when clipboard API is missing (HTTP CP)", async () => {
    // navigator.clipboard is undefined on plain-HTTP non-localhost — exactly
    // the reported failure mode.
    const exec = mockExecCommand(true);

    const ok = await copyText("install-cmd");

    expect(ok).toBe(true);
    expect(exec).toHaveBeenCalledWith("copy");
  });

  it("falls back to execCommand when isSecureContext is false even if clipboard exists", async () => {
    // Some browsers expose navigator.clipboard but reject writeText outside
    // a secure context — guard at the secure-context check.
    const writeText = vi.fn().mockResolvedValue(undefined);
    setSecureContext(false);
    setClipboard({ writeText });
    const exec = mockExecCommand(true);

    const ok = await copyText("payload");

    expect(ok).toBe(true);
    expect(writeText).not.toHaveBeenCalled();
    expect(exec).toHaveBeenCalledWith("copy");
  });

  it("falls back to execCommand when writeText rejects (permissions denied)", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("NotAllowedError"));
    setSecureContext(true);
    setClipboard({ writeText });
    const exec = mockExecCommand(true);

    const ok = await copyText("payload");

    expect(ok).toBe(true);
    expect(writeText).toHaveBeenCalledOnce();
    expect(exec).toHaveBeenCalledWith("copy");
  });

  it("returns false when both the clipboard API and execCommand fail", async () => {
    const exec = mockExecCommand(false);

    const ok = await copyText("payload");

    expect(ok).toBe(false);
    expect(exec).toHaveBeenCalledWith("copy");
  });

  it("removes the temporary textarea from the DOM in the fallback path", async () => {
    mockExecCommand(true);
    const before = document.querySelectorAll("textarea").length;

    await copyText("payload");

    expect(document.querySelectorAll("textarea").length).toBe(before);
  });
});
