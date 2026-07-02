# 🌍 Terra Signals — Environment & Climate Trends

A visual dashboard that gathers key **climate and environment trends** and presents
them as clean, accessible charts. It fetches live data from public sources on
demand, and always falls back to a bundled reference snapshot so the dashboard
renders even offline or when a source is rate-limited.

Built with **React + Vite + Recharts**. No backend, no API keys — every live pull
happens in the browser.

![sections: Overview · Climate · Business & nature](docs/preview.png)

---

## Features

- **Three sections**
  - **Overview** — headline stat tiles + key charts at a glance.
  - **Climate** — global temperature, CO₂, methane, emissions, sea level, Arctic
    sea ice, the electricity mix, and climate-related disasters.
  - **Business & nature** — carbon pricing (EU ETS), energy-transition investment,
    falling clean-tech costs, emissions by sector, net-zero target coverage,
    natural-catastrophe losses (climate risk), tree-cover loss, and the Living
    Planet Index (natural capital).
- **Refresh on call** — a **Refresh** button re-pulls live data on demand, plus an
  optional **auto-refresh** interval (1 / 5 / 15 / 30 min).
- **Live + cached fallback** — each panel is labelled **Live**, **Cached** (a live
  fetch was attempted but failed, so the snapshot is shown), or **Reference** (no
  live feed is wired for that metric yet — the snapshot is the source). A status
  bar summarises provenance and shows the last-updated time.
- **Light & dark mode** — follows your OS by default; toggle to override. Charts
  re-theme automatically.
- **Accessible, consistent charts** — a validated colour palette (colourblind-safe
  ordering), legends for every multi-series chart, direct value labels, hover
  tooltips, and source links on every panel.

---

## Getting started

```bash
npm install
npm run dev       # local dev server (http://localhost:5173)
npm run build     # production build → dist/
npm run preview   # preview the production build
```

The build is fully static — deploy `dist/` to any static host (GitHub Pages,
Netlify, Vercel, S3, …). `vite.config.js` uses a relative `base` so it works from
a sub-path without extra config.

---

## Data sources

Live pulls are best-effort and depend on the browser reaching each host (and its
CORS policy). When a pull fails, the bundled snapshot is used automatically.

| Metric | Live source | Fallback |
|---|---|---|
| Global temperature anomaly | Our World in Data (grapher CSV) | NASA GISTEMP snapshot |
| Atmospheric CO₂ | NOAA Global Monitoring Laboratory | NOAA snapshot |
| Atmospheric methane | NOAA Global Monitoring Laboratory | NOAA snapshot |
| Global CO₂ emissions | World Bank Open Data API | Global Carbon Project snapshot |
| Sea level, Arctic ice, electricity mix, disasters, and all Business & nature metrics | *reference snapshot* | NSIDC · Ember · EM-DAT · EU ETS · BloombergNEF · IRENA · Climate Watch · Swiss Re · Global Forest Watch · WWF |

All snapshot figures reflect full-year values through **2024** (with early-2025
readings where noted) and are documented in `src/data/snapshots.js`. They are
indicative — cite the linked primary source for any reporting.

### Adding a metric

1. Add a dataset to `src/data/snapshots.js` (title, unit, source, `series`).
2. *(Optional)* add a live fetcher in `src/lib/fetchers.js` and register it in
   `FETCHERS`.
3. Add a panel entry to `src/data/sections.js`.

---

## Project structure

```
src/
  data/
    snapshots.js     # bundled reference datasets (the offline fallback)
    sections.js      # tabs → panels → chart form (declarative layout)
  lib/
    fetchers.js      # live fetchers (NOAA / World Bank / OWID) + fallback logic
    csv.js           # minimal CSV parsing
    format.js        # number / date formatting
  hooks/
    useClimateData.js  # data store, refresh, auto-interval, live/cached status
  components/
    TrendChart.jsx     # one chart component (line/area/bar/stacked/multiline/hbar)
    Panel.jsx, StatTile.jsx, Legend.jsx, ChartTooltip.jsx
    RefreshControls.jsx, StatusBar.jsx, ThemeToggle.jsx
  styles/
    theme.css        # design tokens (validated palette, light + dark)
    app.css          # layout
  App.jsx            # shell: header, tabs, sections
```

---

## Notes & limitations

- This is a client-only app; live sources must send permissive CORS headers to be
  reachable from the browser. Where they don't, you'll see **Cached** — the data is
  still shown, just from the bundled snapshot.
- Figures are for visualisation and situational awareness, not authoritative
  reporting. Always cite the primary source (linked on each panel).
