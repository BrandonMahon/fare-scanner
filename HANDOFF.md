# Fare Board: System Handoff

Everything needed to understand, operate, and move the Fare Board to a new
computer. Current as of 2026-09-20.

> This repo is **public**, so this file holds no secrets. Where a secret
> matters, the doc says where it lives.

---

## 1. What it is

A trip-based fare scanner. It pulls retail Google Flights prices on a
schedule, publishes a dashboard, and pushes a phone alert when a watched
First-class fare drops under a threshold.

**It runs entirely in the cloud.** The daily scan, the hourly watch, the
dashboard, and the admin page all run on GitHub (Actions and Pages). **Your
computer is not part of the running system.** Moving computers only affects
local development and testing. If you never clone the repo again, the Fare
Board keeps working.

| Thing | Where |
|---|---|
| Repo | https://github.com/BrandonMahon/fare-scanner (public) |
| Dashboard | https://brandonmahon.github.io/fare-scanner/ |
| Admin page | https://brandonmahon.github.io/fare-scanner/admin.html |
| Price history (CSV) | https://brandonmahon.github.io/fare-scanner/data/history.csv |
| Actions runs | https://github.com/BrandonMahon/fare-scanner/actions |
| Phone alerts | ntfy app, subscribed to the private topic (see §6) |

---

## 2. Architecture

```
                    ┌───────────────────── GitHub ─────────────────────┐
 Google Flights ◄───┤ Actions: "Daily fare scan"  scan.yml   (daily)    │
 (fast-flights)     │ Actions: "Fare watch"       watch.yml  (hourly)   │──► ntfy.sh ──► phone
                    │ Actions: "Manage trips"     trips.yml  (on demand)│
                    │        │ commits data back to main                │
                    │        ▼                                          │
                    │ repo: trips.json, config.json, docs/data/*.json   │
                    │        │                                          │
                    │        ▼                                          │
                    │ Pages: serves /docs  → dashboard + admin page     │
                    └───────────────────────────────────────────────────┘
                              ▲ reads/writes via GitHub REST API
                              │ (token stored in each browser)
                        Admin page (browser / installed PWA)
```

There's no server and no database. **The git repo is the database.** Every
scan and every admin edit is a commit.

---

## 3. Files

| Path | Purpose |
|---|---|
| `scanner.py` | Main scanner. Builds date pairs per trip, queries Google Flights (economy + first), filters by airline and arrive-by, and writes `latest.json`, `previous.json`, and `history.csv`. When fares are under $1,000 it writes `deals_found.txt`. |
| `watch.py` | Hourly tripwire. Checks First only for the trips in `config.json` → `watch`. Pushes to ntfy when the best fare is at or under the threshold and has changed. Imports its helpers from `scanner.py`. |
| `manage_trips.py` | Adds or retires trips from env vars. Used by the Manage trips workflow. |
| `trips.json` | Trip definitions (see §4). |
| `config.json` | Global settings: default origin, day combos, thresholds, pacing, and the watch list (see §5). |
| `.github/workflows/scan.yml` | "Daily fare scan": cron `17 10 * * *` (10:17 UTC) plus manual runs. Commits data and opens an issue when there are deals. |
| `.github/workflows/watch.yml` | "Fare watch": cron `23 * * * *` (hourly) plus manual runs. Uses secret `NTFY_TOPIC` and commits `watch_state.json`. |
| `.github/workflows/trips.yml` | "Manage trips": a manual form. Updates `trips.json`, then scans the new trip immediately. |
| `docs/index.html` | Dashboard: trip tabs, open-trip weekly matrices, anchored-trip ranked cards, card-exposure tracker. |
| `docs/admin.html` | Admin: add trips; edit, pause, delete, or rescan existing trips; edit watch settings; edit bookings. |
| `docs/manifest.webmanifest`, `docs/icons/` | PWA install support (Add to Home Screen). |
| `docs/data/latest.json` | Current board data. The scanner writes it and the dashboard reads it. |
| `docs/data/previous.json` | The prior scan, used for ▼/▲ movement arrows. |
| `docs/data/history.csv` | Every scan's best price per trip, date pair, cabin, and airline. Around 33k rows. Columns: `scan_date,trip,origin,dest,dep,ret,combo,cabin,airline,price`. |
| `docs/data/bookings.json` | Card-exposure tracker entries (`label, amount, booked, expensed`). |
| `docs/data/watch_state.json` | The last alerted prices per watched trip, which prevents repeat alerts. |
| `README.md` | User-facing overview. |

`.gitignore` excludes `.venv/`, `__pycache__/`, and `deals_found.txt`.

---

## 4. Trips (`trips.json`)

There are two trip types.

**Open trips** (`"type": "open"`) are recurring flexible travel. The scanner
checks every day combo in `config.json` → `combos` for `weeks_ahead` weeks,
starting about 3 days out. There are 9 combos: out Sun, Mon, or Tue, back
Wed through Sat. Each week costs 9 combos × 2 cabins = 18 queries.

**Anchored trips** (`"type": "anchored"`) are fixed dates. The scanner checks
every `outbound` × `return_dates` pairing. The optional `arrive_by` field
(`{"YYYY-MM-DD": "HH:MM"}`) drops flights that land after the cutoff on that
outbound date.

Common fields:

- `id`: stable key. History and the ★ lows are keyed by it, so renaming or
  recreating a trip starts a new series.
- `label`: display name.
- `dest`: arrival airport.
- `origin`: departure airport. Optional; blank means the default in
  `config.json`.
- `airlines`: allowed carriers. An itinerary is discarded if any leg uses a
  carrier outside this list. Add `AC` for Toronto.
- `active`: false pauses a trip and hides it from the board.

Current trips on 2026-09-20:

| id | type | route | status |
|---|---|---|---|
| `little-rock-gurdon-0724` | open, 12 weeks | GSP→LIT | active: the main recurring scan |
| `englehart-aug` | anchored, Aug 23–28 | GSP→YYZ (includes AC) | active, but **dates have passed**. Pause or delete it. |
| `lit-aug16` | anchored, Aug 16–22 | GSP→LIT | active, but **dates have passed**. Pause or delete it. |
| `lit-rolling` | open, 8 weeks | GSP→LIT | paused (replaced by `-0724`) |

---

## 5. Settings (`config.json`)

| Key | Value | Meaning |
|---|---|---|
| `origin` | `GSP` | Default departure airport |
| `combos` | 9 pairs | Open-trip [depart, return] day offsets from Sunday |
| `max_stops` | `1` | Longer connections are excluded |
| `cabins` | economy, first | Cabins the daily scan queries |
| `deal_ceiling` | `1000` | A First fare under this is highlighted yellow and opens an alert issue |
| `sweet_low` / `sweet_high` | `700` / `850` | A First fare in this range is highlighted green and tagged "SWEET SPOT" |
| `card_limit` | `5000` | Card-exposure bar maximum |
| `sleep_min` / `sleep_max` | `2.0` / `4.5` | Random delay between queries, in seconds (anti-throttle) |
| `options_per_query` | `8` | Itineraries kept per query |
| `watch` | list | Hourly watch targets: `trip`, `threshold`, optional `min_nights` and `prefer` |

Watch rules: an alert fires when the cheapest qualifying First fare is at or
under `threshold` **and** either that fare or the preferred airline's best
fare differs from the last alert. If the fare rises back over the threshold,
the state resets, so the next dip alerts again. The `prefer` airline (UA) is
always shown in the alert body, even when it isn't cheapest.

Current watch list: `englehart-aug` and `lit-aug16`, both at $800 with prefer
UA, and `min_nights 2` on LIT. **Both targets are expired**, so repoint the
watch at your next trip from the admin page.

Everything in this section can be edited from the admin page, so you don't
need to hand-edit the file.

---

## 6. Credentials and secrets (the part that doesn't copy over)

| Secret | Where it lives | On a new computer |
|---|---|---|
| **GitHub CLI login** | OS keyring on the old machine | Run `gh auth login` again (§7) |
| **Admin page token** (fine-grained PAT: Contents + Actions read/write, this repo only) | The **browser's localStorage**, per browser and per device | Paste it into the admin page again. If you don't have it saved, create a new one: GitHub → Settings → Developer settings → Fine-grained tokens. |
| **`NTFY_TOPIC`** (the push topic name, which works as a password) | GitHub repo secret. It can't be read back from GitHub. | Nothing to do: the watch runs in the cloud. The topic name is also listed in your phone's ntfy app subscriptions. To rotate it, generate a new random topic, run `gh secret set NTFY_TOPIC`, and resubscribe in the app. **Never commit the topic to this public repo.** |
| **Git commit identity** | Repo-local git config, which does **not** clone | Set it again (§7) so commits use the noreply address. |

The PWA on your phone and the ntfy subscription are unaffected by changing
computers.

---

## 7. Setting up a new computer (Windows)

Prerequisites: Git, Python 3.12, and GitHub CLI. Install the CLI with
`winget install GitHub.cli`, then open a new terminal so PATH updates.

```powershell
# 1. Sign in to GitHub. Choose GitHub.com, HTTPS, "authenticate Git: yes", web browser.
gh auth login

# 2. Clone the repo
gh repo clone BrandonMahon/fare-scanner "$env:USERPROFILE\fare-scanner"
cd "$env:USERPROFILE\fare-scanner"

# 3. Set the repo-local commit identity (noreply email keeps your real address out of public history)
git config user.name "BrandonMahon"
git config user.email "294969573+BrandonMahon@users.noreply.github.com"

# 4. Create the Python environment
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install fast-flights typing_extensions

# 5. Smoke test: a small anchored scan, or a watch dry run with no push
.\.venv\Scripts\python.exe watch.py
```

Notes:

- `typing_extensions` is required. fast-flights 3.0.2 imports it but doesn't
  declare it as a dependency.
- `watch.py` without `NTFY_TOPIC` set scans and logs but doesn't send
  anything. Discard the resulting local state change with
  `git checkout -- docs/data/watch_state.json`.
- **Always run `git pull --rebase` before editing.** The bot commits scan data
  several times a day, so a stale local copy will be rejected on push.
- If a new terminal doesn't recognize `gh` right after installing it, refresh
  PATH:
  `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`

Handy commands:

```powershell
gh workflow run "Daily fare scan" -f trip=all      # full board scan now
gh workflow run "Daily fare scan" -f trip=<id>     # one trip
gh workflow run "Fare watch"                       # watch pass now
gh run list --limit 10                             # recent runs
gh run view <run-id> --log                         # run log
```

---

## 8. Changes made to the original code (and why)

1. **Airline names mapped to codes** (`scanner.py`, `AIRLINE_CODES`).
   fast-flights 3.x returns display names like "American" instead of codes
   like "AA". Without the mapping, the airline filter discarded every result.
   Carriers outside the map pass through as their display names, so they're
   filtered out unless you add them to the map.
2. **`typing_extensions`** added to every workflow's pip install (the missing
   dependency noted in §7).
3. **Race-safe commit steps** in all three workflows: commit, then
   `pull --rebase`, then push, retrying the push once. This was needed after
   the hourly watch began colliding with scan commits.
4. **Hourly watch** (`watch.py` and `watch.yml`) with ntfy push,
   `min_nights`, and `prefer`.
5. **Per-trip `origin`.** `fetch_options(origin, dest, …)` and an `origin`
   column in `history.csv`. Rows before 2026-09-01 were backfilled as GSP.
6. **Admin page v2** (full in-app editing) and **PWA** manifest and icons.
7. **Scrubbed internal references.** Employer, rate-program, and booking-tool
   names were removed from all public text, and git history was rewritten to
   match. **Keep them out**: this repo, its issues, and the dashboard are
   public.

---

## 9. Known behavior and quirks

- **Scheduled runs start late.** GitHub queues cron jobs, so the 10:17 UTC scan
  typically starts between 7:30 and 9:30am ET. Manual runs start right away.
  To land earlier, move the cron earlier, not later.
- **Throttled days** show up as a short run and a sparse board. If a trip gets
  zero results, the scanner keeps the previous data for that trip; that's the
  "possibly blocked; keeping previous data" warning. If it gets partial
  results, only those pairs appear. This is intentional: you chose to see gaps
  rather than stale prices. It usually recovers on the next run.
- **`'NoneType' object is not subscriptable`** errors on dates roughly 7 or
  more weeks out. This is a fast-flights parsing quirk, not blocking. Those
  pairs fill in as the dates approach.
- **Occasional Pages 503.** After a deploy, the dashboard can briefly show
  "No scan data yet". Refresh the page.
- **Run budget.** The daily scan has a 60-minute timeout. About 4–5 open trips
  of 8–12 weeks each is the practical ceiling. Anchored trips cost very
  little.
- **Node 20 deprecation warnings** appear on every run. They're harmless for
  now. When GitHub eventually requires it, bump `actions/checkout` and
  `actions/setup-python` to newer major versions.
- **The schedule keeps itself alive.** GitHub pauses cron on repos with no
  activity for 60 days, but the bot's daily commits count as activity.
- **The watch only catches changes.** It won't re-alert on an unchanged fare.
  If you miss the notification, check the dashboard.
- **Fares are retail signals.** Confirm the real price and fare class at
  booking time. Google can't see booking classes or seat counts. For
  bucket-level alerts, ExpertFlyer is the outside tool.

---

## 10. Adding collaborators (a few trusted people)

1. Repo → Settings → Collaborators → invite them with **Write** access.
2. Each person creates their own token: a fine-grained token scoped to this
   repo (Contents + Actions read/write), or a classic `repo` + `workflow`
   token if the fine-grained picker doesn't list your repo.
3. They open the admin page, paste the token, and save. Optionally, they add
   the dashboard to their phone's home screen.
4. For phone alerts, share the ntfy topic with them privately, never in the
   repo.

This paste-a-token model is fine for 2–3 people. For a real team rollout,
plan these changes:

- a small backend holding one server-side token (for example, a Cloudflare
  Worker)
- a private repo on a paid plan or org, since everyone's travel dates are
  public today
- possibly the Amadeus API for booking-class data and sturdier pulls

---

## 11. Next actions

- [ ] Pause or delete `englehart-aug` and `lit-aug16` (expired).
- [ ] Repoint the watch list at the next trip.
- [ ] On the new computer, complete §7 and paste the admin token into that
      browser.
