export type EntryPoint = "new" | "add-component" | "upgrade-component";
export type SourceType = "docker" | "git" | "archive";

export type WizardState = {
  entryPoint: EntryPoint;
  /** Required for add-component / upgrade-component: the deploy we're modifying. */
  targetDeployId?: string;
  /** Required for upgrade-component: the existing component to bump. */
  targetComponentId?: string;

  sourceType: SourceType;

  // Common
  deployName: string;
  componentId: string;

  // Docker source
  image: string;
  tag: string;

  // Git source
  repo: string;
  ref: string;

  // Archive source — uploaded out-of-band; wizard only references the path.
  archivePath: string;

  // Placement & runtime (used by 'new' and 'add-component'; ignored on
  // upgrade since the placement is already in the existing YAML).
  hostIds: string[];
  env: { key: string; value: string }[];
  ports: string[];
  volumes: string[];
  healthcheck:
    | { type: "none" }
    | { type: "http"; url: string; expectStatus: number };
  strategy: "sequential" | "parallel" | "canary";
};

export const initialWizardState: WizardState = {
  entryPoint: "new",
  sourceType: "docker",
  deployName: "",
  componentId: "",
  image: "",
  tag: "latest",
  repo: "",
  ref: "main",
  archivePath: "",
  hostIds: [],
  env: [],
  ports: [],
  volumes: [],
  healthcheck: { type: "none" },
  strategy: "sequential",
};

export function defaultComponentId(s: WizardState): string {
  if (s.sourceType === "docker" && s.image) {
    return s.image.split("/").pop()!.replace(/[^a-z0-9-]/g, "").slice(0, 40) || "app";
  }
  if (s.sourceType === "git" && s.repo) {
    const tail = s.repo.replace(/\.git$/i, "").split("/").pop() || "";
    return tail.replace(/[^a-z0-9-]/g, "").slice(0, 40) || "app";
  }
  if (s.sourceType === "archive" && s.archivePath) {
    const tail = s.archivePath.split(/[\\/]/).pop() || "";
    return tail.replace(/\.[^.]+$/, "").replace(/[^a-z0-9-]/g, "").slice(0, 40) || "app";
  }
  return "app";
}
