import { describe, it, expect } from "vitest";
import { parseDeployYaml } from "./yamlparse";

const SAMPLE = `api_version: maestro/v1
project: demo
hosts:
  host1: {type: linux, address: "10.0.0.1"}
  host2: {type: linux, address: "10.0.0.2"}
components:
  api:
    source: {type: docker, image: "ghcr.io/x/api", tag: "1.4.2"}
    run:
      type: docker
      ports: ["8080:8080"]
  worker:
    source: {type: git, repo: "https://github.com/x/worker.git", ref: "main"}
    run:
      type: systemd
deployment:
  - host: host1
    components: [api]
  - host: host2
    components: [worker, api]
`;

describe("parseDeployYaml", () => {
  it("extracts host ids from a flat hosts mapping", () => {
    const r = parseDeployYaml(SAMPLE);
    expect(r.hosts.sort()).toEqual(["host1", "host2"]);
  });

  it("extracts component ids", () => {
    const r = parseDeployYaml(SAMPLE);
    expect(r.components.map(c => c.id).sort()).toEqual(["api", "worker"]);
  });

  it("derives docker source summary as image:tag", () => {
    const c = parseDeployYaml(SAMPLE).components.find(c => c.id === "api")!;
    expect(c.source).toEqual({ type: "docker", image: "ghcr.io/x/api", tag: "1.4.2" });
  });

  it("derives git source summary as repo@ref", () => {
    const c = parseDeployYaml(SAMPLE).components.find(c => c.id === "worker")!;
    expect(c.source).toEqual({ type: "git", repo: "https://github.com/x/worker.git", ref: "main" });
  });

  it("collects host bindings per component from deployment[]", () => {
    const r = parseDeployYaml(SAMPLE);
    const api = r.components.find(c => c.id === "api")!;
    const worker = r.components.find(c => c.id === "worker")!;
    expect(api.hosts.sort()).toEqual(["host1", "host2"]);
    expect(worker.hosts).toEqual(["host2"]);
  });

  it("returns empty arrays for an empty/blank YAML", () => {
    const r = parseDeployYaml("");
    expect(r.hosts).toEqual([]);
    expect(r.components).toEqual([]);
  });

  it("tolerates a YAML with no deployment block", () => {
    const r = parseDeployYaml(`hosts:\n  h: {}\ncomponents:\n  c:\n    source: {type: archive, path: "./a.tar.gz"}\n`);
    expect(r.components).toHaveLength(1);
    expect(r.components[0].source).toEqual({ type: "archive", path: "./a.tar.gz" });
    expect(r.components[0].hosts).toEqual([]);
  });

  it("keeps source.type='unknown' when the source line is malformed", () => {
    const r = parseDeployYaml(`components:\n  c:\n    source: {type: weird}\n`);
    expect(r.components[0].source.type).toBe("unknown");
  });

  it("ignores commented-out lines (basic guard)", () => {
    const r = parseDeployYaml(`hosts:\n  # h-disabled: {}\n  h-real: {}\n`);
    expect(r.hosts).toEqual(["h-real"]);
  });
});
