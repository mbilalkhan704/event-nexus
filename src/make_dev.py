"""
Builds the dev set (eval/dev.jsonl) and few-shot examples (eval/fewshot.jsonl).

Each question has a gold answer: an open-lane Cypher query (literals instead of parameters, LIMIT
added, no CALL), a FAST call, or a refusal. Slot values (areas, groups, years, events) come from
the live graph and every gold query is validated and executed here, so:
  - list questions return 1 to 49 rows (the gold LIMIT of 50 never cuts them),
  - top-N questions have no tie at the cut,
  - gold queries pass the same validator the models face.

    python src/make_dev.py
"""
import json
import os
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import qa_core
import validator
from config import get_driver, run

END = date(2020, 12, 22)
END_S = END.isoformat()
DEV_OUT, FEW_OUT = "eval/dev.jsonl", "eval/fewshot.jsonl"
FS_AREAS = {"Saddar"}                                          # used in few-shot examples, kept out of dev
FS_GROUPS = {"Jundallah (Pakistan)", "Lashkar-e-Jhangvi"}
SEV = ("victims_killed", "victims_wounded")

driver = get_driver()
NAMES = qa_core.load_names(driver)
rng = random.Random(7)


def db(text, **params):
    return run(driver, text, **params)


SHORT = {k: v for k, v in {
    "Lashkar-e-Jhangvi": "LeJ", "Al-Qaida in the Indian Subcontinent": "AQIS",
    "Muttahida Qami Movement (MQM)": "MQM", "Sindhudesh Revolutionary Army (SRA)": "SRA",
    "Sindhu Desh Liberation Army (SDLA)": "SDLA", "Baloch Liberation Army (BLA)": "BLA",
    "Balochistan Liberation United Front (BLUF)": "BLUF", "Tehrik-i-Taliban Pakistan (TTP)": "TTP",
}.items() if k in NAMES["Group"]}
ATTACK = {k: v for k, v in {"Bombing/Explosion": ("bombing", "bombings"),
                            "Armed Assault": ("armed assault", "armed assaults"),
                            "Assassination": ("assassination", "assassinations")}.items()
          if k in NAMES["AttackType"]}
WEAPON = {k: v for k, v in {"Firearms": "firearm", "Explosives": "explosives"}.items()
          if k in NAMES["WeaponType"]}
TARGET = {k: v for k, v in {
    "Police": "police", "Private Citizens & Property": "private citizens",
    "Religious Figures/Institutions": "religious targets", "Government (General)": "government targets",
    "Business": "businesses", "Educational Institution": "educational institutions",
    "Military": "military targets", "Transportation": "transport targets"}.items()
    if k in NAMES["TargetType"]}


def shuf(xs):
    xs = sorted(xs)
    rng.shuffle(xs)
    return xs


group_counts = {r["g"]: r["c"] for r in db(
    "MATCH (e:Event)-[:ATTRIBUTED_TO]->(g:Group) RETURN g.name AS g, count(e) AS c")}
area_counts = {r["a"]: r["c"] for r in db(
    "MATCH (e:Event)-[:OCCURRED_IN]->(a:Area) RETURN a.name AS a, count(e) AS c")}
GROUPS = [g for g, c in group_counts.items() if c >= 6 and g not in FS_GROUPS]
AREAS = [a for a, c in area_counts.items() if c >= 8 and a not in FS_AREAS]
YEARS = list(range(2003, 2020))
ref_pool = shuf(r["id"] for r in db(
    "MATCH (e:Event)-[:REPORTED_BY]->(:Source) WITH e, count(*) AS c WHERE c >= 2 "
    "RETURN e.eventid AS id LIMIT 300"))
src_pool = shuf(r["id"] for r in db(
    "MATCH (a:Event)-[:SAME_SOURCE]-(:Event) RETURN DISTINCT a.eventid AS id LIMIT 300"))
pair_pool = shuf((r["a"], r["b"]) for r in db(
    "MATCH (a:Event)-[:SAME_ACTOR_NEARBY|SAME_MO_LOCAL|FOLLOWED_BY|SAME_SOURCE]->(b:Event) "
    "RETURN DISTINCT a.eventid AS a, b.eventid AS b LIMIT 400"))


# ---------- gold query builders (open-lane forms of the library queries) ----------
def lit(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def dt(s):
    return f"date({lit(s)})"


def yr(y):
    return f"{y}-01-01", f"{y}-12-31"


def back(n):
    """Start of 'the last n years', counted back from the end of the data."""
    return (date(END.year - n, END.month, END.day) + timedelta(days=1)).isoformat()


def name(g, i):
    return SHORT.get(g, g) if i % 2 == 1 else g


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


# ---------- candidate checking ----------
@dataclass
class Spec:
    question: str
    gold: str
    events: int = 0
    refs: dict = field(default_factory=dict)
    topn: int = 0
    tiekeys: tuple = ()


def execute(gold, spec):
    chk = validator.validate_cypher(gold, spec.events, NAMES)
    if not chk.ok:
        raise SystemExit(f"GOLD FAILS THE VALIDATOR: {chk.problems}\n{gold}")
    params = {p: spec.refs[p] for p in chk.params}
    return qa_core.execute_readonly(driver, chk.query, params), chk.query, params


def problem(spec):
    (keys, rows), text, params = execute(spec.gold, spec)
    if spec.topn:
        if len(rows) != spec.topn:
            return f"top-{spec.topn} returned {len(rows)} rows"
        longer = re.sub(r"LIMIT\s+\d+\s*$", f"LIMIT {spec.topn + 1}", text)
        k2, r2 = qa_core.execute_readonly(driver, longer, params)
        if len(r2) > spec.topn:
            idx = [k2.index(k) for k in spec.tiekeys]

            def key(r):
                return tuple((r[i] or 0) if k2[i] == "victims_wounded" else r[i] for i in idx)

            if key(r2[spec.topn - 1]) == key(r2[spec.topn]):
                return "tie at the cut"
        return None
    if not rows:
        return "no rows"
    if len(rows) >= 50:
        return f"{len(rows)} rows reach the LIMIT of 50"
    return None


used = set()


def pick(cands, label):
    last = "no candidates"
    for spec in cands:
        if spec.question in used:
            continue
        last = problem(spec)
        if last is None:
            used.add(spec.question)
            return spec
    raise SystemExit(f"{label}: no valid candidate; last problem: {last}")


items = []


def add(query_id, phrasing, question, events, refs, expect, gold, topn=None):
    items.append({"id": f"d{len(items) + 1:03d}", "query_id": query_id, "phrasing": phrasing,
                  "question": question, "events": events, "refs": refs, "expect": expect,
                  "gold": gold, "topn": topn})


def add_spec(query_id, phrasing, spec):
    add(query_id, phrasing, spec.question, spec.events, spec.refs, "cypher", spec.gold, spec.topn or None)


# ---------- Q0b: the event finder (rankings) ----------
def g_q0b_1():
    for n in shuf([5, 3, 10, 7, 4]):
        for k in (5, 3):
            yield Spec(f"What were the {k} most severe incidents in the last {n} years?",
                       q0b("severity", k, d_from=back(n), d_to=END_S), topn=k, tiekeys=SEV)


def g_q0b_2():
    for a in shuf(AREAS):
        for atk, (_, plural) in ATTACK.items():
            yield Spec(f"What were the 3 deadliest {plural} in {a}?",
                       q0b("severity", 3, area=a, attack=atk), topn=3, tiekeys=SEV)


def g_q0b_3():
    for g in shuf(GROUPS):
        for k in (3, 5):
            yield Spec(f"Show the {k} most recent attacks by {name(g, 1)}.",
                       q0b("newest", k, group=g), topn=k, tiekeys=("date",))


def g_q0b_4():
    for y in shuf(YEARS):
        for k in (3, 5):
            yield Spec(f"Which {k} attacks in {y} hurt the most people?",
                       q0b("severity", k, *yr(y)), topn=k, tiekeys=SEV)


def g_q0b_5():
    combos = [(w, t) for w in WEAPON for t in TARGET]
    for w, t in shuf(combos):
        for k in (3, 4):
            yield Spec(f"List the {k} oldest {WEAPON[w]} attacks on {TARGET[t]}.",
                       q0b("oldest", k, weapon=w, target=t), topn=k, tiekeys=("date",))


# ---------- Q1, Q5, Q12: events taken from context ----------
Q1_TEXT = [("Tell me more about that attack.", 1), ("What are the sources for that incident?", 1),
           ("Give me the full details of the second one.", 3),
           ("Where exactly did that attack happen and who reported it?", 1),
           ("Show everything we know about the event I selected.", 1)]
Q5_TEXT = ["What else was reported alongside that attack?",
           "Which attacks were reported by the same news article as that one?",
           "Was that incident covered in the same article as any other attack?",
           "Show the events that share a news source with the selected attack.",
           "Which other attacks did the same reports mention as that one?"]
Q12_TEXT = ["Why are these two attacks linked?", "What connects the first and second incident?",
            "What is the link between these two events?", "Explain how the two selected events are related.",
            "On what grounds are these two incidents linked?"]


# ---------- Q2 to Q4: groups, campaigns, local method ----------
def g_q2(i):
    for g in shuf(GROUPS):
        gn = name(g, i)
        if i == 1:
            yield Spec(f"List all {gn} attacks.", q2(g))
        for y in shuf(YEARS):
            if i == 2:
                yield Spec(f"What did {gn} do since {y}?", q2(g, d_from=f"{y}-01-01"))
            elif i == 3:
                for y2 in (y + 1, y + 2):
                    yield Spec(f"Events by {gn} between {y} and {y2}.", q2(g, f"{y}-01-01", f"{y2}-12-31"))
            elif i == 4:
                yield Spec(f"Show every {gn} incident in {y}.", q2(g, *yr(y)))
            elif i == 5:
                yield Spec(f"{gn} activity before {y}.", q2(g, d_to=f"{y - 1}-12-31"))


def g_q3(i):
    if i in (1, 3, 4):
        for g in shuf(GROUPS):
            gn = name(g, i)
            for y in [None] + shuf(YEARS):
                span = f" in {y}" if y else ""
                rng_ = yr(y) if y else (None, None)
                if i == 1:
                    for gap in (30, 15, 7):
                        yield Spec(f"Which {gn} attacks happened within {gap} days of each other{span}?",
                                   q3(g, gap, *rng_))
                elif i == 3 and y:
                    yield Spec(f"Show campaigns by {gn} in {y}.", q3(g, 30, *rng_))
                elif i == 4:
                    for m in (2, 3):
                        yield Spec(f"Which {gn} attacks were within {m} months of each other{span}?",
                                   q3b(g, m * 30, *rng_))
    else:
        for y in shuf(YEARS):
            for m in (30, 2, 3) if i == 2 else (2, 3):
                if i == 2:
                    yield Spec(f"Show attack waves by any group in {y}, within {m} days.", q3(None, m, *yr(y)))
                else:
                    yield Spec(f"Show attacks by the same group within {m} months of each other in {y}.",
                               q3b(None, m * 30, *yr(y)))


def g_q4(i):
    if i in (1, 4):
        for a in shuf(AREAS):
            for atk, (_, plural) in ATTACK.items():
                if i == 1:
                    yield Spec(f"Repeated {plural} in {a}.", q4(30, area=a, attack=atk))
                else:
                    for m in (2, 3):
                        yield Spec(f"Repeated {plural} in {a} within {m} months.",
                                   q4(m * 30, area=a, attack=atk, computed=True))
    elif i == 2:
        for a in shuf(AREAS):
            for gap in (10, 7, 15):
                yield Spec(f"Same method used twice in {a} within {gap} days.", q4(gap, area=a))
    elif i == 3:
        for t in shuf(TARGET):
            for y in shuf(YEARS):
                yield Spec(f"Where were {TARGET[t]} hit the same way more than once in {y}?",
                           q4(30, target=t, d_from=f"{y}-01-01", d_to=f"{y}-12-31"))
    else:
        for w, t in shuf([(w, t) for w in WEAPON for t in TARGET]):
            for y in shuf(YEARS):
                yield Spec(f"Same {WEAPON[w]} attacks on {TARGET[t]} within 2 months of each other in {y}.",
                           q4(60, weapon=w, target=t, d_from=f"{y}-01-01", d_to=f"{y}-12-31", computed=True))


# ---------- Q6, Q7, Q9, Q11, Q13 ----------
def g_q6(i):
    for t in shuf(TARGET):
        tl = TARGET[t]
        if i == 1:
            for w in (15, 30, 7):
                yield Spec(f"Which groups attacked {tl} within {w} days of each other?", q6(w, t))
        else:
            for y in shuf(YEARS):
                if i == 4:
                    yield Spec(f"Which groups hit {tl} in {y} within 30 days of each other?", q6(30, t, *yr(y)))
                elif i == 5:
                    yield Spec(f"Which pairs of groups targeted {tl} within 2 months of each other "
                               f"between {y} and {y + 1}?", q6(60, t, f"{y}-01-01", f"{y + 1}-12-31"))
    if i == 2:
        for y in shuf(YEARS):
            for m in (2, 3):
                yield Spec(f"Groups that targeted the same kind of victim within {m} months in {y}.",
                           q6(m * 30, None, *yr(y)))
    if i == 3:
        for y in shuf(YEARS):
            yield Spec(f"Which groups hit the same target type in {y}?", q6(None, None, *yr(y)))


def g_q7(i):
    if i == 1:
        yield Spec("Which areas were hit by more than one group?", q7(2))
    for y in shuf(YEARS):
        if i == 2:
            yield Spec(f"Contested neighbourhoods since {y}.", q7(2, d_from=f"{y}-01-01"))
        elif i == 4:
            yield Spec(f"Which neighbourhoods saw attacks from several groups between {y} and {y + 2}?",
                       q7(2, f"{y}-01-01", f"{y + 2}-12-31"))
        elif i == 5:
            for n in (2, 3):
                yield Spec(f"Where were {n} or more groups active in {y}?", q7(n, *yr(y)))
    if i == 3:
        for n in (3, 4, 2):
            yield Spec(f"Areas attacked by at least {n} different groups.", q7(n))


def g_q9(i):
    if i == 1:
        for a in shuf(AREAS):
            yield Spec(f"Show escalation chains in {a}.", q9(area=a))
    elif i == 2:
        for k in range(1, 11):
            text = ("What is the longest run of attacks in the same area?" if k == 1
                    else f"What are the {k} longest runs of attacks in the same area?")
            yield Spec(text, q9(limit=k), topn=k, tiekeys=("events",))
    elif i == 3:
        for y in shuf(YEARS):
            yield Spec(f"Escalations in {y}.", q9(d_from=f"{y}-01-01", d_to=f"{y}-12-31"))
    elif i == 4:
        for a in shuf(AREAS):
            for y in shuf(YEARS):
                yield Spec(f"Show escalation chains in {a} in {y}.", q9(a, f"{y}-01-01", f"{y}-12-31"))
    else:
        for y in shuf(YEARS):
            for k in range(1, 7):
                text = (f"Which is the longest escalation chain between {y} and {y + 2}?" if k == 1
                        else f"Which are the {k} longest escalation chains between {y} and {y + 2}?")
                yield Spec(text, q9(None, f"{y}-01-01", f"{y + 2}-12-31", k),
                           topn=k, tiekeys=("events",))


Q11_TEXT = {1: ("area", "Which groups operate in at least {n} of the same areas?"),
            2: ("area", "Show how groups overlap by neighbourhood: pairs sharing {n} or more areas."),
            3: ("org", "Which groups have attacked {n} or more of the same organisations?"),
            4: ("org", "Which pairs of groups share at least {n} target organisations?"),
            5: ("area", "Which groups were active in {n} or more of the same neighbourhoods?")}


def g_q11(i):
    via, text = Q11_TEXT[i]
    for n in (2, 3, 4, 5, 1):
        yield Spec(text.format(n=n), q11("area" if via == "area" else "org", n))


def g_q13(i):
    for g in shuf(GROUPS):
        gn = name(g, i)
        if i == 1:
            yield Spec(f"How solid are the {gn} attributions?", q13_counts(g))
        elif i == 2:
            yield Spec(f"Which {gn} events were actually claimed?", q13_list(g, "claimed"))
        elif i == 3:
            yield Spec(f"Show the {gn} events that are only suspected.", q13_list(g, "suspected"))
        elif i == 4:
            yield Spec(f"Show suspected versus claimed events for {gn}.", q13_counts(g))
        else:
            yield Spec(f"Which {gn} attributions are neither claimed nor flagged as suspected?",
                       q13_list(g, "plain"))


# ---------- build the open-lane items ----------
for i, gen in enumerate([g_q0b_1, g_q0b_2, g_q0b_3, g_q0b_4, g_q0b_5], 1):
    add_spec("Q0b", i, pick(gen(), f"Q0b/{i}"))
for i, ((text, ev), ref) in enumerate(zip(Q1_TEXT, ref_pool), 1):
    add("Q1", i, text, ev, {"ref": ref}, "cypher", Q1_GOLD)
for qid, fn in (("Q2", g_q2), ("Q3", g_q3), ("Q4", g_q4)):
    for i in range(1, 6):
        add_spec(qid, i, pick(fn(i), f"{qid}/{i}"))
src_refs = iter(src_pool)
for i, text in enumerate(Q5_TEXT, 1):
    for ref in src_refs:
        spec = Spec(text, Q5_GOLD, 1, {"ref": ref})
        if problem(spec) is None:
            add_spec("Q5", i, spec)
            break
    else:
        raise SystemExit(f"Q5/{i}: no event with a usable SAME_SOURCE result")
for qid, fn in (("Q6", g_q6), ("Q7", g_q7), ("Q9", g_q9), ("Q11", g_q11)):
    for i in range(1, 6):
        add_spec(qid, i, pick(fn(i), f"{qid}/{i}"))
pairs = iter(pair_pool)
for i, text in enumerate(Q12_TEXT, 1):
    for a, b in pairs:
        spec = Spec(text, Q12_GOLD, 2, {"ref_a": a, "ref_b": b})
        if problem(spec) is None:
            add_spec("Q12", i, spec)
            break
    else:
        raise SystemExit(f"Q12/{i}: no linked pair with a usable result")
for i in range(1, 6):
    add_spec("Q13", i, pick(g_q13(i), f"Q13/{i}"))

# ---------- FAST items ----------
fast_refs = iter(ref_pool[10:])
Q8_TEXT = [("What is connected to that attack?", 1),
           ("Show everything within three links of that incident and why.", 1),
           ("What else is linked to this event, directly or indirectly?", 2),
           ("Trace the connections going out from the selected attack.", 1),
           ("Which events can be reached from that one, and through which links?", 1)]
Q10_TEXT = [("How are these two attacks connected?", 2), ("Find the link between the first and the third one.", 3),
            ("Is there any chain of links between these two events?", 2),
            ("What is the shortest connection between the two selected incidents?", 2),
            ("Connect the first and second event for me.", 2)]
Q14_TEXT = [("Find attacks like that one.", 1), ("What other incidents look similar to this one?", 1),
            ("Show the 5 most similar events and why.", 1), ("Which attacks resemble the selected one?", 1),
            ("Give me incidents with a similar description to that event.", 2)]
Q15_TEXT = ["Which unattributed attacks look like {g} attacks?", "Events that resemble {g} but have no group.",
            "Are there events with no group that resemble the {g} pattern?",
            "List unattributed events similar to the ones blamed on {g}.",
            "Show unattributed incidents that look like the work of {g}."]
for i, (text, ev) in enumerate(Q8_TEXT, 1):
    add("Q8", i, text, ev, {"ref": next(fast_refs)}, "fast", "Q8")
for i, (text, ev) in enumerate(Q10_TEXT, 1):
    a, b = next(pairs)
    add("Q10", i, text, ev, {"ref_a": a, "ref_b": b}, "fast", "Q10")
for i, (text, ev) in enumerate(Q14_TEXT, 1):
    add("Q14", i, text, ev, {"ref": next(fast_refs)}, "fast", "Q14")
for i, (text, g) in enumerate(zip(Q15_TEXT, shuf(GROUPS)), 1):
    add("Q15", i, text.format(g=name(g, i)), 0, {}, "fast", f"Q15 {g}")

# ---------- refusals ----------
REFUSALS = [
    ("How many attacks happened in Lahore in 2012?", 0, "not Karachi"),
    ("What was the deadliest attack in 1995?", 0, "before 2000"),
    ("Show me all attacks in 2023.", 0, "after 2020"),
    ("What is the weather in Karachi today?", 0, "off topic"),
    ("Delete all events from 2014.", 0, "write request"),
    ("Which attacks did Hamas carry out?", 0, "group not in the data"),
    ("What did the Taliban do in Karachi?", 0, "ambiguous group"),
    ("Predict where the next attack will happen.", 0, "outside the data"),
    ("Tell me more about that attack.", 0, "no event in context"),
    ("Find attacks like that one.", 0, "no event in context"),
    ("How are these two attacks connected?", 0, "no events in context"),
    ("How are the first two attacks connected?", 1, "only one event in context"),
    ("Which events were attributed to Al-Shabaab?", 0, "group not in the data"),
    ("Show attacks between 1990 and 1999.", 0, "before 2000"),
    ("Who will win the next election?", 0, "off topic"),
]
for i, (text, ev, why) in enumerate(REFUSALS, 1):
    add("REFUSE", i, text, ev, {}, "refuse", None)
    items[-1]["note"] = why

# ---------- few-shot examples ----------
FEWSHOT = [
    ("What were the 3 most severe attacks in the last 3 years?", 0,
     "CYPHER: " + q0b("severity", 3, d_from=back(3), d_to=END_S)),
    ("List the Jundallah attacks between 2010 and 2012.", 0,
     "CYPHER: " + q2("Jundallah (Pakistan)", "2010-01-01", "2012-12-31")),
    ("How many bombings were there in Saddar?", 0,
     "CYPHER: MATCH (e:Event)-[:OCCURRED_IN]->(:Area {name: 'Saddar'})\n"
     "WHERE e.attack_type = 'Bombing/Explosion'\nRETURN count(e) AS events\nLIMIT 1"),
    ("What happened near I.I. Chundrigar Road?", 0,
     "CYPHER: MATCH (e:Event)\nWHERE toLower(e.location) CONTAINS toLower('chundrigar')\n"
     "   OR toLower(e.summary_clean) CONTAINS toLower('chundrigar')\n"
     "RETURN e.eventid AS _ref, e.date AS date, 'text' AS place_match\nORDER BY e.date\nLIMIT 50"),
    ("How many attacks targeted the Rangers?", 0,
     "CYPHER: MATCH (e:Event)-[:TARGETED_ORG]->(o:TargetOrg)\nWHERE toLower(o.name) CONTAINS toLower('rangers')\n"
     "RETURN o.name AS org_name, 'text' AS org_match, count(e) AS events\nORDER BY events DESC\nLIMIT 50"),
    ("Find attacks similar to this one.", 1, "FAST: Q14"),
    ("Show attacks in 1996.", 0, "REFUSE: The data covers 2000 to 2020, so there is nothing for 1996."),
    ("Which unattributed events look like LeJ attacks?", 0, "FAST: Q15 Lashkar-e-Jhangvi"),
]
for text, ev, reply in FEWSHOT:
    if reply.startswith("CYPHER: "):
        chk = validator.validate_cypher(reply[8:], ev, NAMES)
        if not chk.ok:
            raise SystemExit(f"FEW-SHOT FAILS THE VALIDATOR: {chk.problems}\n{reply}")
        qa_core.execute_readonly(driver, chk.query, {})

# ---------- write ----------
os.makedirs("eval", exist_ok=True)
with open(DEV_OUT, "w", encoding="utf-8") as f:
    for it in items:
        f.write(json.dumps(it, ensure_ascii=False) + "\n")
with open(FEW_OUT, "w", encoding="utf-8") as f:
    for text, ev, reply in FEWSHOT:
        f.write(json.dumps({"question": text, "events": ev, "reply": reply}, ensure_ascii=False) + "\n")
driver.close()

print(f"wrote {len(items)} dev items to {DEV_OUT} and {len(FEWSHOT)} few-shot examples to {FEW_OUT}")
print("by expected output:", dict(Counter(it["expect"] for it in items)))
print("by query:", dict(Counter(it["query_id"] for it in items)))
assert len({it["question"] for it in items if it["expect"] == "cypher"}) == sum(
    it["expect"] == "cypher" for it in items), "duplicate cypher questions"
