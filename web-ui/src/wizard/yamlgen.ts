import type { WizardState } from "./types";

/** Produce the deployment.yaml text for the "new deploy" entry point.
 *  Add-component / upgrade-component go through patchYaml() instead. */
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
  emitComponent(lines, s, cid);

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

/** Patch an existing deploy YAML.
 *
 * - "add-component": insert a new component block + add a deployment binding
 *   on the first selected host (or default to first existing host).
 * - "upgrade-component": replace the source ref of an existing component.
 *
 * Strategy: parse-light (regex) instead of a full YAML parser, because we
 * only mutate well-known anchors. The CP re-parses + validates the result
 * server-side anyway, so any drift surfaces as a diff/apply error. The
 * raw editor stays available for power users who need surgical edits.
 */
export function patchYaml(currentYaml: string, s: WizardState): string {
  if (s.entryPoint === "upgrade-component") {
    return upgradeComponentInYaml(currentYaml, s);
  }
  if (s.entryPoint === "add-component") {
    return addComponentToYaml(currentYaml, s);
  }
  return currentYaml;
}

function upgradeComponentInYaml(yaml: string, s: WizardState): string {
  const cid = s.targetComponentId;
  if (!cid) return yaml;
  // Find "  <cid>:" at indent 2 inside `components:` block.
  // Replace its `source:` line.
  const sourceLine = renderSourceLine(s);
  // Find the component block start and its source: line.
  const re = new RegExp(
    `(\\n  ${escapeRe(cid)}:\\s*\\n(?:[\\s\\S]*?))(\\n    source:\\s*[^\\n]*)`,
    "m",
  );
  if (!re.test(yaml)) {
    // Fall back: append a comment so the user notices the patch failed.
    return yaml + `\n# upgrade-component: could not locate '${cid}' source line\n`;
  }
  return yaml.replace(re, (_m, head: string) => `${head}\n    source: ${sourceLine}`);
}

function addComponentToYaml(yaml: string, s: WizardState): string {
  const cid = s.componentId || "new-component";
  const newCompLines: string[] = [];
  newCompLines.push(`  ${yamlKey(cid)}:`);
  emitComponentBody(newCompLines, s);
  const compBlock = newCompLines.join("\n");

  // Insert the new component before `deployment:` (not at end, because that
  // would land outside the components: mapping in many cases).
  let patched = yaml;
  const compHeader = patched.match(/\ncomponents:\s*\n/);
  const deployHeader = patched.match(/\ndeployment:\s*\n/);
  if (compHeader && deployHeader && deployHeader.index! > compHeader.index!) {
    const insertAt = deployHeader.index!; // before \ndeployment:
    patched = patched.slice(0, insertAt) + "\n" + compBlock + patched.slice(insertAt);
  } else {
    // No components section yet — append both.
    patched += `\ncomponents:\n${compBlock}\n`;
  }

  // Add a deployment binding on the first selected host (or first existing host).
  const targetHost = s.hostIds[0] || extractFirstHostId(yaml);
  if (targetHost) {
    const bindingLines = [
      `  - host: ${yamlStr(targetHost)}`,
      `    components: [${yamlStr(cid)}]`,
    ];
    // Append to deployment list. We cheat: just append at end of file under deployment.
    // The CP validates the result; if structure breaks the user sees an error.
    patched = patched.replace(
      /\ndeployment:\s*\n/,
      `\ndeployment:\n${bindingLines.join("\n")}\n`,
    );
  } else {
    patched += `\n# add-component: no host to bind to — add a deployment binding manually\n`;
  }
  return patched;
}

function extractFirstHostId(yaml: string): string | null {
  const m = yaml.match(/\bhosts:\s*\n[ \t]+([A-Za-z0-9_.-]+)\s*:/);
  return m ? m[1] : null;
}

// ---- emission helpers ----

function emitComponent(lines: string[], s: WizardState, cid: string): void {
  lines.push(`  ${yamlKey(cid)}:`);
  emitComponentBody(lines, s);
}

function emitComponentBody(lines: string[], s: WizardState): void {
  lines.push(`    source: ${renderSourceLine(s)}`);
  lines.push(`    run:`);
  lines.push(`      type: ${s.sourceType === "docker" ? "docker" : "systemd"}`);
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
}

function renderSourceLine(s: WizardState): string {
  switch (s.sourceType) {
    case "docker":
      return `{type: docker, image: ${yamlStr(s.image)}, tag: ${yamlStr(s.tag || "latest")}}`;
    case "git":
      return `{type: git, repo: ${yamlStr(s.repo)}, ref: ${yamlStr(s.ref || "main")}}`;
    case "archive":
      return `{type: archive, path: ${yamlStr(s.archivePath)}}`;
  }
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

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
