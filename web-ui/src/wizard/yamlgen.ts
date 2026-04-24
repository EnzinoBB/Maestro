import type { WizardState } from "./types";

/** Produce the deployment.yaml text for a "new deploy, docker source" flow. */
export function generateYaml(s: WizardState): string {
  const lines: string[] = [];
  lines.push(`api_version: maestro/v1`);
  lines.push(`project: ${yamlStr(s.deployName || s.componentId || "app")}`);

  lines.push(`hosts:`);
  for (const h of s.hostIds) {
    lines.push(`  ${yamlKey(h)}: {type: linux, address: ${yamlStr(h)}}`);
  }
  if (s.hostIds.length === 0) {
    lines.push(`  # no hosts selected yet`);
  }

  const cid = s.componentId || "app";
  lines.push(`components:`);
  lines.push(`  ${yamlKey(cid)}:`);
  lines.push(`    source: {type: docker, image: ${yamlStr(s.image)}, tag: ${yamlStr(s.tag || "latest")}}`);
  lines.push(`    run:`);
  lines.push(`      type: docker`);
  if (s.ports.length > 0) {
    lines.push(`      ports: [${s.ports.map(yamlStr).join(", ")}]`);
  }
  if (s.volumes.length > 0) {
    lines.push(`      volumes: [${s.volumes.map(yamlStr).join(", ")}]`);
  }
  if (s.env.length > 0) {
    lines.push(`      env:`);
    for (const { key, value } of s.env) {
      if (!key) continue;
      lines.push(`        ${yamlKey(key)}: ${yamlStr(value)}`);
    }
  }
  if (s.healthcheck.type === "http") {
    lines.push(`    healthcheck:`);
    lines.push(`      type: http`);
    lines.push(`      url: ${yamlStr(s.healthcheck.url)}`);
    lines.push(`      expect_status: ${s.healthcheck.expectStatus}`);
  }

  lines.push(`deployment:`);
  if (s.hostIds.length === 0) {
    lines.push(`  # bind to a host once selected`);
  } else {
    for (const h of s.hostIds) {
      lines.push(`  - host: ${yamlStr(h)}`);
      lines.push(`    components: [${yamlStr(cid)}]`);
      if (s.hostIds.length > 1 && s.strategy !== "sequential") {
        lines.push(`    strategy: ${s.strategy}`);
      }
    }
  }

  return lines.join("\n") + "\n";
}

function yamlStr(v: string): string {
  if (v === "" || v == null) return '""';
  if (/^-?\d+(\.\d+)?$/.test(v) || /^(true|false|null|yes|no)$/i.test(v)) {
    return `"${v}"`;
  }
  if (/[:#{}[\],&*!|>'"%@`\n]/.test(v) || /^\s/.test(v) || /\s$/.test(v)) {
    return JSON.stringify(v);
  }
  return v;
}

function yamlKey(k: string): string {
  if (/^[A-Za-z0-9_.-]+$/.test(k)) return k;
  return JSON.stringify(k);
}
