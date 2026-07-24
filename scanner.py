#!/usr/bin/env python3
"""
Trip-based fare scanner. Runs on GitHub Actions, writes docs/data/*.json
for the dashboard.

  python scanner.py                 # scan all active trips
  python scanner.py --trip <id>     # scan one trip
"""

import argparse
import csv
import json
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from fast_flights import FlightQuery, Passengers, create_query, get_flights
from fast_flights.exceptions import FlightsNotFound

ROOT = Path(__file__).parent
DATA = ROOT / "docs" / "data"
CONFIG = json.loads((ROOT / "config.json").read_text())
TRIPS = json.loads((ROOT / "trips.json").read_text())["trips"]


# ---------------------------------------------------------------- utilities --
def to_dt(sd):
    """fast-flights SimpleDatetime -> datetime"""
    return datetime(*sd.date, *sd.time)


def load_json(path, fallback):
    try:
        return json.loads(path.read_text())
    except Exception:
        return fallback


def load_lows():
    """min price ever seen, keyed (trip, dep, ret, cabin, airline)"""
    lows = {}
    hist = DATA / "history.csv"
    if not hist.exists():
        return lows
    with hist.open() as f:
        for row in csv.DictReader(f):
            try:
                key = (row["trip"], row["dep"], row["ret"], row["cabin"], row["airline"])
                p = int(float(row["price"]))
                if key not in lows or p < lows[key]:
                    lows[key] = p
            except (KeyError, ValueError):
                continue
    return lows


# ------------------------------------------------------------------ fetching --
# fast-flights 3.x reports airline display names; trips.json and the data
# files use IATA codes, so translate before filtering.
AIRLINE_CODES = {"american": "AA", "delta": "DL", "united": "UA", "air canada": "AC"}


def airline_code(name):
    low = name.lower()
    for key, code in AIRLINE_CODES.items():
        if key in low:
            return code
    return name


def fetch_options(dest, dep, ret, cabin, airlines):
    """One round-trip query -> sorted option list with outbound flight detail."""
    query = create_query(
        flights=[
            FlightQuery(date=dep.isoformat(), from_airport=CONFIG["origin"],
                        to_airport=dest, airlines=airlines),
            FlightQuery(date=ret.isoformat(), from_airport=dest,
                        to_airport=CONFIG["origin"], airlines=airlines),
        ],
        trip="round-trip",
        seat=cabin,
        passengers=Passengers(adults=1),
        currency="USD",
        max_stops=CONFIG["max_stops"],
    )
    for attempt in range(1, 4):
        try:
            results = get_flights(query)
            break
        except FlightsNotFound:
            return []
        except Exception as exc:
            if attempt == 3:
                print(f"    ! {dep} -> {ret} {cabin}: {exc}", flush=True)
                return []
            time.sleep(8 * attempt)

    opts = []
    for itin in results:
        if not itin.airlines or not itin.price:
            continue
        codes = [airline_code(a) for a in itin.airlines]
        if not all(a in airlines for a in codes):
            continue
        legs, layovers, prev_arr = [], [], None
        try:
            for leg in itin.flights:
                d, a = to_dt(leg.departure), to_dt(leg.arrival)
                if prev_arr is not None:
                    layovers.append(int((d - prev_arr).total_seconds() // 60))
                prev_arr = a
                legs.append({
                    "from": leg.from_airport.code, "to": leg.to_airport.code,
                    "dep": d.strftime("%H:%M"), "arr": a.strftime("%H:%M"),
                })
            arr_dt = prev_arr
        except Exception:
            continue
        opts.append({
            "price": itin.price,
            "airlines": codes,
            "stops": max(len(legs) - 1, 0),
            "legs": legs,
            "layovers": layovers,
            "arr_iso": arr_dt.isoformat(timespec="minutes"),
        })
    opts.sort(key=lambda o: o["price"])
    return opts[: CONFIG["options_per_query"]]


def build_entry(trip, dep, ret, lows, arrive_by=None):
    """Price one date pair across cabins; returns entry dict or None."""
    entry = {
        "dep": dep.isoformat(),
        "ret": ret.isoformat(),
        "label": f"{dep.strftime('%a')}-{ret.strftime('%a')}",
        "nights": (ret - dep).days,
        "cabins": {},
    }
    cutoff = None
    if arrive_by:
        cutoff = datetime.fromisoformat(f"{dep.isoformat()}T{arrive_by}")

    got_data = False
    for cabin in CONFIG["cabins"]:
        opts = fetch_options(trip["dest"], dep, ret, cabin, trip["airlines"])
        time.sleep(random.uniform(CONFIG["sleep_min"], CONFIG["sleep_max"]))
        if cutoff:
            opts = [o for o in opts
                    if datetime.fromisoformat(o["arr_iso"]) <= cutoff]
        best = {}
        for o in opts:
            al = o["airlines"][0]
            if al not in best or o["price"] < best[al]:
                best[al] = o["price"]
        low, at_low = {}, {}
        for al, p in best.items():
            key = (trip["id"], entry["dep"], entry["ret"], cabin, al)
            floor = min(lows.get(key, p), p)
            low[al] = floor
            at_low[al] = p <= floor
        entry["cabins"][cabin] = {"best": best, "low": low,
                                  "at_low": at_low, "options": opts}
        got_data = got_data or bool(opts)
    if arrive_by:
        entry["arrive_by"] = arrive_by
    return entry if got_data else None


# --------------------------------------------------------------- trip scans --
def open_pairs(trip):
    start = date.today() + timedelta(days=3)
    sunday = start + timedelta(days=(6 - start.weekday()) % 7)
    pairs = []
    for w in range(trip.get("weeks_ahead", 8)):
        wk = sunday + timedelta(weeks=w)
        for dep_off, ret_off in CONFIG["combos"]:
            dep, ret = wk + timedelta(days=dep_off), wk + timedelta(days=ret_off)
            if dep > date.today():
                pairs.append((dep, ret, None))
    return pairs


def anchored_pairs(trip):
    pairs = []
    for ob in trip["outbound"]:
        for rb in trip["return_dates"]:
            dep, ret = date.fromisoformat(ob), date.fromisoformat(rb)
            if ret > dep >= date.today():
                pairs.append((dep, ret, trip.get("arrive_by", {}).get(ob)))
    return pairs


def scan_trip(trip, lows):
    pairs = open_pairs(trip) if trip["type"] == "open" else anchored_pairs(trip)
    total = len(pairs) * len(CONFIG["cabins"])
    print(f"== {trip['label']} ({trip['id']}): {len(pairs)} date pairs, "
          f"{total} queries", flush=True)
    entries, n = [], 0
    for dep, ret, arrive_by in pairs:
        n += 1
        print(f"[{n}/{len(pairs)}] {dep} -> {ret}", flush=True)
        e = build_entry(trip, dep, ret, lows, arrive_by)
        if e:
            entries.append(e)
    return entries


# ------------------------------------------------------------------- output --
def append_history(trip_id, dest, entries):
    hist = DATA / "history.csv"
    new = not hist.exists()
    with hist.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["scan_date", "trip", "dest", "dep", "ret",
                        "combo", "cabin", "airline", "price"])
        today = date.today().isoformat()
        for e in entries:
            for cabin, blk in e["cabins"].items():
                for al, p in blk["best"].items():
                    w.writerow([today, trip_id, dest, e["dep"], e["ret"],
                                e["label"], cabin, al, p])


def find_deals(trip, entries):
    out = []
    for e in entries:
        fc = e["cabins"].get("first", {})
        for al, p in fc.get("best", {}).items():
            if p < CONFIG["deal_ceiling"]:
                tag = " ** SWEET SPOT **" if CONFIG["sweet_low"] <= p <= CONFIG["sweet_high"] else ""
                star = " (lowest seen)" if fc["at_low"].get(al) else ""
                out.append(f"{trip['label']} {e['label']} {e['dep']} -> {e['ret']}: "
                           f"{al} First ${p}{tag}{star}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", default="all")
    args = ap.parse_args()

    if args.trip == "all":
        targets = [t for t in TRIPS if t.get("active", True)]
    else:
        targets = [t for t in TRIPS if t["id"] == args.trip]
        if not targets:
            sys.exit(f"No trip with id '{args.trip}' in trips.json")
    if not targets:
        sys.exit("No active trips in trips.json")

    DATA.mkdir(parents=True, exist_ok=True)
    latest_path, prev_path = DATA / "latest.json", DATA / "previous.json"
    latest = load_json(latest_path, {"trips": {}})
    previous = load_json(prev_path, {"trips": {}})
    latest.setdefault("trips", {})
    previous.setdefault("trips", {})
    lows = load_lows()

    all_deals = []
    for trip in targets:
        entries = scan_trip(trip, lows)
        if not entries:
            print(f"WARNING: no results for {trip['id']} -- possibly blocked; "
                  f"keeping previous data", flush=True)
            continue
        if trip["id"] in latest["trips"]:
            previous["trips"][trip["id"]] = latest["trips"][trip["id"]]
        latest["trips"][trip["id"]] = {
            "label": trip["label"], "type": trip["type"], "dest": trip["dest"],
            "airlines": trip["airlines"],
            "scanned_at": date.today().isoformat(),
            "entries": entries,
        }
        append_history(trip["id"], trip["dest"], entries)
        all_deals += find_deals(trip, entries)

    # drop retired trips from the board
    active_ids = {t["id"] for t in TRIPS if t.get("active", True)}
    latest["trips"] = {k: v for k, v in latest["trips"].items() if k in active_ids}

    latest["origin"] = CONFIG["origin"]
    latest["config"] = {k: CONFIG[k] for k in
                        ("deal_ceiling", "sweet_low", "sweet_high", "card_limit")}
    latest_path.write_text(json.dumps(latest, indent=1))
    prev_path.write_text(json.dumps(previous, indent=1))

    if all_deals:
        (ROOT / "deals_found.txt").write_text(
            "First class fares in range on today's scan:\n\n"
            + "\n".join(all_deals)
            + "\n\nConfirm final pricing and fare-class options before booking."
        )
        print("\n".join(all_deals))
    print("Done.")


if __name__ == "__main__":
    main()
