# Claude Design Prompt — Control Plane v2 UI

Paste the following into Claude Design to produce the SPA mockups for the Control Plane v2 UI. The prompt is self-contained; Claude Design does not see the vision spec.

---

## Prompt

Design a production-grade SPA frontend for **Maestro Control Plane v2**, a self-hosted multi-host orchestrator that deploys and monitors containerized applications across Linux servers. The product is for technical operators — DevOps engineers, platform engineers, small-team SREs — not end users. Tone: technical, dense-but-legible, operator-grade. Think Grafana meets Vercel meets Portainer, without the generic-AI-dashboard look. No playful illustrations, no gradient blobs, no emoji. Information-first, every pixel earns its place.

### Stack constraints

- React 18 + Vite
- TypeScript
- Tailwind CSS
- shadcn/ui component library (Radix primitives, unstyled accessible components)
- Recharts for time-series graphs
- TanStack Query for data fetching (mock the hooks; do not implement the backend)
- react-hook-form + zod for wizard forms
- Dark mode is the **primary** theme; also provide a light theme. Theme toggle in top-right. No auto-switching — user choice, persisted.

### Product context (enough to design with)

- The CP manages multiple **deploys** (think: named application stacks, like `webapp-prod`, `monitoring-stack`). Each deploy has a version history with rollback.
- Deploys are composed of **components** (containers or systemd services) bound to **nodes** (Linux hosts running a daemon).
- Nodes come in two flavors: **user nodes** (owned by a single user) and **shared nodes** (provided by an organization, admin-granted access).
- Real-time metrics stream to the UI over a WebSocket: host metrics (CPU/RAM/disk/net), per-component metrics (CPU/RAM/uptime/restarts/healthcheck), deploy-level aggregates.
- A **wizard** guides users through creating a new deploy, adding a component, or upgrading a component version. Wizard supports three source types: Docker image, Git repo, uploaded archive.
- Single-user mode is the default; multi-user with ownership/ACL is opt-in. Design for both — login screen exists but a prominent onboarding banner/badge indicates single-user mode when active.

### Screens to produce (in priority order)

**1. Overview (landing page after login)**
Grid of deploy cards. Each card shows: deploy name, owner (if multi-user), health indicator (X/Y components healthy), last apply status (success/failed/in-progress) + timestamp, sparkline of aggregate health over 24h, quick-action menu (apply, wizard, rollback, open detail). Top bar: global stats (total deploys, total components, alerts count, total nodes online/offline). Empty state for first-run: illustrated call-to-action "Create your first deploy" → wizard.

**2. Deploy Detail**
The anchor screen. Left sidebar: list of components with tiny health dot + name + image/source ref. Main area tabs:
- *Components*: expandable rows per component, showing live sparklines (CPU, RAM, request rate or log rate), healthcheck status, placement (which hosts). Click row → right panel drawer with logs tail + full metrics graph panel.
- *Versions*: vertical timeline of versions (v1 → v2 → v3 → ...), each node showing timestamp, diff summary ("+2 components, updated nginx:1.24→1.25"), who applied, success/fail badge, rollback button on non-current versions.
- *Configuration*: raw YAML viewer with syntax highlighting. Edit toggle → Monaco-like editor with validation panel on the side. "Open in wizard" button to restart wizard on this deploy.
- *Metrics*: full-page metrics dashboard — aggregate CPU/RAM/request-rate/error-rate graphs with time-range picker (5m/1h/6h/24h/7d/custom).

Top bar of deploy detail: deploy name + breadcrumb (Overview > Deploy name), status pill (Healthy / Degraded / Failed / Applying), action buttons (Apply, Rollback, Wizard, Delete).

**3. Nodes**
Two-pane view. Left: filterable table of nodes (columns: name, type badge `user`/`shared`, status dot, CPU %, RAM %, disk %, components count, owner). Filter chips at top: All / My nodes / Shared / Online / Offline. Right: when a row is selected, a detail panel with:
- Host metrics panel: CPU/RAM/disk/net graphs, load average.
- Components running here (across all deploys visible to the user) — grouped by deploy, each with health dot.
- Node metadata: OS, kernel, daemon version, labels, uptime.
- If user is owner: "Share node" action opens a modal to grant access to specific users.

**4. Wizard (full-page flow, three entry points)**
Multi-step, each step is a distinct screen with back/next nav and progress indicator (numbered steps, not generic "1/5"). Steps:
1. **Intent**: pick entry point — "New deploy", "Add component to existing deploy", "Upgrade component". If the user came from a deploy-detail page, preselect appropriately.
2. **Source**: radio cards for Docker / Git / Archive. Each card has an icon (use lucide-react icons, not emoji) and a one-line description.
3. **Source details**: conditional on step 2.
   - Docker: image + tag input, with a "Test pull" button that simulates inspecting the image. After success, show detected ports/volumes/env as editable suggestion chips.
   - Git: repo URL, ref, build-steps template dropdown (Dockerfile / npm / pip / go / custom).
   - Archive: drag-drop uploader + progress bar.
4. **Placement**: multi-select of nodes (only shows nodes visible to the user). Strategy radio: Sequential / Parallel / Canary. Depends-on tree editor (visual chain of components).
5. **Runtime**: ports table, volumes table, env vars key-value editor (with "mark as secret" toggle per row), healthcheck block.
6. **Review**: generated YAML on the left with syntax highlight; diff panel on the right showing what will change against the deploy's current version (create/update/remove rows, color-coded green/yellow/red). Actions: Back / Save as Draft / Apply Now.

**5. Login + Single-User Onboarding**
Simple centered card: Maestro logo, username + password fields, submit. Under the card, small text: "Single-user mode? Set up multi-user by running `maestrod setup-admin`." In single-user mode, this screen is not shown.

**6. Admin (visible only to platform admins or org admins)**
Tabs: Users / Organizations / Shared Nodes / Audit. Tables with inline edit for role assignments. Audit is a reverse-chronological event log with filters.

### Design language

- **Typography**: Inter for UI, JetBrains Mono for code/YAML/IDs/hashes. Tight line-heights. Generous letter-spacing only on small caps labels.
- **Density**: compact-ish. Table rows 36-40px tall. Cards breathe but don't waste space. Nothing bouncy.
- **Color**: dark theme as primary — near-black background (not pure `#000`), subtle elevation via border rather than shadow. A single semantic palette: healthy (green-500), degraded (amber-500), failed (red-500), unknown (zinc-500), applying/in-progress (blue-500). Accent color for brand: pick something distinctive — **not** blue-500. Consider a signature color like teal-400 or a warm ochre-300 to stand apart from the Tailwind-default look.
- **Status dots**: 8px, with a soft outer ring in the same hue at 20% opacity when "active" (e.g., applying animates a pulse).
- **Badges**: compact pill with icon + label where possible. Consistent use across lists.
- **Graphs (Recharts)**: no grid noise. Single-series sparklines in card corners (30×100px). Full graphs use a single accent color with a thin area fill. Tooltip on hover, crosshair line, rounded timestamp.
- **Navigation**: left sidebar with icon + label (collapsible to icons only on narrow screens). Top bar: breadcrumb + global actions (theme, user menu). Breadcrumbs are functional (clickable), not decorative.
- **Empty states**: a short line of text + one primary action. No oversized illustrations.
- **Loading**: skeleton rows (not spinners) in tables and card grids. Real-time connection indicator in top bar: a tiny pulsing dot when WS is connected, red static dot when disconnected.
- **Motion**: restrained. Fade-in for route changes, 150ms. Slide for drawers. No hover-bounce, no spring animations beyond Radix defaults.

### Deliverables

- A working React + Vite + Tailwind + shadcn/ui project I can `npm install && npm run dev`.
- All six screens fully mocked with realistic data (hardcoded fixtures in `src/fixtures/`).
- Real-time channels stubbed with a fake WS that replays recorded metric events on a loop.
- Mobile responsive for Overview, Nodes, and Deploy Detail (read-only on mobile is acceptable). Wizard and Admin are desktop-only.
- A `README.md` describing file layout and where to plug in real APIs (replace `src/api/client.ts` mock).

Avoid any generic AI-dashboard tropes: no "Welcome back, [Name]!" greetings, no "Quick Stats" meaningless tiles, no decorative gradients, no random abstract shapes. Make it feel like a serious operator tool you'd trust with production.
