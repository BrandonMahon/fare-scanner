#!/usr/bin/env python3
"""Add or retire trips in trips.json. Driven by the 'Manage trips'
GitHub Actions form (env vars) -- see .github/workflows/trips.yml."""

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
PATH = ROOT / "trips.json"
data = json.loads(PATH.read_text())


def env(k, default=""):
    return os.environ.get(k, default).strip()


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "trip"


def parse_dates(raw, field):
    out = []
    for tok in re.split(r"[,\s]+", raw):
        if not tok:
            continue
        try:
            out.append(date.fromisoformat(tok).isoformat())
        except ValueError:
            sys.exit(f"Bad date '{tok}' in {field}; use YYYY-MM-DD")
    if not out:
        sys.exit(f"{field} is required")
    return sorted(out)


action = env("ACTION")
dest = env("DEST").upper()
origin = env("ORIGIN").upper()
label = env("LABEL")
airlines = [a.strip().upper() for a in env("AIRLINES", "UA,DL,AA").split(",") if a.strip()]

if action == "retire":
    target = env("TRIP_ID") or dest
    hit = False
    for t in data["trips"]:
        if t["id"] == target or (not env("TRIP_ID") and t["dest"] == dest and t.get("active", True)):
            t["active"] = False
            hit = True
            print(f"Retired: {t['id']}")
    if not hit:
        sys.exit(f"No active trip matching '{target}'")

elif action in ("add_open", "add_anchored"):
    if not re.fullmatch(r"[A-Z]{3}", dest):
        sys.exit("Destination must be a 3-letter airport code")
    if origin and not re.fullmatch(r"[A-Z]{3}", origin):
        sys.exit("Origin must be a 3-letter airport code (or blank for default)")
    trip = {
        "id": f"{slug(label or dest)}-{date.today().strftime('%m%d')}",
        "type": "open" if action == "add_open" else "anchored",
        "label": label or dest,
        "dest": dest,
        "airlines": airlines,
        "active": True,
    }
    if origin:
        trip["origin"] = origin
    if action == "add_open":
        try:
            trip["weeks_ahead"] = max(1, min(12, int(env("WEEKS", "8"))))
        except ValueError:
            trip["weeks_ahead"] = 8
    else:
        trip["outbound"] = parse_dates(env("OUTBOUND_DATES"), "outbound dates")
        trip["return_dates"] = parse_dates(env("RETURN_DATES"), "return dates")
        ab = env("ARRIVE_BY")  # e.g. "2026-08-24=12:00" (comma-separate multiples)
        if ab:
            trip["arrive_by"] = {}
            for pair in ab.split(","):
                if "=" not in pair:
                    sys.exit("arrive_by format: YYYY-MM-DD=HH:MM")
                d, t = pair.split("=", 1)
                d, t = d.strip(), t.strip()
                if d not in trip["outbound"] or not re.fullmatch(r"\d{2}:\d{2}", t):
                    sys.exit(f"arrive_by '{pair}' must reference an outbound date, HH:MM")
                trip["arrive_by"][d] = t
    data["trips"].append(trip)
    print(f"Added: {trip['id']}")
    with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
        f.write(f"trip_id={trip['id']}\n")
else:
    sys.exit(f"Unknown action '{action}'")

PATH.write_text(json.dumps(data, indent=2) + "\n")
