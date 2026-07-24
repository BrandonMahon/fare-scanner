# Fare Scanner

Trip-based daily scan of Google Flights retail fares, with a dashboard on
GitHub Pages. Runs entirely on GitHub's servers — nothing to install,
everything managed from a browser on any device.

## The model: trips, not routes

Every search is a **trip** in `trips.json`, managed through a form:

- **Open trip** — recurring travel with flexible days (e.g. GSP⇄LIT).
  Scans all 9 day-combos (Sun/Mon/Tue out × mid-week/weekend back) for
  every week in a rolling window, so off-cadence bargain weeks are visible.
- **Anchored trip** — fixed onsite dates with narrow flexibility (e.g.
  Englehart: out 8/23 anytime OR 8/24 arriving by 12:00; back 8/27 or
  8/28). Scans exactly those combinations and discards flights that miss
  an arrive-by cutoff.

All active trips are scanned in one daily run (~5:17am Central). Retired
trips drop off the dashboard.

## One-time setup (~10 minutes, all in a browser)

1. Create a free GitHub account.
2. **+ → New repository**, name `fare-scanner`, Private, create.
3. **Add file → Upload files**, drag in everything from this folder
   (including the `.github` folder). If folder-drag fails, use
   **Create new file** and paste each file, typing full paths like
   `.github/workflows/scan.yml` as the name (typing `/` creates folders).
4. **Settings → Pages** → Branch `main`, folder `/docs`, Save.
   Dashboard: `https://YOURNAME.github.io/fare-scanner/` — bookmark it.
5. **Settings → Actions → General → Workflow permissions** →
   **Read and write permissions** → Save.
6. **Actions tab → Daily fare scan → Run workflow** (`all`). ~10–15 min,
   then refresh the dashboard.

## Managing trips (the "form")

Dashboard → **Manage trips** (or Actions → Manage trips → Run workflow):

- **add_open**: set `dest` (any airport code), `label`, optionally `weeks`.
- **add_anchored**: set `dest`, `label`, `outbound_dates` and
  `return_dates` (comma-separated `YYYY-MM-DD`), optional `arrive_by`
  like `2026-08-24=12:00`, optional `airlines` (e.g. add `AC` for
  Toronto: `UA,DL,AA,AC`).
- **retire**: set `trip_id` (shown in trips.json) or just `dest`.

Adding a trip scans it immediately, so results appear without waiting
for the morning run.

### Admin page (nicer forms)

Dashboard → **Admin** gives real forms for the same actions plus a
bookings editor, with client-side validation. One-time setup: create a
GitHub **fine-grained personal access token** scoped to only this repo
(Contents: read/write, Actions: read/write) and paste it into the page.
The token stays in your browser's localStorage and is sent only to
`api.github.com` — it is never stored in the repo.

## Reading the dashboard

- Open trips show the weekly combo matrix; **click a combo row** to
  expand actual flight options — times, stops, layover lengths (outbound
  flights; returns are picked at booking time). Anchored trips show every valid
  date pairing ranked by cheapest First, with flight detail inline.
- Green = First in the $700–850 sweet spot; yellow = under $1,000 (a
  soft target — everything is always shown). ▼/▲ = movement since the
  last scan. **★ = lowest fare ever recorded** for that trip/date/airline
  since tracking began — your "probably as low as it goes" signal.
- Fare alerts: any First fare under $1,000 opens a GitHub issue, which
  emails you.
- Card tracker: **Edit bookings** to log bookings (`"expensed": false`,
  flip to `true` when cleared); the bar shows open exposure vs $5,000.

## Notes and limits

- Fares are retail Google Flights prices — a signal. Confirm final
  pricing, and the Econ+ **Refundable** vs First Non-refundable pairing,
  where you book. Google cannot see refundable Economy+ fares or
  booking-class codes; those exist only on the booking fare screen.
- If scans return nothing (datacenter-IP blocking), yesterday's data is
  kept and the next run usually succeeds. Persistent blocking = switch
  the data source to Amadeus's official API (which also adds booking
  class / fare basis); the dashboard wouldn't change.
- Thresholds, day combos, and pacing live in `config.json`.
