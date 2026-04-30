import { useEffect, useRef, useState } from "react";

type CmModules = {
  EditorView: typeof import("@codemirror/view")["EditorView"];
  EditorState: typeof import("@codemirror/state")["EditorState"];
  yaml: typeof import("@codemirror/lang-yaml")["yaml"];
  basicSetup: typeof import("codemirror")["basicSetup"];
};

let cachedModules: Promise<CmModules> | null = null;
function loadCm(): Promise<CmModules> {
  if (cachedModules) return cachedModules;
  cachedModules = Promise.all([
    import("@codemirror/view"),
    import("@codemirror/state"),
    import("@codemirror/lang-yaml"),
    import("codemirror"),
  ]).then(([viewMod, stateMod, yamlMod, cmMod]) => ({
    EditorView: viewMod.EditorView,
    EditorState: stateMod.EditorState,
    yaml: yamlMod.yaml,
    basicSetup: cmMod.basicSetup,
  }));
  return cachedModules;
}

export function YamlEditor({
  value,
  readOnly,
  onChange,
}: {
  value: string;
  readOnly: boolean;
  onChange?: (v: string) => void;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<unknown>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadCm().then(mods => {
      if (cancelled || !hostRef.current) return;
      const exts = [
        mods.basicSetup,
        mods.yaml(),
        mods.EditorView.theme({
          "&": { fontSize: "12px", height: "100%", minHeight: "300px" },
          ".cm-scroller": { fontFamily: "var(--font-mono)" },
        }),
        mods.EditorState.readOnly.of(readOnly),
        mods.EditorView.updateListener.of(u => {
          if (u.docChanged && onChangeRef.current) {
            onChangeRef.current(u.state.doc.toString());
          }
        }),
      ];
      const view = new mods.EditorView({
        parent: hostRef.current,
        state: mods.EditorState.create({ doc: value, extensions: exts }),
      });
      viewRef.current = view;
      setReady(true);
    });
    return () => {
      cancelled = true;
      const v = viewRef.current as { destroy?: () => void } | null;
      v?.destroy?.();
      viewRef.current = null;
      setReady(false);
    };
    // Re-mount when readOnly flips so the extension list rebuilds.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly]);

  useEffect(() => {
    const v = viewRef.current as
      | { state: { doc: { toString(): string; length: number } }; dispatch: (tr: unknown) => void }
      | null;
    if (!v || !ready) return;
    const cur = v.state.doc.toString();
    if (cur !== value) {
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
    }
  }, [value, ready]);

  return <div ref={hostRef} className="cp-yaml-editor" />;
}
