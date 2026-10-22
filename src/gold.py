"""
Gold-query builders: open-lane forms of the library queries (literals instead of parameters,
LIMIT added, no CALL). Copied unchanged from make_dev.py, which is frozen; make_pairs.py imports
them so training queries have exactly the dev style. Do not edit without checking make_dev.py.
"""
from datetime import date, timedelta

END = date(2020, 12, 22)
END_S = END.isoformat()


def lit(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def dt(s):
    return f"date({lit(s)})"


def yr(y):
    return f"{y}-01-01", f"{y}-12-31"


def back(n):
    """Start of 'the last n years', counted back from the end of the data."""
    return (date(END.year - n, END.month, END.day) + timedelta(days=1)).isoformat()


def one(var, d_from, d_to):
    c = []
    if d_from:
        c.append(f"{var}.date >= {dt(d_from)}")
    if d_to:
        c.append(f"{var}.date <= {dt(d_to)}")
    return c


def both(a, b, d_from, d_to):
    c = []
    if d_from:
        c.append(f"({a}.date >= {dt(d_from)} AND {b}.date >= {dt(d_from)})")
    if d_to:
        c.append(f"({a}.date <= {dt(d_to)} AND {b}.date <= {dt(d_to)})")
    return c


def where(conds, sep=" AND "):
    return ("WHERE " + sep.join(conds) + "\n") if conds else ""


def q0b(order="severity", limit=5, d_from=None, d_to=None, area=None, group=None,
        attack=None, weapon=None, target=None):
    w = one("e", d_from, d_to)
    if attack:
        w.append("e.attack_type = " + lit(attack))
    if weapon:
        w.append("e.weapon_type = " + lit(weapon))
    if target:
        w.append("e.target_type = " + lit(target))
    if area:
        w.append("EXISTS { (e)-[:OCCURRED_IN]->(:Area {name: " + lit(area) + "}) }")
    if group:
        w.append("EXISTS { (e)-[:ATTRIBUTED_TO]->(:Group {name: " + lit(group) + "}) }")
    if order == "severity":
        w.append("e.nkill IS NOT NULL")
    text = "MATCH (e:Event)\n" + where(w, "\n  AND ")
    if order == "severity":
        text += ("WITH e, e.nkill - coalesce(e.nkillter, 0) AS victims_killed,\n"
                 "     CASE WHEN e.nwound IS NULL THEN null ELSE e.nwound - coalesce(e.nwoundte, 0) END AS victims_wounded\n"
                 "RETURN e.eventid AS _ref, e.date AS date, victims_killed, victims_wounded\n"
                 "ORDER BY victims_killed DESC, coalesce(victims_wounded, 0) DESC, e.date DESC\n")
    else:
        text += ("RETURN e.eventid AS _ref, e.date AS date\n"
                 f"ORDER BY e.date {'DESC' if order == 'newest' else 'ASC'}\n")
    return text + f"LIMIT {limit}"


Q1_GOLD = (
    "MATCH (e:Event {eventid: $ref})\n"
    "OPTIONAL MATCH (e)-[:OCCURRED_IN]->(a:Area)\n"
    "OPTIONAL MATCH (e)-[:OCCURRED_AT]->(l:Locality)\n"
    "RETURN e.eventid AS _ref, e.date AS date, e.summary_clean AS summary, e.location AS location,\n"
    "       a.name AS area, l.name AS locality, e.attack_type AS attack_type, e.weapon_type AS weapon_type,\n"
    "       e.target_type AS target_type, e.target_org AS target_org,\n"
    "       CASE WHEN e.nkill IS NULL THEN null ELSE e.nkill - coalesce(e.nkillter, 0) END AS victims_killed,\n"
    "       CASE WHEN e.nwound IS NULL THEN null ELSE e.nwound - coalesce(e.nwoundte, 0) END AS victims_wounded,\n"
    "       [(e)-[r:ATTRIBUTED_TO]->(g:Group) | {group: g.name, claimed: r.claimed, uncertain: r.uncertain}] AS attribution,\n"
    "       COLLECT { MATCH (e)-[:REPORTED_BY]->(s:Source) RETURN s.citation } AS sources\n"
    "LIMIT 1")


def q2(g, d_from=None, d_to=None):
    return ("MATCH (e:Event)-[:ATTRIBUTED_TO]->(g:Group {name: " + lit(g) + "})\n"
            + where(one("e", d_from, d_to))
            + "OPTIONAL MATCH (e)-[:OCCURRED_IN]->(a:Area)\n"
              "RETURN e.eventid AS _ref, e.date AS date, e.attack_type AS attack_type, a.name AS area\n"
              "ORDER BY e.date\nLIMIT 50")


def q3(g, gap, d_from=None, d_to=None):
    w = ["a.eventid < b.eventid", f"r.gap_days <= {gap}"] + both("a", "b", d_from, d_to)
    return ("MATCH (a:Event)-[r:SAME_ACTOR_NEARBY]-(b:Event)\n" + where(w, "\n  AND ")
            + "MATCH (a)-[:ATTRIBUTED_TO]->(g:Group)\n" + (f"WHERE g.name = {lit(g)}\n" if g else "")
            + "RETURN g.name AS group, a.eventid AS _ref_a, b.eventid AS _ref_b, r.gap_days AS gap_days\n"
              "ORDER BY g.name, gap_days\nLIMIT 50")


def q3b(g, gap, d_from=None, d_to=None):
    w = ["a.eventid < b.eventid", f"abs(duration.inDays(a.date, b.date).days) <= {gap}"]
    if g:
        w.append(f"g.name = {lit(g)}")
    w += both("a", "b", d_from, d_to)
    return ("MATCH (a:Event)-[:ATTRIBUTED_TO]->(g:Group)<-[:ATTRIBUTED_TO]-(b:Event)\n" + where(w, "\n  AND ")
            + "RETURN g.name AS group, a.eventid AS _ref_a, b.eventid AS _ref_b,\n"
              "       abs(duration.inDays(a.date, b.date).days) AS gap_days\n"
              "ORDER BY g.name, gap_days\nLIMIT 50")


def q4(gap, area=None, attack=None, weapon=None, target=None, d_from=None, d_to=None, computed=False):
    filt = []
    if area:
        filt.append("ar.name = " + lit(area))
    for prop, val in (("attack_type", attack), ("weapon_type", weapon), ("target_type", target)):
        if val:
            filt.append(f"a.{prop} = " + lit(val))
    dates = both("a", "b", d_from, d_to)
    if not computed:
        return ("MATCH (a:Event)-[r:SAME_MO_LOCAL]-(b:Event)\n"
                + where(["a.eventid < b.eventid", f"r.gap_days <= {gap}"] + dates, "\n  AND ")
                + "MATCH (a)-[:OCCURRED_IN]->(ar:Area)\n" + where(filt)
                + "RETURN ar.name AS area, a.eventid AS _ref_a, b.eventid AS _ref_b, r.gap_days AS gap_days\n"
                  "ORDER BY ar.name, gap_days\nLIMIT 50")
    w = (["a.eventid < b.eventid",
          "a.attack_type = b.attack_type AND a.attack_type <> 'Unknown'",
          "a.weapon_type = b.weapon_type AND a.weapon_type <> 'Unknown'",
          "a.target_type = b.target_type AND a.target_type <> 'Unknown'",
          f"abs(duration.inDays(a.date, b.date).days) <= {gap}"] + filt + dates)
    return ("MATCH (a:Event)-[:OCCURRED_IN]->(ar:Area)<-[:OCCURRED_IN]-(b:Event)\n" + where(w, "\n  AND ")
            + "RETURN ar.name AS area, a.eventid AS _ref_a, b.eventid AS _ref_b,\n"
              "       abs(duration.inDays(a.date, b.date).days) AS gap_days\n"
              "ORDER BY ar.name, gap_days\nLIMIT 50")


Q5_GOLD = (
    "MATCH (a:Event)-[r:SAME_SOURCE]-(b:Event)\n"
    "WHERE a.eventid < b.eventid AND (a.eventid = $ref OR b.eventid = $ref)\n"
    "RETURN a.eventid AS _ref_a, b.eventid AS _ref_b, r.strength AS shared_citations,\n"
    "       abs(duration.inDays(a.date, b.date).days) AS gap_days,\n"
    "       EXISTS { (a)-[:OCCURRED_IN]->(:Area)<-[:OCCURRED_IN]-(b) } AS same_area\n"
    "LIMIT 50")


def q6(window, target, d_from=None, d_to=None):
    w = ["g1.name < g2.name"]
    if window:
        w.append(f"abs(duration.inDays(e1.date, e2.date).days) <= {window}")
    if target:
        w.append(f"t.name = {lit(target)}")
    w += both("e1", "e2", d_from, d_to)
    return ("MATCH (e1:Event)-[:ATTRIBUTED_TO]->(g1:Group), (e2:Event)-[:ATTRIBUTED_TO]->(g2:Group),\n"
            "      (e1)-[:TARGETED]->(t:TargetType)<-[:TARGETED]-(e2)\n" + where(w, "\n  AND ")
            + "RETURN t.name AS target_type, g1.name AS group_a, g2.name AS group_b, count(*) AS event_pairs\n"
              "ORDER BY event_pairs DESC, target_type, group_a, group_b\nLIMIT 50")


def q7(n, d_from=None, d_to=None):
    return ("MATCH (e:Event)-[:OCCURRED_IN]->(a:Area), (e)-[:ATTRIBUTED_TO]->(g:Group)\n"
            + where(one("e", d_from, d_to))
            + "WITH a, count(DISTINCT g) AS group_count\n"
              f"WHERE group_count >= {n}\n"
              "RETURN a.name AS area, group_count\nORDER BY group_count DESC, area\nLIMIT 50")


def q9(area=None, d_from=None, d_to=None, limit=50):
    w = ["NOT EXISTS { ()-[:FOLLOWED_BY]->(a) }", "NOT EXISTS { (b)-[:FOLLOWED_BY]->() }"]
    if d_from:
        w.append(f"a.date >= {dt(d_from)}")
    if d_to:
        w.append(f"b.date <= {dt(d_to)}")
    return ("MATCH p = (a:Event)-[:FOLLOWED_BY*2..]->(b:Event)\n" + where(w, "\n  AND ")
            + "MATCH (a)-[:OCCURRED_IN]->(ar:Area)\n" + (f"WHERE ar.name = {lit(area)}\n" if area else "")
            + "RETURN ar.name AS area, length(p) + 1 AS events, a.date AS start_date, b.date AS end_date\n"
              f"ORDER BY events DESC, start_date\nLIMIT {limit}")


def q11(via, n):
    mid = ("(x:Area)<-[:OCCURRED_IN]-" if via == "area" else "(x:TargetOrg)<-[:TARGETED_ORG]-")
    link = "-[:OCCURRED_IN]->" if via == "area" else "-[:TARGETED_ORG]->"
    return ("MATCH (g1:Group)<-[:ATTRIBUTED_TO]-(:Event)" + link + mid
            + "(:Event)-[:ATTRIBUTED_TO]->(g2:Group)\n"
              "WHERE g1.name < g2.name\n"
              "WITH g1, g2, count(DISTINCT x) AS shared\n"
              f"WHERE shared >= {n}\n"
              "RETURN g1.name AS group_a, g2.name AS group_b, shared\n"
              "ORDER BY shared DESC, group_a, group_b\nLIMIT 50")


Q12_GOLD = (
    "MATCH (a:Event {eventid: $ref_a}), (b:Event {eventid: $ref_b})\n"
    "OPTIONAL MATCH (a)-[r]-(b)\n"
    "WHERE type(r) <> 'GTD_RELATED'\n"
    "RETURN type(r) AS link_type, r.gap_days AS gap_days\n"
    "LIMIT 50")


def q13_counts(g):
    return ("MATCH (e:Event)-[r:ATTRIBUTED_TO]->(g:Group {name: " + lit(g) + "})\n"
            "RETURN CASE WHEN coalesce(r.claimed, false) THEN 'claimed'\n"
            "            WHEN coalesce(r.uncertain, false) THEN 'suspected'\n"
            "            ELSE 'attributed, not flagged suspected' END AS status,\n"
            "       count(e) AS events\nORDER BY status\nLIMIT 50")


Q13_COND = {"claimed": "coalesce(r.claimed, false)",
            "suspected": "NOT coalesce(r.claimed, false) AND coalesce(r.uncertain, false)",
            "plain": "NOT coalesce(r.claimed, false) AND NOT coalesce(r.uncertain, false)"}


def q13_list(g, kind):
    return ("MATCH (e:Event)-[r:ATTRIBUTED_TO]->(g:Group {name: " + lit(g) + "})\n"
            "WHERE " + Q13_COND[kind] + "\n"
            "RETURN e.eventid AS _ref, e.date AS date\nORDER BY e.date\nLIMIT 50")




# ---------- aggregation gold (AGG family; not in make_dev.py) ----------
def _agg_where(d_from=None, d_to=None, area=None, group=None, attack=None, weapon=None,
               target=None, extra=()):
    w = one("e", d_from, d_to)
    for prop, val in (("attack_type", attack), ("weapon_type", weapon), ("target_type", target)):
        if val:
            w.append(f"e.{prop} = " + lit(val))
    if area:
        w.append("EXISTS { (e)-[:OCCURRED_IN]->(:Area {name: " + lit(area) + "}) }")
    if group:
        w.append("EXISTS { (e)-[:ATTRIBUTED_TO]->(:Group {name: " + lit(group) + "}) }")
    return w + list(extra)


def agg_count(unattributed=False, **f):
    extra = ["NOT EXISTS { (e)-[:ATTRIBUTED_TO]->(:Group) }"] if unattributed else []
    return ("MATCH (e:Event)\n" + where(_agg_where(extra=extra, **f), "\n  AND ")
            + "RETURN count(e) AS incidents\nLIMIT 1")


def agg_killed(fn="sum", **f):
    """Severity rule: computed in WITH, nkill IS NOT NULL. fn is 'sum' or 'avg' (avg is not rounded)."""
    w = _agg_where(extra=["e.nkill IS NOT NULL"], **f)
    name = "victims_killed" if fn == "sum" else "avg_victims_killed"
    return ("MATCH (e:Event)\n" + where(w, "\n  AND ")
            + "WITH e.nkill - coalesce(e.nkillter, 0) AS victims_killed\n"
            + f"RETURN {fn}(victims_killed) AS {name}\nLIMIT 1")


_DIM = {
    "area": ("MATCH (e:Event)-[:OCCURRED_IN]->(x:Area)\n", "x.name", "area"),
    "locality": ("MATCH (e:Event)-[:OCCURRED_AT]->(x:Locality)\n", "x.name", "locality"),
    "group": ("MATCH (e:Event)-[:ATTRIBUTED_TO]->(x:Group)\n", "x.name", "group"),
    "attack_type": ("MATCH (e:Event)-[:HAS_ATTACK_TYPE]->(x:AttackType)\n", "x.name", "attack_type"),
    "weapon_type": ("MATCH (e:Event)-[:USED_WEAPON]->(x:WeaponType)\n", "x.name", "weapon_type"),
    "target_type": ("MATCH (e:Event)-[:TARGETED]->(x:TargetType)\n", "x.name", "target_type"),
    "year": ("MATCH (e:Event)\n", "e.date.year", "year"),
    "month": ("MATCH (e:Event)\n", "e.date.month", "month"),
}


def agg_by(dim, order="key", limit=50, **f):
    """Incidents per value of dim. order: 'key' (by the value), 'top' (most first), 'bottom' (fewest first)."""
    match, expr, label = _DIM[dim]
    text = (match + where(_agg_where(**f), "\n  AND ")
            + f"RETURN {expr} AS {label}, count(e) AS incidents\n")
    if order == "top":
        text += f"ORDER BY incidents DESC, {label}\n"
    elif order == "bottom":
        text += f"ORDER BY incidents ASC, {label}\n"
    else:
        text += f"ORDER BY {label}\n"
    return text + f"LIMIT {limit}"