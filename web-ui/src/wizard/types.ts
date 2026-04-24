export type WizardState = {
  entryPoint: "new";
  sourceType: "docker";
  deployName: string;
  image: string;
  tag: string;
  hostIds: string[];
  componentId: string;
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
  image: "",
  tag: "latest",
  hostIds: [],
  componentId: "",
  env: [],
  ports: [],
  volumes: [],
  healthcheck: { type: "none" },
  strategy: "sequential",
};

export function defaultComponentId(image: string): string {
  const last = image.split("/").pop() || "";
  return last.replace(/[^a-z0-9-]/g, "").slice(0, 40) || "app";
}
