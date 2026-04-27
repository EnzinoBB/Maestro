# Maestro Control Plane — UX additions for v0.2.x (Claude Design brief)

This is a follow-up brief to the original [v2 design prompt](2026-04-24-control-plane-v2-claude-design-prompt.md). The base design exists, has shipped, and the user has been operating it. This brief asks you to **design only the new screens / panels / components needed to close three concrete UX gaps**, while staying inside the existing design system (dark teal, Inter / JetBrains Mono, dense-but-readable, no decorative SVGs).

**Output expected**: HTML/CSS/JS handoff bundle (same format as the original) with one `Maestro Control Plane v0.2.x — UX additions.html` entry point, mocking only the screens / panels enumerated below. Do NOT redesign the existing screens.

---

## Design system recap (DO NOT change)

- **Stack**: React 18 + Tailwind-friendly CSS (the existing project uses CSS variables in `src/styles.css`, not Tailwind utility classes — match that pattern)
- **Accent**: `oklch(0.78 0.14 180)` (teal). Never `blue-500`.
- **Type**: Inter for UI, JetBrains Mono for ids / hashes / commands / timestamps
- **Status semantics**: ok / warn / err / info / muted. `applying` pulses; others static.
- **Density**: rows ~38px, cards padded 14–16px, base 13px
- **Motion**: 150ms fade for content, slide for drawers, pulse for live indicators. No spring, no bounce.

You can see the full token set in `src/styles.css` of the original handoff.

---

## Gap 1 — User management (admin)

The Admin screen today has Users + Organizations tables (no create form for users). Operators have no way to add a second user from the UI; the only path is the API. Design what happens when an admin clicks **+ Add user** and what the entry looks like in the table.

### What to design

**1.1 — Admin > Users table augmented**
- Same table shell as existing Admin screen
- A primary button **+ Add user** in the section header (top right of the Users table block)
- Each row gets a contextual menu (the existing `Icons.more` 3-dot button) with: "Reset password" (admin-side, sets a new password the admin reads on screen), "Delete user" (M7.5)
- The `singleuser` row should NOT have any actions (it's a fixture; show its row label as italic + dim with a small badge "system")

**1.2 — Add User dialog/drawer**
- Two layout candidates — design BOTH and we'll pick:
  - **Candidate A**: inline expand of the section (matches the Wizard pattern)
  - **Candidate B**: right-side drawer (matches the existing `cp-drawer` primitive)
- Fields:
  - Username (mono input, dns-1123 hint below)
  - Email (optional)
  - Password (with show/hide toggle, 8+ char counter, common-pattern strength meter — green/amber/red)
  - "Send password to user via …" — out of scope today; show a disabled tooltip "available in v0.3"
  - Toggle: "Make this user an admin" (off by default)
- Footer: Cancel | Create user (primary teal)
- After submit success: dialog closes, new row appears in the table with a 1.5s subtle highlight

**1.3 — Empty state for the Users table**
The table is never truly empty (singleuser is always there). Design what happens when ONLY singleuser exists: show a small inline hint card under the row: "You're the only user. Click + Add user to invite collaborators."

---

## Gap 2 — Change own password

Today there's no UI for a user to change their own password — only the API endpoint. The natural place is under the topbar UserMenu (the `admin × ☼` group on the right of the topbar).

### What to design

**2.1 — UserMenu becomes a popover**
Currently the UserMenu shows just the username + a logout `×` button. Replace with:
- The username remains visible (with the existing `(single-user)` qualifier when applicable)
- Clicking it opens a **small popover** below, anchored right
- Popover entries (in this order):
  - User identity block (username + role badge + email if set)
  - Divider
  - **Change password** — opens dialog 2.2
  - **Switch user** — calls logout + redirects to /login (same as logout but with a clearer label for non-experts; show a confirm dialog: "Sign out and return to login? Other users on this CP can sign in here.")
  - **Sign out** — current behaviour
- Single-user mode: only "Identity block" + a hint "Multi-user is off — set MAESTRO_SINGLE_USER_MODE=false to enable login"

**2.2 — Change password dialog**
- Centered modal (max 420px wide)
- Fields: Current password, New password (with strength meter), Confirm new password
- Submit: green "Change password"
- After success: green inline "Password changed. You stay signed in on this device."
- Errors: red inline (e.g. "Current password is wrong")

---

## Gap 3 — Refinement of daemon-enroll (already shipped, but rough)

We already shipped a working `+ Enroll new daemon` panel in v0.2.6 on the Nodes screen — see the live URL below. It's functional but ad-hoc; we'd like a proper design pass before users see it widely.

### What to design

**3.1 — Refactor the enroll panel into a step-flow drawer**
- Convert the inline panel to a right-side drawer (consistent with M7.1 candidate B)
- Stepper (compact, top of drawer):
  1. Identity (host_id input + optional friendly label)
  2. Target OS (Linux + macOS radio cards; unsupported OS shows greyed)
  3. Reveal command (the prebuilt curl|bash, copy button, "Show as docker run" alternative for Docker-targeted hosts)
  4. Watch (a live indicator that polls `/api/nodes` every 3s and highlights the new row when it appears, then auto-closes the drawer with a green confirmation toast "host-N is now connected")
- Token rotation hint at the bottom: "If a previous enroll command was leaked, you can rotate the daemon token (M6.5 — coming)" — show as disabled link

**3.2 — Empty Nodes state CTA**
The current empty state shows the enroll button. Add a friendlier explanation: a short paragraph "Maestro daemons are tiny Go binaries (~12MB) you install on the hosts you want to manage. Each daemon connects back here over WebSocket. No inbound ports needed on the daemon side."

---

## Bonus (nice to have, not blocking)

**B.1 — Topbar redesign on narrow viewports**
On <768px the topbar today crams everything into a row that overflows. Ticker + UserMenu + theme toggle wrap awkwardly. Design how the right cluster collapses (e.g. UserMenu collapses to just an avatar circle; ticker hides; theme toggle moves into UserMenu popover).

**B.2 — First-run setup polish**
The setup-admin form today is a generic "Create your admin" with username + email + password + confirm. Consider adding a brief illustrated welcome above the form ("Welcome to Maestro. This is the first time anyone's logged in. Create the operator account that will own this Control Plane.")

---

## Reference URLs the designer can probe

- Live system: http://109.199.123.26:8000/ (multi-user, admin already created — ask for the test password to log in if needed)
- Existing screens to NOT redesign: Overview, Deploy detail, Deploy metrics, Wizard, Login, Admin (only the Users-table block is in scope for redesign)
- Original v2 handoff: `.worktrees/cp-dashboard/control-plane/project/` (the source-of-truth for primitives + tokens you should match)

## Deliverable format

Same as the original handoff:
- One `Maestro Control Plane v0.2.x — UX additions.html` entry
- `src/screens/admin-users-add.jsx`, `src/screens/user-menu-popover.jsx`, `src/screens/change-password-dialog.jsx`, `src/screens/enroll-drawer.jsx`
- Reuse `primitives.jsx` from the original handoff where possible (Button, Pill, Mono, Drawer, Dialog, Stepper). If a primitive is missing, add it and document the addition.

When you're done, hand back the bundle and we'll port it into the live `web-ui/` Vite project the same way we did for the v1 design.
