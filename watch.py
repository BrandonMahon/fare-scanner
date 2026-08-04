#!/usr/bin/env python3
"""Hourly fare watch. Scans the trips listed in config.json "watch"
(First class only) and pushes an ntfy.sh notification when the best fare
is at or under that trip's threshold. Keeps its own state in
docs/data/watch_state.json; never touches the daily board data.

Alert rule: notify when best First <= threshold and the best (or the
preferred airline's best) price differs from the last alerted prices.
When the fare climbs back above the threshold the state resets, so a
later re-drop alerts again.

Per-watch options in config.json: "threshold" (dollars), "min_nights"
(skip shorter pairings), "prefer" (airline code always shown in the
alert even when it is not the cheapest).
"""

import json
import os
import random
import time
import urllib.request
from datetime import datetime

from scanner import CONFIG, TRIPS, DATA, fetch_options, anchored_pairs, open_pairs

STATE_PATH = DATA / "watch_state.json"
MAX_PAIRS = 24  # safety cap; watch is meant for small anchored trips


def load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def notify(topic, title, body):
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=body.encode(),
        headers={"Title": title, "Priority": "high", "Tags": "airplane"},
    )
    urllib.request.urlopen(req, timeout=30)


def fmtd(d):
    return f"{d.strftime('%a')} {d.month}/{d.day}"


def describe(opt, dep, ret):
    route = opt["legs"][0]["from"] + "".join("-" + l["to"] for l in opt["legs"])
    lays = ", ".join(f"{m//60}h{m%60:02d}" if m >= 60 else f"{m}m"
                     for m in opt["layovers"]) or "nonstop"
    return (f"{fmtd(dep)} -> {fmtd(ret)}\n"
            f"{route}  dep {opt['legs'][0]['dep']}  arr {opt['legs'][-1]['arr']}"
            f"  ({opt['stops']} stop, layover {lays})")


def best_first(trip, min_nights=0, prefer=None):
    pairs = anchored_pairs(trip) if trip["type"] == "anchored" else open_pairs(trip)
    if min_nights:
        pairs = [(d, r, ab) for d, r, ab in pairs if (r - d).days >= min_nights]
    if len(pairs) > MAX_PAIRS:
        print(f"  capping {trip['id']} watch to first {MAX_PAIRS} of {len(pairs)} pairs")
        pairs = pairs[:MAX_PAIRS]
    best, best_pref = None, None
    for dep, ret, arrive_by in pairs:
        opts = fetch_options(trip["dest"], dep, ret, "first", trip["airlines"])
        time.sleep(random.uniform(CONFIG["sleep_min"], CONFIG["sleep_max"]))
        if arrive_by:
            cutoff = datetime.fromisoformat(f"{dep.isoformat()}T{arrive_by}")
            opts = [o for o in opts
                    if datetime.fromisoformat(o["arr_iso"]) <= cutoff]
        for o in opts:
            if best is None or o["price"] < best[0]["price"]:
                best = (o, dep, ret)
            if prefer and prefer in o["airlines"]:
                if best_pref is None or o["price"] < best_pref[0]["price"]:
                    best_pref = (o, dep, ret)
    return best, best_pref


def main():
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("NTFY_TOPIC not set -- will scan and log but not notify")
    state = load_state()
    changed = False

    for w in CONFIG.get("watch", []):
        trip = next((t for t in TRIPS if t["id"] == w["trip"]), None)
        if not trip or not trip.get("active", True):
            print(f"watch target '{w['trip']}' missing or inactive; skipping")
            continue
        thr = w.get("threshold", CONFIG["deal_ceiling"])
        prefer = w.get("prefer")
        print(f"== watching {trip['label']} ({trip['id']}), threshold ${thr}")
        best, best_pref = best_first(trip, w.get("min_nights", 0), prefer)
        if best is None:
            print("  no First data this pass (throttled or none published)")
            continue
        opt, dep, ret = best
        price, airline = opt["price"], opt["airlines"][0]
        pref_price = best_pref[0]["price"] if best_pref else None
        last = state.get(trip["id"])
        if isinstance(last, int):          # legacy single-price state
            last = {"best": last, "pref": None}
        print(f"  best: {airline} ${price} {dep} -> {ret}"
              f" | {prefer or 'pref'}: {pref_price} | last alerted: {last}")

        if price <= thr and (last is None or price != last.get("best")
                             or pref_price != last.get("pref")):
            title = f"{trip['label']}: {airline} First ${price}"
            body = describe(opt, dep, ret)
            if best_pref and best_pref[0] is not opt:
                po, pd, pr = best_pref
                body += f"\n\n{prefer} option: ${po['price']}\n" + describe(po, pd, pr)
            if last is not None:
                body += f"\n(was ${last.get('best')})"
            body += f"\nThreshold ${thr}"
            if topic:
                notify(topic, title, body)
                print(f"  ALERT sent: {title}")
            else:
                print(f"  ALERT (not sent, no topic): {title}")
            state[trip["id"]] = {"best": price, "pref": pref_price}
            changed = True
        elif price > thr and last is not None:
            print("  climbed above threshold; resetting so the next dip re-alerts")
            del state[trip["id"]]
            changed = True

    if changed:
        STATE_PATH.write_text(json.dumps(state, indent=1) + "\n")
        print("state updated")
    print("Done.")


if __name__ == "__main__":
    main()
