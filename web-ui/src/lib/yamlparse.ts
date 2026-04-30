export type ParsedSource =
  | { type: "docker"; image: string; tag?: string }
  | { type: "git"; repo: string; ref?: string }
  | { type: "archive"; path: string }
  | { type: "unknown"; raw: string };

export type ParsedComponent = {
  id: string;
  source: ParsedSource;
  hosts: string[];
};

export type ParsedDeployment = {
  hosts: string[];
  components: ParsedComponent[];
};

const COMMENT_RE = /^[ \t]*#/;

function extractTopLevelBlock(yaml: string, key: string): string | null {
  const re = new RegExp(`(?:^|\\n)${key}:\\s*\\n((?:[ \\t]+\\S.*(?:\\n|$))+)`);
  const m = yaml.match(re);
  return m ? m[1] : null;
}

function extractIndent2Keys(block: string): string[] {
  const ids: string[] = [];
  for (const line of block.split("\n")) {
    if (COMMENT_RE.test(line)) continue;
    const m = line.match(/^[ \t]{2}([A-Za-z0-9_.-]+)\s*:/);
    if (m) ids.push(m[1]);
  }
  return Array.from(new Set(ids));
}

function parseSourceInline(raw: string): ParsedSource {
  const get = (k: string): string | undefined => {
    const m = raw.match(new RegExp(`${k}\\s*:\\s*("([^"]*)"|'([^']*)'|([^,}\\s]+))`));
    if (!m) return undefined;
    return m[2] ?? m[3] ?? m[4];
  };
  const t = get("type");
  if (t === "docker") {
    const image = get("image") ?? "";
    const tag = get("tag");
    return { type: "docker", image, tag };
  }
  if (t === "git") {
    const repo = get("repo") ?? "";
    const ref = get("ref");
    return { type: "git", repo, ref };
  }
  if (t === "archive") {
    return { type: "archive", path: get("path") ?? "" };
  }
  return { type: "unknown", raw };
}

function extractComponentSource(yaml: string, cid: string): ParsedSource {
  // Component block runs from "^  <cid>:" to the next "^  <id>:" (sibling) or
  // to a line not indented with at least 2 spaces (end of components: block).
  const lines = yaml.split("\n");
  let inComps = false;
  let inThisComp = false;
  for (const line of lines) {
    if (/^components:\s*$/.test(line)) { inComps = true; continue; }
    if (!inComps) continue;
    // End of components: block — line not indented with 2+ spaces (and not blank).
    if (line !== "" && !/^[ \t]{2}/.test(line)) break;
    // Sibling component header at indent-2: "  <id>:"
    const sibling = line.match(/^[ \t]{2}([A-Za-z0-9_.-]+)\s*:\s*$/);
    if (sibling) {
      inThisComp = sibling[1] === cid;
      continue;
    }
    if (inThisComp) {
      const m = line.match(/^[ \t]{4}source:\s*(.+)$/);
      if (m) return parseSourceInline(m[1]);
    }
  }
  return { type: "unknown", raw: "" };
}

function extractDeploymentBindings(yaml: string): { host: string; components: string[] }[] {
  const block = extractTopLevelBlock(yaml, "deployment");
  if (!block) return [];
  const out: { host: string; components: string[] }[] = [];
  // Each entry begins with a line "  - host: ...". Capture from each marker
  // up to (but not including) the next marker.
  const re = /(^|\n)  - host:\s*("([^"]+)"|'([^']+)'|([A-Za-z0-9_.-]+))[\s\S]*?(?=(?:\n  - host:)|$)/g;
  // Run against block (no leading deployment: header).
  for (const m of block.matchAll(re)) {
    const host = m[3] ?? m[4] ?? m[5];
    if (!host) continue;
    const entry = m[0];
    const cm = entry.match(/components:\s*\[([^\]]*)\]/);
    const comps: string[] = cm
      ? cm[1].split(",").map(s => s.trim().replace(/^["']|["']$/g, "")).filter(Boolean)
      : [];
    out.push({ host, components: comps });
  }
  return out;
}

export function parseDeployYaml(yaml: string): ParsedDeployment {
  const hostsBlock = extractTopLevelBlock(yaml, "hosts");
  const hosts = hostsBlock ? extractIndent2Keys(hostsBlock) : [];

  const compsBlock = extractTopLevelBlock(yaml, "components");
  const compIds = compsBlock ? extractIndent2Keys(compsBlock) : [];

  const bindings = extractDeploymentBindings(yaml);
  const hostsByComp = new Map<string, Set<string>>();
  for (const b of bindings) {
    for (const cid of b.components) {
      if (!hostsByComp.has(cid)) hostsByComp.set(cid, new Set());
      hostsByComp.get(cid)!.add(b.host);
    }
  }

  const components: ParsedComponent[] = compIds.map(id => ({
    id,
    source: extractComponentSource(yaml, id),
    hosts: Array.from(hostsByComp.get(id) ?? []).sort(),
  }));

  return { hosts, components };
}
