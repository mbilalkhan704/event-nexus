import sys
import pandas as pd
from config import DATA_CLEAN, GRAPH_RULES, ORG_ALIASES, ORG_PLACEHOLDERS, get_driver, run
from itertools import combinations
from collections import defaultdict
from areas import build_gazetteer, extract_area_detail

BATCH = 500


def clean(value):
    """Turn pandas missing values and numpy types into plain Python."""
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def to_int(value):
    value = clean(value)
    return None if value is None else int(value)


def to_bool(value):
    value = clean(value)
    return None if value is None else bool(value)


def event_rows(df):
    rows = []
    for r in df.to_dict("records"):
        rows.append({
            "eventid": int(r["eventid"]),
            "date": r["date"].date(),
            "date_approx": to_bool(r["date_approx"]),
            "summary_clean": clean(r["summary_clean"]),
            "location": clean(r["location"]),
            "city_raw": clean(r["city_raw"]),
            "nkill": to_int(r["nkill"]),
            "nwound": to_int(r["nwound"]),
            "success": to_bool(r["success"]),
            "suicide": to_bool(r["suicide"]),
            "multiple": to_bool(r["multiple"]),
            "doubtterr": to_bool(r["doubtterr"]),
            "actor_known": to_bool(r["actor_known"]),
            "dup_group": to_int(r["dup_group"]),
            "gname": clean(r["gname"]),
            "attack_type": clean(r["attacktype1_txt"]),
            "weapon_type": clean(r["weaptype1_txt"]),
            "weapon_subtype": clean(r["weapsubtype1_txt"]),
            "weapon_detail": clean(r["weapdetail"]),
            "target_type": clean(r["targtype1_txt"]),
            "target_subtype": clean(r["targsubtype1_txt"]),
            "target_org": clean(r["corp1"]),
            "target_desc": clean(r["target1"]),
            "motive": clean(r["motive"]),
        })
    return rows


LOAD_EVENTS = """
UNWIND $rows AS row
MERGE (e:Event {eventid: row.eventid})
SET e += row
"""


def reset(driver):
    run(driver, "MATCH (n) DETACH DELETE n")
    print("Graph cleared")


def load_events(driver, df):
    rows = event_rows(df)
    for i in range(0, len(rows), BATCH):
        run(driver, LOAD_EVENTS, rows=rows[i:i + BATCH])
    print("Events loaded:", len(rows))


def usable(value):
    """Return a tidy string, or None for missing and 'Unknown' values."""
    value = clean(value)
    if value is None:
        return None
    value = " ".join(str(value).split())
    if value == "" or value.lower() == "unknown":
        return None
    return value


def link(driver, label, key, rel, rows):
    query = (
        "UNWIND $rows AS row "
        "MATCH (e:Event {eventid: row.eventid}) "
        f"MERGE (n:{label} {{{key}: row.value}}) "
        f"MERGE (e)-[r:{rel}]->(n) "
        "SET r += row.props"
    )
    for i in range(0, len(rows), BATCH):
        run(driver, query, rows=rows[i:i + BATCH])
    print(f"{rel}: {len(rows)} links sent")


def load_attributes(driver, df):
    groups, attacks, weapons, targets, orgs, sources = [], [], [], [], [], []

    for r in df.to_dict("records"):
        eid = int(r["eventid"])

        if to_bool(r["actor_known"]):
            name = usable(r["gname"])
            if name:
                groups.append({"eventid": eid, "value": name, "props": {
                    "claimed": to_bool(r["claimed"]),
                    "uncertain": to_bool(r["guncertain1"]),
                }})

        value = usable(r["attacktype1_txt"])
        if value:
            attacks.append({"eventid": eid, "value": value, "props": {}})

        value = usable(r["weaptype1_txt"])
        if value:
            weapons.append({"eventid": eid, "value": value,
                            "props": {"subtype": clean(r["weapsubtype1_txt"])}})

        value = usable(r["targtype1_txt"])
        if value:
            targets.append({"eventid": eid, "value": value,
                            "props": {"subtype": clean(r["targsubtype1_txt"])}})

        value = usable(r["corp1"])
        if value:
            value = value.replace("\u2019", "'")
            if value.lower() not in ORG_PLACEHOLDERS:
                orgs.append({"eventid": eid, "value": ORG_ALIASES.get(value, value), "props": {}})

        for slot, col in ((1, "scite1"), (2, "scite2"), (3, "scite3")):
            citation = usable(r[col])
            if citation:
                sources.append({"eventid": eid, "value": citation, "props": {
                    "slot": slot,
                    "dbsource": clean(r["dbsource"]),
                }})

    link(driver, "Group", "name", "ATTRIBUTED_TO", groups)
    link(driver, "AttackType", "name", "HAS_ATTACK_TYPE", attacks)
    link(driver, "WeaponType", "name", "USED_WEAPON", weapons)
    link(driver, "TargetType", "name", "TARGETED", targets)
    link(driver, "TargetOrg", "name", "TARGETED_ORG", orgs)
    link(driver, "Source", "citation", "REPORTED_BY", sources)


def summary(driver):
    print("\nNodes:")
    for rec in run(driver, "MATCH (n) UNWIND labels(n) AS l RETURN l AS label, count(*) AS c ORDER BY c DESC"):
        print(f"  {rec['label']:12s} {rec['c']}")
    print("Relationships:")
    for rec in run(driver, "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS c ORDER BY c DESC"):
        print(f"  {rec['type']:16s} {rec['c']}")


def ordered(a, b, key):
    """Return the pair earlier-first (by date, then eventid)."""
    return (a, b) if key[a] <= key[b] else (b, a)


def derived_rows(df):
    key = {int(e): (d, int(e)) for e, d in zip(df["eventid"], df["date"])}
    window = GRAPH_RULES["same_actor_window_days"]
    actor_rows, source_rows, related_rows = [], [], []

    # SAME_ACTOR_NEARBY
    by_group = defaultdict(list)
    for r in df.to_dict("records"):
        if to_bool(r["actor_known"]):
            name = usable(r["gname"])
            if name:
                by_group[name].append((int(r["eventid"]), r["date"]))
    for name, items in by_group.items():
        for (a, da), (b, db) in combinations(items, 2):
            gap = abs((da - db).days)
            if gap <= window:
                first, second = ordered(a, b, key)
                actor_rows.append({"a": first, "b": second, "props": {
                    "rule": "same_actor_nearby",
                    "gap_days": gap,
                    "strength": round(1 - gap / (window + 1), 2),
                    "evidence": [f"group: {name}", f"gap_days: {gap}"],
                }})

    # SAME_SOURCE
    by_cite = defaultdict(set)
    for r in df.to_dict("records"):
        for col in ("scite1", "scite2", "scite3"):
            citation = usable(r[col])
            if citation:
                by_cite[citation].add(int(r["eventid"]))
    shared = defaultdict(list)
    for citation, events in by_cite.items():
        if 2 <= len(events) <= GRAPH_RULES["source_max_events"]:
            for a, b in combinations(sorted(events), 2):
                first, second = ordered(a, b, key)
                shared[(first, second)].append(citation)
    for (a, b), cites in shared.items():
        source_rows.append({"a": a, "b": b, "props": {
            "rule": "same_source",
            "strength": len(cites),
            "evidence": [c[:120] for c in cites[:3]],
        }})

    # GTD_RELATED (evaluation only)
    seen = set()
    for eid, related in zip(df["eventid"], df["related_in_scope"]):
        for other in related:
            pair = tuple(sorted((int(eid), int(other))))
            if pair not in seen:
                seen.add(pair)
                first, second = ordered(pair[0], pair[1], key)
                related_rows.append({"a": first, "b": second, "props": {
                    "rule": "gtd_related",
                    "evaluation_only": True,
                }})

    return actor_rows, source_rows, related_rows


def load_links(driver, rel, rows):
    query = (
        "UNWIND $rows AS row "
        "MATCH (a:Event {eventid: row.a}) "
        "MATCH (b:Event {eventid: row.b}) "
        f"MERGE (a)-[r:{rel}]->(b) "
        "SET r += row.props"
    )
    for i in range(0, len(rows), BATCH):
        run(driver, query, rows=rows[i:i + BATCH])
    print(f"{rel}: {len(rows)} links sent")


def area_assignments(df):
    """Area, locality and method for every event that has one."""
    gazetteer = build_gazetteer(df)
    out = {}
    for r in df.to_dict("records"):
        area, locality, method = extract_area_detail(
            r["location"], r["summary_clean"], r["city_raw"], gazetteer)
        if area:
            out[int(r["eventid"])] = (area, locality, method)
    return out


def load_areas(driver, assignments):
    in_rows = [{"eventid": e, "value": a, "props": {"method": m}}
               for e, (a, loc, m) in assignments.items()]
    at_rows = [{"eventid": e, "value": loc, "props": {}}
               for e, (a, loc, m) in assignments.items() if loc]
    link(driver, "Area", "name", "OCCURRED_IN", in_rows)
    link(driver, "Locality", "name", "OCCURRED_AT", at_rows)

    parts = sorted({(loc, a) for (a, loc, m) in assignments.values() if loc})
    run(driver,
        "UNWIND $rows AS row "
        "MATCH (l:Locality {name: row.child}) MATCH (a:Area {name: row.parent}) "
        "MERGE (l)-[:PART_OF]->(a)",
        rows=[{"child": c, "parent": p} for c, p in parts])
    print(f"PART_OF: {len(parts)} links sent")


def area_link_rows(df, assignments):
    info = {}
    for r in df.to_dict("records"):
        eid = int(r["eventid"])
        if eid in assignments:
            area, locality, _ = assignments[eid]
            info[eid] = {
                "date": r["date"], "area": area, "locality": locality,
                "mo": (usable(r["attacktype1_txt"]), usable(r["weaptype1_txt"]),
                       usable(r["targtype1_txt"])),
            }

    def same_locality(a, b):
        return info[a]["locality"] is not None and info[a]["locality"] == info[b]["locality"]

    # SAME_MO_LOCAL: same area and same attack, weapon and target type, close in time
    window = GRAPH_RULES["same_mo_window_days"]
    groups = defaultdict(list)
    for eid, d in info.items():
        if all(d["mo"]):
            groups[(d["area"],) + d["mo"]].append(eid)
    mo_rows = []
    for (area, attack, weapon, target), ids in groups.items():
        for a, b in combinations(ids, 2):
            gap = abs((info[a]["date"] - info[b]["date"]).days)
            if gap <= window:
                first, second = sorted((a, b), key=lambda e: (info[e]["date"], e))
                shared = same_locality(a, b)
                evidence = [f"area: {area}", f"attack: {attack}", f"weapon: {weapon}",
                            f"target: {target}", f"gap_days: {gap}"]
                if shared:
                    evidence.append(f"locality: {info[a]['locality']}")
                mo_rows.append({"a": first, "b": second, "props": {
                    "rule": "same_mo_local", "gap_days": gap,
                    "strength": round(1 - gap / (window + 1), 2),
                    "same_locality": shared, "evidence": evidence}})

    # FOLLOWED_BY: the next event in the same area, if it comes soon enough
    follow_window = GRAPH_RULES["followed_by_window_days"]
    by_area = defaultdict(list)
    for eid, d in info.items():
        by_area[d["area"]].append(eid)
    follow_rows = []
    for area, ids in by_area.items():
        ids.sort(key=lambda e: (info[e]["date"], e))
        for a, b in zip(ids, ids[1:]):
            gap = (info[b]["date"] - info[a]["date"]).days
            if gap <= follow_window:
                shared = same_locality(a, b)
                evidence = [f"area: {area}", f"gap_days: {gap}"]
                if shared:
                    evidence.append(f"locality: {info[a]['locality']}")
                follow_rows.append({"a": a, "b": b, "props": {
                    "rule": "followed_by", "gap_days": gap,
                    "strength": round(1 - gap / (follow_window + 1), 2),
                    "same_locality": shared, "evidence": evidence}})
    return mo_rows, follow_rows


if __name__ == "__main__":
    driver = get_driver()
    df = pd.read_parquet(DATA_CLEAN)

    if "--reset" in sys.argv:
        reset(driver)

    load_events(driver, df)
    load_attributes(driver, df)

    actor_rows, source_rows, related_rows = derived_rows(df)
    load_links(driver, "SAME_ACTOR_NEARBY", actor_rows)
    load_links(driver, "SAME_SOURCE", source_rows)
    load_links(driver, "GTD_RELATED", related_rows)

    assignments = area_assignments(df)
    print(f"Events with an area: {len(assignments)} of {len(df)}")
    load_areas(driver, assignments)
    mo_rows, follow_rows = area_link_rows(df, assignments)
    load_links(driver, "SAME_MO_LOCAL", mo_rows)
    load_links(driver, "FOLLOWED_BY", follow_rows)

    summary(driver)
    driver.close()
