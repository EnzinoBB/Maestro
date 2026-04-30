import { useEffect, useRef } from "react";

type MergeModules = {
  MergeView: typeof import("@codemirror/merge")["MergeView"];
  EditorView: typeof import("@codemirror/view")["EditorView"];
  EditorState: typeof import("@codemirror/state")["EditorState"];
  yaml: typeof import("@codemirror/lang-yaml")["yaml"];
  basicSetup: typeof import("codemirror")["basicSetup"];
};

let cachedMergeModules: Promise<MergeModules> | null = null;
function loadMerge(): Promise<MergeModules> {
  if (cachedMergeModules) return cachedMergeModules;
  cachedMergeModules = Promise.all([
    import("@codemirror/merge"),
    import("@codemirror/view"),
    import("@codemirror/state"),
    import("@codemirror/lang-yaml"),
    import("codemirror"),
  ]).then(([mergeMod, viewMod, stateMod, yamlMod, cmMod]) => ({
    MergeView: mergeMod.MergeView,
    EditorView: viewMod.EditorView,
    EditorState: stateMod.EditorState,
    yaml: yamlMod.yaml,
    basicSetup: cmMod.basicSetup,
  }));
  return cachedMergeModules;
}

export function YamlDiff({
  left,
  right,
  leftLabel,
  rightLabel,
}: {
  left: string;
  right: string;
  leftLabel?: string;
  rightLabel?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    loadMerge().then(mods => {
      if (cancelled || !ref.current) return;
      const exts = [
        mods.basicSetup,
        mods.yaml(),
        mods.EditorState.readOnly.of(true),
        mods.EditorView.theme({
          "&": { fontSize: "12px" },
          ".cm-scroller": { fontFamily: "var(--font-mono)" },
        }),
      ];
      const view = new mods.MergeView({
        a: { doc: left, extensions: exts },
        b: { doc: right, extensions: exts },
        parent: ref.current,
        revertControls: undefined,
        highlightChanges: true,
      });
      viewRef.current = view;
    });
    return () => {
      cancelled = true;
      const v = viewRef.current as { destroy?: () => void } | null;
      v?.destroy?.();
      viewRef.current = null;
    };
  }, [left, right]);

  return (
    <div className="cp-yaml-diff">
      {(leftLabel || rightLabel) && (
        <div className="cp-yaml-diff__labels small dim">
          <span>{leftLabel || "left"}</span>
          <span>{rightLabel || "right"}</span>
        </div>
      )}
      <div ref={ref} className="cp-yaml-diff__view" />
    </div>
  );
}
