# Soil Temperature & GDD Tracker — Website Tools Design

**Date:** 2026-05-06
**Status:** Approved for implementation

---

## Problem

The Lawn Dominator website markets soil temperature monitoring and GDD tracking as app features but provides nothing interactive for visitors. GreenCast (a Syngenta commercial tool) owns this search space. The opportunity: build better, more turf-specific versions of these tools on the website, stateless and anonymous, to capture search traffic and convert visitors to app downloads.

---

## Goals

1. Rank for queries like "soil temperature lawn care [city]", "GDD calculator bermuda grass", "when to apply pre-emergent [state]".
2. Give visitors genuinely useful data — not just a reason to download the app, but something worth bookmarking.
3. Convert visitors with well-placed app CTAs that are contextually relevant (not generic banners).
4. Stay completely stateless — no accounts, no saved sessions, no personalization. Anything requiring a start date or history stays in the app.

---

## Scope

Two new pages added to the existing GitHub Pages static site:

- `/soil-temperature.html` — Soil Temperature Tracker
- `/gdd-tracker.html` — GDD Calculator

Both share the existing site header, footer, CSS variables, and visual design language. No build system change. Vanilla HTML/CSS/JS + Leaflet.js + Chart.js (CDN) + Open-Meteo API (free, no key, CORS-friendly) + Nominatim geocoding (free, no key).

---

## Data Sources

### Open-Meteo (primary)
- **URL:** `https://api.open-meteo.com/v1/forecast`
- **No API key required.** CORS-friendly for browser requests.
- **Soil temperature fields:** `soil_temperature_0cm`, `soil_temperature_6cm`, `soil_temperature_18cm` (current + 7-day hourly)
- **Historical data (for GDD):** `https://archive-api.open-meteo.com/v1/archive` — daily `temperature_2m_max` and `temperature_2m_min` from Jan 1 of current year to today
- Units: Fahrenheit (`temperature_unit=fahrenheit`)

### Nominatim (geocoding)
- **URL:** `https://nominatim.openstreetmap.org/search`
- **No API key required.** Must set `User-Agent` header. Rate limit: 1 req/sec (fine for user-triggered lookups).
- Returns `lat`, `lon`, `display_name` for a free-text address query.

### Leaflet.js + OpenStreetMap
- Map tiles from OpenStreetMap (free, attribution required).
- Leaflet 1.9.x from CDN.

### Chart.js
- Chart.js 4.x from CDN.

---

## Page 1: Soil Temperature Tracker (`/soil-temperature.html`)

### SEO
- `<title>`: "Soil Temperature Tracker for Lawn Care — Lawn Dominator"
- `<meta description>`: "Check current soil temperature at 2" and 6" depth for your lawn. See a 7-day trend and what the temperature means for bermuda, zoysia, and cool-season grass programs."
- `<h1>`: "Soil Temperature Tracker"
- JSON-LD `WebApplication` structured data pointing to this page.

### Layout (top to bottom)

**1. Location bar**
- Text input: "Enter your address or city"
- "Use my location" button (Geolocation API fallback)
- On submit: geocode via Nominatim → store `{lat, lon, displayName}` → fetch Open-Meteo

**2. Leaflet map**
- Full-width, ~280px tall on mobile / ~360px on desktop
- OpenStreetMap tiles
- Single marker at geocoded coordinates
- Popup on marker: display name + current 2" soil temp

**3. Depth cards (3-column on desktop, stacked on mobile)**

| Card | Open-Meteo field | Label |
|------|-----------------|-------|
| Surface | `soil_temperature_0cm` | Surface |
| 2 inch | `soil_temperature_6cm` | 2" depth |
| 6 inch | `soil_temperature_18cm` | 6" depth |

Each card shows: current reading (large), today's high/low, color-coded badge (blue < 50°F, yellow 50–65°F, green 65–80°F, red > 80°F).

**4. 7-day trend chart**
- Chart.js line chart
- Three lines: Surface, 2", 6" — using 7 days of hourly data averaged to daily
- X-axis: day labels (Mon, Tue…)
- Y-axis: °F
- Legend at top
- Subtle fill under the 2" line (primary color at 10% opacity)

**5. Grass-type pill selector**
Four pills: Bermuda · Zoysia · St. Augustine · Cool-season
Default: Bermuda. Changing the pill updates the interpretation card only (no re-fetch).

**6. Interpretation card**
Plain-English reading of the current 2" soil temperature for the selected grass type. One sentence status + one sentence action.

Bermuda thresholds (2" depth):
- < 50°F: "Bermuda is dormant. Hold all fertilizer, herbicide applications, and PGR. Resume when soil reaches 50°F."
- 50–55°F: "Bermuda is at the pre-emergent window. Apply crabgrass pre-emergent now if you haven't already."
- 55–65°F: "Bermuda is breaking dormancy. Light nitrogen is OK; watch for the first flush of green before resuming a full program."
- 65–80°F: "Bermuda is in active growth. Full fertilizer and PGR program is appropriate."
- > 80°F: "Soil is hot. Avoid elemental sulfur applications. Water stress risk is elevated."

Zoysia thresholds: same breakpoints, adjusted language ("Zoysia breaks dormancy later than bermuda — confirm visual greenup before applying nitrogen.").

St. Augustine thresholds: similar to bermuda but note sensitivity to cold damage and no PGR use in most programs.

Cool-season thresholds: focused on spring/fall ideal ranges (50–65°F), summer dormancy above 80°F, overseed timing.

**7. App CTA strip**
Dark background strip: "Track soil temperature through the full season — get alerts when your lawn hits key thresholds. Available on iPhone."
[App Store button]

---

## Page 2: GDD Calculator (`/gdd-tracker.html`)

### SEO
- `<title>`: "GDD Calculator for Lawns — Growing Degree Days Tracker — Lawn Dominator"
- `<meta description>`: "Calculate growing degree days (GDD) for your lawn from January 1. See where you are in the pre-emergent and greenup windows for bermuda, zoysia, and cool-season grass."
- `<h1>`: "GDD Calculator for Lawns"
- JSON-LD `WebApplication` structured data.

### GDD Calculation

`GDD per day = max(0, ((T_max + T_min) / 2) - T_base)`

- `T_base`: 50°F for all grass types on this page (pre-emergent and seasonal greenup context)
- `T_max` capped at 86°F, `T_min` floored at 50°F (modified growing degree day method used by most extension services)
- Period: Jan 1 of current year → today, using Open-Meteo historical archive daily max/min
- Result: cumulative GDD from Jan 1

> Note: PGR reapplication GDD (base 32°F from application date) requires a personal start date — that stays in the app. The website shows seasonal accumulation only.

### Layout (top to bottom)

**1. Location bar**
Same address input + "Use my location" as soil temp page.

**2. Grass-type pill selector**
Four pills: Bermuda · Zoysia · St. Augustine · Cool-season
Default: Bermuda. Changes milestone labels on chart; does not change base temp (50°F for all).

**3. Current season GDD stat card**
Large number: "847 GDD since Jan 1"
Sub-label: "Base 50°F · [City, State]"

**4. Cumulative GDD chart**
- Chart.js line chart
- Single line: cumulative GDD from Jan 1 to today
- Vertical milestone lines (dashed, labeled):
  - Bermuda: 50 GDD "Pre-emergent window opens", 200 GDD "Greenup approaching", 500 GDD "Full active growth"
  - Zoysia: 100 GDD "Pre-emergent window", 300 GDD "Greenup approaching"
  - St. Augustine: 50 GDD "Pre-emergent window", 200 GDD "First green push"
  - Cool-season: 50 GDD "Spring pre-emergent window", note fall GDD is less relevant
- X-axis: month labels (Jan, Feb, Mar…)
- Y-axis: cumulative GDD

**5. PGR reference table**
Static reference — not personalized. Header: "Common PGR Reapplication Windows (from your application date)".

| Product | Active Ingredient | Base Temp | Reapply At |
|---------|-------------------|-----------|------------|
| Primo Maxx / T-Nex | Trinexapac-ethyl | 32°F | ~200 GDD |
| Anuew | Prohexadione Calcium | 32°F | ~2–3 weeks (shorter residual) |
| Paclobutrazol (Trimmit) | Paclobutrazol | — | 6–8 weeks (soil absorbed, not GDD-tracked) |

> **Implementation note:** Verify GDD base temps and thresholds against product labels and UGA/Penn State extension guidance before publishing. The `gddBase` and `gddReapplyThreshold` fields exist in the app's PGR product data but are unpopulated — populate them as part of this work.

**6. App CTA strip**
"Track your PGR reapplication window from your exact application date — the app calculates your personal countdown. Available on iPhone."
[App Store button]

---

## Shared Components

### Header
Identical to `index.html` header: LD mark, site name, nav links (Why it hits · Tools · Proof · Download), "Get the app" pill. Nav updated to include "Soil Temp" and "GDD" links pointing to the new pages.

### Footer
Identical to `index.html` footer.

### CSS
New styles added to `styles.css`:
- `.tool-page` — page wrapper with consistent max-width and padding
- `.location-bar` — input row with address field + button
- `.depth-cards` — 3-column responsive grid
- `.depth-card` — individual card with color-coded badge
- `.chart-wrap` — Chart.js canvas container
- `.grass-pills` — pill selector row
- `.interpretation-card` — bordered card for turf-specific text
- `.pgr-table` — simple table for PGR reference
- `.cta-strip` — dark-background app download section

### Error States
- Geocoding fails: "Couldn't find that location. Try a city name or zip code."
- Open-Meteo fails: "Weather data unavailable right now. Try again in a moment."
- Geolocation denied: fall back to input field with placeholder "Enter your city or zip"

---

## What Does NOT Change

- `index.html` — no changes to existing content. Nav gets two new links added.
- `styles.css` — new classes appended only, no existing rules touched.
- `privacy-policy.html`, `terms.html`, `robots.txt`, `sitemap.xml` — sitemap updated to include new pages, nothing else.

---

## Out of Scope

- National/regional color-gradient soil temperature map (requires gridded backend data)
- PGR reapplication countdown from personal application date (requires account/state — stays in app)
- ET/watering guidance (deferred to future feature)
- Android app download link (app is iOS only currently)
- Any server-side component — this stays on GitHub Pages, all API calls from browser
