import { Icons } from "../primitives";

export function StubScreen({ title, milestone }: { title: string; milestone?: string }) {
  return (
    <div className="cp-page">
      <h1>{title}</h1>
      <div className="cp-empty" style={{ marginTop: 24 }}>
        <Icons.wizard size={24} />
        <h2 style={{ marginTop: 10 }}>Coming in {milestone ?? "a later milestone"}</h2>
        <p>This screen is scaffolded in the shell but the backing APIs are not yet implemented.</p>
      </div>
    </div>
  );
}
