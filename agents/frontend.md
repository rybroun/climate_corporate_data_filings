# Agent: Frontend

## Role

Build the Next.js application that implements the three-screen flow from the design handoff. You consume the backend API and present emissions data with pixel-perfect fidelity to the prototype.

## Tech Stack

- **Next.js 14+** (App Router)
- **React 18**
- **TypeScript**
- **CSS Modules** or **Tailwind CSS** (TBD — either works, but tokens must match the design handoff exactly)
- **Google Fonts:** Inter Tight, Inter, JetBrains Mono

## Responsibilities

### Screen Implementation (priority 1)

Implement all three screens from `design_handoff_company_carbon_lookup/README.md`. The prototype in that directory is the visual spec — match it pixel-perfectly. It is *not* production code to copy; rebuild using Next.js patterns.

**Screen 1: Home** (`/`)
- Top bar with brand mark and prototype pill
- Hero H1 + sub
- Search bar with live autocomplete
  - `GET /api/search?q={query}` on input change (debounce 150ms)
  - Dropdown shows up to 5 candidates with logo initial, name, ticker/domain, match score
  - Enter key or "Resolve" button submits
- Search hint with kbd pill
- Pipeline card (7 steps, all idle)
- Sample company grid (3 columns, 6 cards)
  - Cards show source-type tags (CDP, SUST, filing, SEC, news), company name, description, domain, ticker
  - Click triggers resolve flow

**Screen 2: Searching** (`/resolve/[jobId]`)
- H1 with company name in `--forest`
- Status chip with spinner
- Pipeline card with real-time step progression
  - Connect to SSE: `GET /api/resolve/{job_id}/stream`
  - Each SSE `step` event advances the pipeline visualization
  - Steps transition: idle → active (pulsing dot, forest border) → done (moss dot, sage bg)
- Live worker log (black terminal panel)
  - Append `log_line` from each SSE event
  - Trailing spinner while pipeline is running
  - Max height 220px, overflow hidden (newest at bottom)
- On `complete` event: 300ms settle, then navigate to Results

**Screen 3: Results** (`/company/[companyId]`)
- Back link → Home
- Result header: logo tile, name, meta, chips, confidence card
- Headline card: total emissions (72px number), YoY delta, intensity metrics
- Results grid: scope breakdown card + trend card
- Sources card: list of cited documents with verification badges

Data fetching (parallel on page load):
- `GET /api/company/{companyId}/emissions?year=latest`
- `GET /api/company/{companyId}/trend?from=2018&to=2024`
- `GET /api/company/{companyId}/sources`

### Design System (priority 1)

Extract all design tokens from `design_handoff_company_carbon_lookup/styles.css` into your styling approach:

```
Colors:     --bg, --surface, --ink (4 levels), --line (2 levels), --forest, --moss, --sage-bg, --amber, --rust
            Tag colors: filing, cdp, sec, news, sust (each has -bg and -ink)
Typography: --font-sans (Inter Tight), --font-body (Inter), --font-mono (JetBrains Mono)
Spacing:    Max-width 1180px, 32px padding, cards 24px internal
Radii:      6px / 10px / 14px
Shadows:    --shadow-card (hairline), --shadow-pop (hover/dropdown)
Motion:     120-200ms transitions, 0.8s spinner, 1.2s pulse on active dots
```

### Charts (priority 2)

Two chart types for the trend card, rendered as inline SVG (no charting library):

1. **Stacked bar chart** (default): bars per year with Scope 1/2/3 segments, total label above each bar
2. **Line chart** (toggle): area fill + total line + dashed S3 line + dots

Both share: 5 horizontal gridlines (0/25/50/75/100%), mono axis labels, year labels below. Legend beneath chart. See `StackedChart` and `LineChart` components in `app.jsx` for exact geometry.

The chart style toggle should be a simple UI control on the trend card (not a global settings panel — drop the Tweaks panel from the prototype).

### SSE Integration (priority 2)

```typescript
// Connect to pipeline SSE
const eventSource = new EventSource(`/api/resolve/${jobId}/stream`);

eventSource.addEventListener('step', (e) => {
  const data = JSON.parse(e.data);
  // Update pipeline step state
  // Append log line to worker log
});

eventSource.addEventListener('complete', (e) => {
  const data = JSON.parse(e.data);
  // Navigate to results after 300ms settle
  eventSource.close();
});

eventSource.addEventListener('error', (e) => {
  // Show error state
  eventSource.close();
});
```

### State Management (priority 2)

Minimal — no Redux or Zustand needed:

- **Home:** `query` string, `focused` boolean, `suggestions` array (derived from API)
- **Searching:** `stepIdx` number, `logLines` string array (driven by SSE events)
- **Results:** API response data (fetch on mount)
- **Navigation state:** Next.js router handles screen transitions

Persist current view to `localStorage` under `ccl_state` so refresh preserves position (same as prototype).

## Key Constraints

- **Do not copy the prototype code.** It uses Babel-in-browser and inline everything. Rebuild with Next.js App Router, proper component files, and your chosen CSS approach.
- **Drop the Tweaks panel** and the `__edit_mode_*` postMessage plumbing. Chart style toggle stays as a regular UI control.
- **Drop the `density` tweak.** Only `comfortable` density.
- **Prototype data fallback:** While the backend is being built, the frontend should work with the hardcoded `SAMPLES` and `EMISSIONS_DATA` from `app.jsx` as a fallback. Gate this behind an environment variable (`NEXT_PUBLIC_USE_MOCK_DATA=true`).
- **Logo tiles:** Use the initial-on-black treatment from the prototype. In future, swap for real logos via Clearbit or similar.

## Interfaces With Other Agents

- **Backend agent** provides the API. Endpoint shapes are defined in `requirements.md` §4. If you need a field the spec doesn't include, coordinate with the backend agent rather than adding frontend-only derivation.
- **Database agent** — no direct interface. All data comes through the backend API.

## Reference Documents

- `design_handoff_company_carbon_lookup/README.md` — authoritative visual spec
- `design_handoff_company_carbon_lookup/styles.css` — all design tokens
- `design_handoff_company_carbon_lookup/app.jsx` — component structure, sample data fixtures, chart geometry
- `requirements.md` — API contracts, data derivation rules
