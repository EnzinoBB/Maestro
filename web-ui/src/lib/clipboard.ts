/**
 * Copy text to the clipboard with a fallback for non-secure contexts.
 *
 * `navigator.clipboard` is gated to secure contexts. The CP is commonly
 * self-hosted on plain HTTP at a non-localhost address, where the API is
 * unavailable and any call throws — so we fall back to the legacy
 * `<textarea>` + `execCommand('copy')` path. Returns `true` on success.
 */
export async function copyText(text: string): Promise<boolean> {
  if (
    typeof navigator !== "undefined" &&
    navigator.clipboard &&
    typeof window !== "undefined" &&
    window.isSecureContext
  ) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // fall through to legacy path
    }
  }
  return legacyCopy(text);
}

function legacyCopy(text: string): boolean {
  if (typeof document === "undefined") return false;
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.top = "0";
  ta.style.left = "0";
  ta.style.width = "1px";
  ta.style.height = "1px";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  const prevSelection = document.getSelection()?.rangeCount
    ? document.getSelection()!.getRangeAt(0)
    : null;
  ta.focus();
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  if (prevSelection) {
    const sel = document.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(prevSelection);
  }
  return ok;
}
