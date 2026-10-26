"""
Builds the training pairs (question + CONTEXT line -> reply) for the QLoRA fine-tune.

    python src/make_pairs.py        # writes train/pairs_raw.jsonl
    python src/filter_pairs.py      # overlap filter against dev and test -> train/pairs.jsonl

Every CYPHER reply passes the validator and runs read-only with at least one row. The question
phrasings are written for training (not the dev wording); filter_pairs.py removes any that are
still too close to a dev or test question. Slot values come from the live graph.
"""
import json
import os
import random
import re
from collections import Counter
from datetime import date, timedelta

from neo4j.exceptions import Neo4jError

import qa_core
import validator
from config import get_driver, run
from gold import (END, END_S, Q1_GOLD, Q5_GOLD, Q12_GOLD, agg_by, agg_count, agg_killed, back, lit,
                  one, q0b, q2, q3, q3b, q4, q6, q7, q9, q11, q13_counts, q13_list, where, yr)

OUT = "train/pairs_raw.jsonl"
rng = random.Random(11)
driver = get_driver()
NAMES = qa_core.load_names(driver)


def db(text, **params):
    return run(driver, text, **params)


# ---------- slot pools ----------
group_counts = {r["g"]: r["c"] for r in db(
    "MATCH (e:Event)-[:ATTRIBUTED_TO]->(g:Group) RETURN g.name AS g, count(e) AS c")}
area_counts = {r["a"]: r["c"] for r in db(
    "MATCH (e:Event)-[:OCCURRED_IN]->(a:Area) RETURN a.name AS a, count(e) AS c")}
loc_counts = {r["l"]: r["c"] for r in db(
    "MATCH (e:Event)-[:OCCURRED_AT]->(l:Locality) RETURN l.name AS l, count(e) AS c")}
# names with an apostrophe are skipped: the validator compares the escaped text with the list
GROUPS = sorted(g for g, c in group_counts.items() if c >= 1 and "'" not in g)
AREAS = sorted(a for a, c in area_counts.items() if c >= 1 and "'" not in a)
LOCALITIES = sorted(l for l in loc_counts if "'" not in l)
KH = "Khorasan Chapter of the Islamic State"
GROUP_ALIASES = {k: v for k, v in {
    "Lashkar-e-Jhangvi": ["LeJ"], "Al-Qaida in the Indian Subcontinent": ["AQIS"],
    "Al-Qaida": ["Al Qaeda"], KH: ["ISIS", "Daesh", "ISKP", "Islamic State"],
    "Tehrik-i-Taliban Pakistan (TTP)": ["TTP", "Taliban Pakistan"],
    "Muttahida Qami Movement (MQM)": ["MQM"], "Sindhudesh Revolutionary Army (SRA)": ["SRA"],
    "Sindhu Desh Liberation Army (SDLA)": ["SDLA"], "Baloch Liberation Army (BLA)": ["BLA"],
    "Balochistan Liberation United Front (BLUF)": ["BLUF"]}.items() if k in NAMES["Group"]}
AREA_ALIASES = {k: v for k, v in {
    "Defence Housing Authority": ["DHA", "Defence", "Defense"], "Gulshan-e-Iqbal": ["Gulshan", "Gulshan Iqbal"],
    "Gulistan-e-Jauhar": ["Gulistan-e-Johar"], "Lyari": ["Layari"], "Saddar": ["Sadar"],
    "Keamari": ["Kiamari"], "Mauripur": ["Maripur"], "Liaquatabad": ["Liaqatabad"],
    "Pirabad": ["Peerabad"]}.items() if k in NAMES["Area"]}

ATTACK = {k: v for k, v in {
    "Bombing/Explosion": ("bombing", "bombings"), "Armed Assault": ("armed assault", "armed assaults"),
    "Assassination": ("assassination", "assassinations"),
    "Hostage Taking (Kidnapping)": ("kidnapping", "kidnappings"),
    "Facility/Infrastructure Attack": ("attack on a facility", "attacks on facilities"),
    "Unarmed Assault": ("unarmed assault", "unarmed assaults")}.items() if k in NAMES["AttackType"]}
WEAPON = {k: v for k, v in {"Firearms": "firearm", "Explosives": "explosive",
                            "Incendiary": "incendiary", "Melee": "melee"}.items() if k in NAMES["WeaponType"]}
TARGET = {k: v for k, v in {
    "Police": "police", "Private Citizens & Property": "private citizens",
    "Religious Figures/Institutions": "religious targets", "Government (General)": "government targets",
    "Business": "businesses", "Educational Institution": "educational institutions",
    "Military": "military targets", "Transportation": "transport targets",
    "Journalists & Media": "journalists", "Violent Political Party": "political party targets",
    "Telecommunication": "telecom targets", "NGO": "NGOs"}.items() if k in NAMES["TargetType"]}
SPAN = {7: "a week", 10: "10 days", 14: "two weeks", 15: "15 days", 20: "20 days", 30: "30 days",
        45: "45 days", 60: "2 months", 90: "3 months", 120: "4 months", 180: "6 months"}

ref_pool = [r["id"] for r in db(
    "MATCH (e:Event)-[:REPORTED_BY]->(:Source) WITH e, count(*) AS c WHERE c >= 2 "
    "RETURN e.eventid AS id LIMIT 300")]
src_pool = [r["id"] for r in db(
    "MATCH (a:Event)-[:SAME_SOURCE]-(:Event) RETURN DISTINCT a.eventid AS id LIMIT 300")]
pair_pool = [(r["a"], r["b"]) for r in db(
    "MATCH (a:Event)-[:SAME_ACTOR_NEARBY|SAME_MO_LOCAL|FOLLOWED_BY|SAME_SOURCE]->(b:Event) "
    "RETURN DISTINCT a.eventid AS a, b.eventid AS b LIMIT 400")]

# road and landmark names for the text fallback: (name as typed, distinctive word for CONTAINS)
_SUFFIX = "Road|Chowk|Bridge|Market|Highway|Park|University|Square|Hospital|Street|Chowrangi|Stadium|Terminal|Station|Court|Plaza|Mall"
_ROAD = re.compile(r"([A-Z][A-Za-z\.\-']*(?: [A-Z][A-Za-z\.\-']*){0,3}) (" + _SUFFIX + r")\b")
_LEAD = {"The", "On", "In", "At", "Near", "Outside", "Along", "Across", "From", "Inside", "Opposite"}
ROADS = {}
for r in db("MATCH (e:Event) WHERE e.location IS NOT NULL RETURN e.location AS t"):
    for m in _ROAD.finditer(r["t"]):
        words = m.group(1).split()
        while words and words[0] in _LEAD:
            words.pop(0)
        if not words or "'" in m.group(0):
            continue
        core = " ".join(words)
        tokens = sorted(re.findall(r"[A-Za-z]{4,}", core), key=len, reverse=True)
        if tokens:
            ROADS[f"{core} {m.group(2)}"] = tokens[0].lower()
ROADS = sorted(ROADS.items())

_STOP = {"pakistan", "pakistani", "karachi", "government", "police", "office", "ministry", "department",
         "company", "limited", "private", "national", "international", "public", "school", "college",
         "hospital", "services", "service", "corporation", "authority", "association", "center", "centre",
         "forces", "military", "bank"}
ORGS, _seen_w = [], set()
for r in db("MATCH (e:Event)-[:TARGETED_ORG]->(o:TargetOrg) RETURN o.name AS n, count(e) AS c "
            "ORDER BY c DESC LIMIT 120"):
    if "'" in r["n"]:
        continue
    word = next((t.lower() for t in re.findall(r"[A-Za-z]{6,}", re.sub(r"\(.*?\)", "", r["n"]))
                 if t.lower() not in _STOP), None)
    if word and word not in _seen_w:
        _seen_w.add(word)
        ORGS.append((re.sub(r"\s*\(.*?\)", "", r["n"]).strip(), word))


# ---------- small helpers ----------
def back_months(n):
    y, m = END.year, END.month - n
    while m <= 0:
        m += 12
        y -= 1
    return (date(y, m, END.day) + timedelta(days=1)).isoformat()


def ry(lo=2001, hi=2020):
    return rng.randint(lo, hi)


def gdisp(g):
    forms = [g] + GROUP_ALIASES.get(g, [])
    return g if rng.random() < 0.5 else rng.choice(forms)


def adisp(a):
    return rng.choice(AREA_ALIASES[a]) if a in AREA_ALIASES and rng.random() < 0.35 else a


def ctx(minimum=0):
    if minimum == 0:
        return 0 if rng.random() < 0.5 else rng.randint(1, 10)
    return rng.randint(minimum, minimum + rng.choice([0, 0, 1, 2, 4]))


def style(q):
    r = rng.random()
    if r < 0.12:
        return q.lower().rstrip(".?!")
    if r < 0.22:
        return q.rstrip(".?!")
    return q


# ---------- collecting pairs ----------
pairs, seen, skipped = [], set(), Counter()
shown = 0


def add_pair(qid, kind, question, events, reply):
    key = (question.lower(), events)
    if key in seen:
        skipped["duplicate"] += 1
        return False
    seen.add(key)
    pairs.append({"id": f"t{len(pairs) + 1:04d}", "query_id": qid, "type": kind,
                  "question": question, "events": events, "reply": reply})
    return True


def try_cypher(qid, question, gold, events, refs=None):
    global shown
    if (question.lower(), events) in seen:
        skipped["duplicate"] += 1
        return False
    chk = validator.validate_cypher(gold, events, NAMES)
    if not chk.ok:
        skipped[f"{qid} invalid"] += 1
        if shown < 12:
            shown += 1
            print("INVALID", qid, question, chk.problems[:2])
        return False
    try:
        params = {p: (refs or {})[p] for p in chk.params}
        keys, rows = qa_core.execute_readonly(driver, chk.query, params)
    except (KeyError, Neo4jError):
        skipped[f"{qid} error"] += 1
        return False
    if not rows or validator.exposed_id_columns(keys, rows):
        skipped[f"{qid} empty or exposes ids"] += 1
        return False
    return add_pair(qid, "cypher", question, events, "CYPHER: " + gold)


def fill(qid, target, make):
    got = tries = 0
    while got < target and tries < target * 60:
        tries += 1
        out = make()
        if out is None:
            continue
        q, gold, *rest = out
        refs = rest[0] if rest else None
        need = rest[1] if len(rest) > 1 else 0
        if try_cypher(qid, style(q), gold, ctx(need), refs):
            got += 1
    if got < target:
        print(f"WARNING {qid}: {got}/{target}")


# ---------- open-lane makers ----------
def m_q0b():
    k = rng.choice([3, 3, 4, 5, 5, 6, 8, 10])
    n, mo = rng.choice([2, 3, 4, 5, 6, 8, 10]), rng.choice([3, 6, 9, 12, 18, 24, 36])
    a = rng.choice(AREAS); ad = adisp(a)
    g = rng.choice(GROUPS); gd = gdisp(g)
    atk = rng.choice(list(ATTACK)); plur = ATTACK[atk][1]
    w, t = rng.choice(list(WEAPON)), rng.choice(list(TARGET))
    y = ry(); y1 = ry(2001, 2018); y2 = min(2020, y1 + rng.randint(1, 3))
    v = rng.randrange(13)
    if v == 0:
        return (rng.choice([f"Give me the {k} deadliest attacks of the past {n} years.",
                            f"Which {k} incidents killed the most victims in the last {n} years?",
                            f"Top {k} most severe attacks over the last {n} years."]),
                q0b("severity", k, d_from=back(n), d_to=END_S))
    if v == 1:
        return (f"What were the {k} worst incidents in the last {mo} months?",
                q0b("severity", k, d_from=back_months(mo), d_to=END_S))
    if v == 2:
        return (rng.choice([f"What are the {k} worst {plur} in {ad}?",
                            f"Show the {k} most severe {plur} that hit {ad}.", f"{ad}: {k} deadliest {plur}."]),
                q0b("severity", k, area=a, attack=atk))
    if v == 3:
        return (rng.choice([f"Latest {k} incidents attributed to {gd}.", f"What were {gd}'s {k} newest attacks?",
                            f"List the {k} most recent {gd} attacks."]),
                q0b("newest", k, group=g))
    if v == 4:
        return (rng.choice([f"Rank the {k} bloodiest incidents of {y}.",
                            f"In {y}, which {k} attacks killed the most people?",
                            f"Top {k} deadliest attacks during {y}."]),
                q0b("severity", k, *yr(y)))
    if v == 5:
        return (f"What are the earliest {k} {WEAPON[w]} attacks on {TARGET[t]}?",
                q0b("oldest", k, weapon=w, target=t))
    if v == 6:
        return (f"The {k} most recent {WEAPON[w]} attacks on {TARGET[t]}.", q0b("newest", k, weapon=w, target=t))
    if v == 7:
        return (rng.choice([f"{k} most severe incidents in {ad}.", f"What were the worst {k} attacks to hit {ad}?"]),
                q0b("severity", k, area=a))
    if v == 8:
        return (rng.choice([f"{gd}'s deadliest {k} attacks.", f"Which {k} {gd} attacks killed the most people?"]),
                q0b("severity", k, group=g))
    if v == 9:
        return (f"Deadliest {k} attacks on {TARGET[t]} between {y1} and {y2}.",
                q0b("severity", k, *(f"{y1}-01-01", f"{y2}-12-31"), target=t))
    if v == 10:
        return f"The first {k} attacks recorded in {ad}.", q0b("oldest", k, area=a)
    if v == 11:
        return f"Which {k} {plur} in {y} were the deadliest?", q0b("severity", k, *yr(y), attack=atk)
    return (rng.choice([f"Top {k} deadliest attacks in Karachi.", f"The {k} most severe incidents in Sindh.",
                        f"Show the {k} worst attacks in the whole city."]), q0b("severity", k))


def m_q0b_one():
    a = rng.choice(AREAS); ad = adisp(a)
    g = rng.choice(GROUPS); gd = gdisp(g)
    atk = rng.choice(list(ATTACK)); sing = ATTACK[atk][0]
    t = rng.choice(list(TARGET)); y = ry(); n = rng.choice([2, 3, 5, 7, 10])
    v = rng.randrange(10)
    if v == 0:
        return f"What was the single deadliest attack in {ad}?", q0b("severity", 1, area=a)
    if v == 1:
        return f"What was the worst {sing} in {ad}?", q0b("severity", 1, area=a, attack=atk)
    if v == 2:
        return f"Which was the most severe incident of {y}?", q0b("severity", 1, *yr(y))
    if v == 3:
        return f"What is the most recent attack by {gd}?", q0b("newest", 1, group=g)
    if v == 4:
        return f"When did {gd} first strike?", q0b("oldest", 1, group=g)
    if v == 5:
        return "What was the deadliest attack in Karachi?", q0b("severity", 1)
    if v == 6:
        return "What was the most recent attack in the data?", q0b("newest", 1)
    if v == 7:
        return f"Which attack in the last {n} years had the most victims?", q0b("severity", 1, d_from=back(n), d_to=END_S)
    if v == 8:
        return f"What was the deadliest attack on {TARGET[t]}?", q0b("severity", 1, target=t)
    return f"What was the first attack recorded in {ad}?", q0b("oldest", 1, area=a)


Q1_T = [("Open that incident and show its details.", 1), ("What do the sources say about the attack I just clicked?", 1),
        ("Pull up the full record for the third one.", 3), ("Who reported that event and where did it happen?", 1),
        ("I want the complete details of the first attack in the list.", 1), ("Show me everything on the last one.", 2),
        ("More information on the attack above, please.", 1), ("Details of the fourth incident.", 4),
        ("Which news reports cover that attack?", 1), ("Expand on the highlighted event.", 1),
        ("Give me the summary, place and casualties of this incident.", 1), ("Describe the second attack in detail.", 2)]
Q5_T = ["Did any other attack get mentioned in the same news story as that one?",
        "Find events reported by the same sources as the attack I selected.",
        "Other incidents sharing a citation with this event?", "Which events cite the same articles as that attack?",
        "Is that event covered by the same reports as any other?", "Show attacks sharing sources with the one I clicked.",
        "Any incidents reported together with this one?", "What other events appear in the same coverage as that incident?"]
Q12_T = ["How do the first two incidents relate?", "Are these two events linked, and if so how?",
         "Why do these two events appear connected?", "Tell me the relationship between the selected pair.",
         "Is there a direct link between the first and the second event?", "What kind of link joins these two incidents?",
         "What ties these two attacks together?", "What links these two attacks?", "What is the reason these events are linked?"]


def m_q1():
    t, need = rng.choice(Q1_T)
    return t, Q1_GOLD, {"ref": rng.choice(ref_pool)}, need


def m_q5():
    return rng.choice(Q5_T), Q5_GOLD, {"ref": rng.choice(src_pool)}, 1


def m_q12():
    a, b = rng.choice(pair_pool)
    return rng.choice(Q12_T), Q12_GOLD, {"ref_a": a, "ref_b": b}, 2


def m_q2():
    g = rng.choice(GROUPS); gd = gdisp(g); y = ry(); y1 = ry(2001, 2018); y2 = min(2020, y1 + rng.randint(1, 3))
    n = rng.choice([2, 3, 5, 8])
    v = rng.randrange(6)
    if v == 0:
        return (rng.choice([f"What attacks are attributed to {gd}?", f"Everything {gd} has been blamed for.",
                            f"Chronology of {gd} attacks.", f"Which incidents are linked to {gd}?"]), q2(g))
    if v == 1:
        return rng.choice([f"Incidents linked to {gd} in {y}.", f"What did {gd} carry out during {y}?"]), q2(g, *yr(y))
    if v == 2:
        return (rng.choice([f"{gd} events from {y1} to {y2}.", f"Attacks by {gd} between {y1} and {y2}."]),
                q2(g, f"{y1}-01-01", f"{y2}-12-31"))
    if v == 3:
        return (rng.choice([f"Has {gd} been active since {y}?", f"What has {gd} done from {y} onwards?"]),
                q2(g, d_from=f"{y}-01-01"))
    if v == 4:
        return f"{gd} activity prior to {y}.", q2(g, d_to=f"{y - 1}-12-31")
    return f"Attacks by {gd} in the last {n} years.", q2(g, d_from=back(n), d_to=END_S)


def m_q3():
    g = rng.choice(GROUPS); gd = gdisp(g); y = ry()
    if rng.random() < 0.55:
        gap = rng.choice([7, 10, 14, 15, 20, 30]); sp = SPAN[gap]
        v = rng.randrange(5)
        if v == 0:
            return f"Did {gd} strike repeatedly within {sp}?", q3(g, gap)
        if v == 1:
            return f"Show {gd} attacks that came within {sp} of one another in {y}.", q3(g, gap, *yr(y))
        if v == 2:
            return f"Which {gd} attacks formed a wave within {sp}?", q3(g, gap)
        if v == 3:
            return f"Which groups carried out attacks within {sp} of each other?", q3(None, gap)
        return f"Attack waves by a single group within {sp} in {y}.", q3(None, gap, *yr(y))
    gap = rng.choice([45, 60, 90, 120, 180]); sp = SPAN[gap]
    v = rng.randrange(3)
    if v == 0:
        return f"Pairs of {gd} attacks less than {sp} apart.", q3b(g, gap)
    if v == 1:
        return f"Same-group attacks within {sp} of each other in {y}.", q3b(None, gap, *yr(y))
    return f"Did {gd} attack again within {sp} of an earlier attack?", q3b(g, gap)


def m_q4():
    a = rng.choice(AREAS); ad = adisp(a)
    atk = rng.choice(list(ATTACK)); plur = ATTACK[atk][1]
    w, t = rng.choice(list(WEAPON)), rng.choice(list(TARGET))
    y = ry(); gap = rng.choice([7, 10, 14, 15, 20, 30]); sp = SPAN[gap]
    big = rng.choice([45, 60, 90, 120]); bp = SPAN[big]
    v = rng.randrange(7)
    if v == 0:
        return f"Where was the same method repeated within {sp}?", q4(gap)
    if v == 1:
        return f"In {ad}, was the same kind of attack carried out again within {sp}?", q4(gap, area=a)
    if v == 2:
        return f"Repeat {plur} in {ad} in {y}.", q4(30, area=a, attack=atk, d_from=f"{y}-01-01", d_to=f"{y}-12-31")
    if v == 3:
        return f"Where were {TARGET[t]} hit in the same way twice within {sp}?", q4(gap, target=t)
    if v == 4:
        return f"Same {WEAPON[w]} attacks on {TARGET[t]} within {bp} of each other.", q4(big, weapon=w, target=t, computed=True)
    if v == 5:
        return f"Repeat {plur} in {ad} within {bp}.", q4(big, area=a, attack=atk, computed=True)
    return f"Did the same method strike {ad} again within {sp}?", q4(gap, area=a)


def m_q6():
    t = rng.choice(list(TARGET)); tl = TARGET[t]; y = ry()
    win = rng.choice([7, 15, 30, 60, 90]); sp = SPAN[win]
    v = rng.randrange(6)
    if v == 0:
        return f"Which groups attacked {tl} within {sp} of each other?", q6(win, t)
    if v == 1:
        return f"Pairs of groups that hit {tl} close together in time, within {sp}.", q6(win, t)
    if v == 2:
        return f"Which different groups struck the same type of target within {sp} in {y}?", q6(win, None, *yr(y))
    if v == 3:
        return f"Groups that targeted {tl} in {y} within {sp}.", q6(win, t, *yr(y))
    if v == 4:
        return f"Which groups have gone after {tl}?", q6(None, t)
    return f"Which groups have gone after the same kind of target in {y}?", q6(None, None, *yr(y))


def m_q7():
    n = rng.choice([2, 2, 3, 4]); y = ry(); y1 = ry(2001, 2018); y2 = min(2020, y1 + rng.randint(1, 4))
    v = rng.randrange(5)
    if v == 0:
        return f"Which areas have seen attacks by {n} or more groups?", q7(n)
    if v == 1:
        return f"Neighbourhoods contested by several groups since {y}.", q7(2, d_from=f"{y}-01-01")
    if v == 2:
        return f"Where did at least {n} groups operate in {y}?", q7(n, *yr(y))
    if v == 3:
        return f"Which neighbourhoods were hit by multiple groups between {y1} and {y2}?", q7(2, f"{y1}-01-01", f"{y2}-12-31")
    return f"List the areas where {n} different groups have struck.", q7(n)


def m_q9():
    k = rng.choice([2, 3, 5, 8, 10]); a = rng.choice(AREAS); ad = adisp(a)
    y = ry(); y1 = ry(2001, 2018); y2 = min(2020, y1 + rng.randint(1, 4))
    v = rng.randrange(5)
    if v == 0:
        return f"Show the {k} longest escalation chains.", q9(limit=k)
    if v == 1:
        return f"Longest chains of events in {ad}.", q9(area=a)
    if v == 2:
        return f"What escalation sequences began in {y}?", q9(d_from=f"{y}-01-01", d_to=f"{y}-12-31")
    if v == 3:
        return f"Longest runs of attacks between {y1} and {y2}.", q9(None, f"{y1}-01-01", f"{y2}-12-31", k)
    return f"Chains of attacks in {ad} during {y}.", q9(a, *yr(y))


def m_q11():
    n = rng.choice([1, 2, 3, 4, 5]); v = rng.randrange(4)
    if v == 0:
        return f"Which pairs of groups were active in {n} or more of the same areas?", q11("area", n)
    if v == 1:
        return f"Groups that overlap geographically: at least {n} shared neighbourhoods.", q11("area", n)
    if v == 2:
        return f"Which groups hit {n} or more of the same organisations?", q11("org", n)
    return f"Pairs of groups with {n} or more common target organisations.", q11("org", n)


def m_q13():
    g = rng.choice(GROUPS); gd = gdisp(g); v = rng.randrange(5)
    if v == 0:
        return f"How reliable is the attribution of {gd} events?", q13_counts(g)
    if v == 1:
        return f"How many {gd} events were claimed versus suspected?", q13_counts(g)
    if v == 2:
        return f"Which attacks did {gd} claim itself?", q13_list(g, "claimed")
    if v == 3:
        return f"Which attacks are only suspected to be {gd}'s?", q13_list(g, "suspected")
    return f"Which {gd} attributions have no claim and no suspicion flag?", q13_list(g, "plain")


def locality_list(l, d_from=None, d_to=None):
    return ("MATCH (e:Event)-[:OCCURRED_AT]->(:Locality {name: " + lit(l) + "})\n"
            + where(one("e", d_from, d_to)) + "RETURN e.eventid AS _ref, e.date AS date\nORDER BY e.date\nLIMIT 50")


def area_list(a, d_from=None, d_to=None):
    return ("MATCH (e:Event)-[:OCCURRED_IN]->(:Area {name: " + lit(a) + "})\n"
            + where(one("e", d_from, d_to)) + "RETURN e.eventid AS _ref, e.date AS date\nORDER BY e.date\nLIMIT 50")


def place_text(word):
    return ("MATCH (e:Event)\nWHERE toLower(e.location) CONTAINS toLower(" + lit(word) + ")\n"
            "   OR toLower(e.summary_clean) CONTAINS toLower(" + lit(word) + ")\n"
            "RETURN e.eventid AS _ref, e.date AS date, 'text' AS place_match\nORDER BY e.date\nLIMIT 50")


def org_text(word, d_from=None, d_to=None):
    w = ["toLower(o.name) CONTAINS toLower(" + lit(word) + ")"] + one("e", d_from, d_to)
    return ("MATCH (e:Event)-[:TARGETED_ORG]->(o:TargetOrg)\n" + where(w, "\n  AND ")
            + "RETURN e.eventid AS _ref, e.date AS date, o.name AS org_name, " + lit(word)
            + " AS org_match\nORDER BY e.date\nLIMIT 50")


def m_loc():
    l = rng.choice(LOCALITIES); y = ry(); v = rng.randrange(4)
    if v == 0:
        return f"What happened in {l}?", locality_list(l)
    if v == 1:
        return f"Show the attacks in {l}.", locality_list(l)
    if v == 2:
        return f"Incidents at {l}.", locality_list(l)
    return f"{l} incidents since {y}.", locality_list(l, d_from=f"{y}-01-01")


def m_area():
    a = rng.choice(AREAS); ad = adisp(a); y = ry(); v = rng.randrange(4)
    if v == 0:
        return f"What attacks took place in {ad}?", area_list(a)
    if v == 1:
        return f"Show incidents in {ad} during {y}.", area_list(a, *yr(y))
    if v == 2:
        return f"List the events in {ad} since {y}.", area_list(a, d_from=f"{y}-01-01")
    return f"Which incidents were recorded in {ad}?", area_list(a)


def m_place():
    name, word = rng.choice(ROADS)
    return (rng.choice([f"What happened near {name}?", f"Show attacks on or around {name}.",
                        f"Any incidents at {name}?", f"Which attacks took place at {name}?"]), place_text(word))


def m_org():
    name, word = rng.choice(ORGS); y = ry(); v = rng.randrange(4)
    if v == 0:
        return f"Which attacks targeted {name}?", org_text(word)
    if v == 1:
        return f"Show attacks on {name}.", org_text(word)
    if v == 2:
        return f"Incidents where {name} was the target since {y}.", org_text(word, d_from=f"{y}-01-01")
    return f"Attacks against {name}.", org_text(word)


def _yr(n):
    d_from, d_to = yr(n)
    return {"d_from": d_from, "d_to": d_to}


def m_agg():
    y = ry(); y1 = ry(2001, 2016); y2 = min(2020, y1 + rng.randint(2, 4))
    a = rng.choice(AREAS); ad = adisp(a)
    g = rng.choice(GROUPS); gd = gdisp(g)
    atk = rng.choice(list(ATTACK)); plur = ATTACK[atk][1]
    w = rng.choice(list(WEAPON)); wl = WEAPON[w]
    t = rng.choice(list(TARGET)); tl = TARGET[t]
    k = rng.choice([3, 5, 5, 10])
    rg = {"d_from": f"{y1}-01-01", "d_to": f"{y2}-12-31"}
    v = rng.randrange(26)
    if v == 0:
        return rng.choice([f"How many incidents were there in {y}?", f"Number of attacks recorded in {y}.",
                           f"Count the incidents in {y}."]), agg_count(**_yr(y))
    if v == 1:
        return rng.choice([f"How many incidents happened in {ad}?", f"Number of attacks in {ad}.",
                           f"How many times was {ad} hit?"]), agg_count(area=a)
    if v == 2:
        return rng.choice([f"How many attacks are attributed to {gd}?", f"Number of incidents blamed on {gd}.",
                           f"How many incidents did {gd} carry out?"]), agg_count(group=g)
    if v == 3:
        return f"How many {plur} were there in {ad}?", agg_count(area=a, attack=atk)
    if v == 4:
        return f"How many {plur} happened in {y}?", agg_count(attack=atk, **_yr(y))
    if v == 5:
        return rng.choice([f"How many attacks targeted {tl}?", f"Number of incidents against {tl}."]), agg_count(target=t)
    if v == 6:
        return f"How many incidents involved {wl} weapons in {y}?", agg_count(weapon=w, **_yr(y))
    if v == 7:
        return rng.choice(["How many incidents have no known perpetrator?",
                           "Number of unattributed attacks."]), agg_count(unattributed=True)
    if v == 8:
        return f"How many attacks in {y} have no group attributed?", agg_count(unattributed=True, **_yr(y))
    if v == 9:
        return rng.choice([f"What was the total number of victims killed in {y}?",
                           f"Total deaths among victims in {y}."]), agg_killed("sum", **_yr(y))
    if v == 10:
        return f"Total number of people killed in {ad}.", agg_killed("sum", area=a)
    if v == 11:
        return f"How many people did {gd} kill in total?", agg_killed("sum", group=g)
    if v == 12:
        return rng.choice(["What is the average number of victims killed per incident?",
                           "On average, how many people die in an attack?"]), agg_killed("avg")
    if v == 13:
        return f"Average number killed per attack in {y}.", agg_killed("avg", **_yr(y))
    if v == 14:
        return f"Incidents per year from {y1} to {y2}.", agg_by("year", **rg)
    if v == 15:
        return rng.choice(["Break down incidents by attack type.", f"Number of incidents of each attack type in {y}."]), \
            agg_by("attack_type", order="top", **(_yr(y) if rng.random() < 0.4 else {}))
    if v == 16:
        return "How many incidents used each type of weapon?", agg_by("weapon_type", order="top")
    if v == 17:
        return rng.choice(["Count incidents by target type.", "Which target types were hit and how often?"]), \
            agg_by("target_type", order="top")
    if v == 18:
        return rng.choice(["Number of incidents in each month of the year.", f"Incidents per month in {y}."]), \
            agg_by("month", **(_yr(y) if rng.random() < 0.5 else {}))
    if v == 19:
        return f"Which {k} areas had the most incidents?", agg_by("area", "top", k)
    if v == 20:
        return rng.choice([f"Top {k} groups by number of attacks.", f"Which {k} groups are blamed for the most incidents?"]), \
            agg_by("group", "top", k)
    if v == 21:
        return rng.choice([f"Which area had the most attacks in {y}?", f"Where did the most incidents happen in {y}?"]), \
            agg_by("area", "top", 1, **_yr(y))
    if v == 22:
        dim, label = rng.choice([("attack_type", "attack type"), ("weapon_type", "weapon"), ("target_type", "target type")])
        return f"What was the most common {label} in {ad}?", agg_by(dim, "top", 1, area=a)
    if v == 23:
        return rng.choice(["Which year had the fewest incidents?", "In which year were the fewest attacks recorded?"]), \
            agg_by("year", "bottom", 1)
    if v == 24:
        return f"Compare the number of incidents in {y1} and {y2}.", agg_by("year", extra=[f"e.date.year IN [{y1}, {y2}]"])
    return rng.choice(["Which locality saw the most incidents?", "Which sub-area has the most recorded attacks?"]), \
        agg_by("locality", "top", 1)


# ---------- FAST pairs ----------
Q8_T = ["What can be traced from that incident?", "Expand outward from the selected attack: what is it linked to?",
        "Everything connected to this event, step by step.", "Show the network around that incident.",
        "What other events lie within a few links of this one?", "Follow the links out from the attack I clicked.",
        "Which incidents are indirectly tied to that one?", "Map out what surrounds this event.",
        "What does this attack lead to through its links?", "List everything reachable from the event I picked."]
Q10_T = [("Is the first incident connected to the second through any chain?", 2),
         ("How does event one lead to event two?", 2), ("Find a path between these two attacks.", 2),
         ("Are these two incidents related through other events in between?", 2),
         ("Show the route of links from the first attack to the third.", 3),
         ("What is the shortest chain linking the two events I picked?", 2),
         ("Could these two attacks be part of the same web of events?", 2),
         ("Trace how the second attack is tied to the first.", 2),
         ("How are the first and the third events related, even indirectly?", 3),
         ("Is there any path from this attack to the other one I selected?", 2)]
Q14_T = ["Which events resemble this one?", "Look for incidents described in a similar way to that attack.",
         "Any attacks that read like this one?", "Show similar incidents to the one I picked.",
         "What are the closest matches to that event by description?", "Other attacks of the same kind as this one?",
         "Give me lookalikes of the selected incident.", "Find events with a matching narrative to that one.",
         "Which past incidents sound like this attack?", "Are there similar events to the one I clicked?"]
Q15_T = ["Which events without a named group resemble {g}'s attacks?", "Could any unclaimed attacks be the work of {g}?",
         "Unattributed incidents that match the {g} pattern.", "Find attacks with no group that look like {g} ones.",
         "Are some of the unknown-perpetrator events similar to {g}?", "Possible {g} attacks that nobody was blamed for.",
         "Which unexplained attacks resemble those of {g}?", "Show orphan events that look like {g}."]


def make_fast(n_each=14):
    for qid, texts, tag in (("Q8", [(t, 1) for t in Q8_T], "FAST: Q8"), ("Q10", Q10_T, "FAST: Q10"),
                            ("Q14", [(t, 1) for t in Q14_T], "FAST: Q14")):
        got = tries = 0
        while got < n_each and tries < 400:
            tries += 1
            t, need = rng.choice(texts)
            got += add_pair(qid, "fast", style(t), ctx(need), tag)
    got = tries = 0
    while got < n_each and tries < 400:
        tries += 1
        g = rng.choice(GROUPS)
        got += add_pair("Q15", "fast", style(rng.choice(Q15_T).format(g=gdisp(g))), ctx(0), f"FAST: Q15 {g}")


# ---------- REFUSE pairs ----------
CITIES = ["Lahore", "Islamabad", "Peshawar", "Quetta", "Hyderabad", "Rawalpindi", "Faisalabad", "Multan",
          "Kabul", "Delhi", "Mumbai", "London", "Dhaka", "Baghdad"]
UNKNOWN_GROUPS = [g for g in ["Hamas", "Hezbollah", "Al-Shabaab", "Boko Haram", "Lashkar-e-Taiba",
                              "Tehreek-e-Labbaik Pakistan", "the Houthis", "Hizb-ut-Tahrir", "Jamaat-ud-Dawa",
                              "the Irish Republican Army", "FARC"] if g not in NAMES["Group"]]
OFF_TOPIC = ["What is the weather in Karachi today?", "Who will win the next cricket match?",
             "Give me a recipe for biryani.", "What is the dollar rate today?", "Write me a poem about the sea.",
             "Translate this sentence into Urdu.", "Who is the prime minister of Pakistan?",
             "What is the population of Karachi?", "Explain how neural networks work.",
             "What movies are playing tonight?", "How do I reach the airport from Saddar?",
             "Summarise the news today.", "Which team won the 2019 World Cup?", "What is the capital of France?"]
WRITES = ["Delete all events from 2014.", "Add a new attack to the database.",
          "Update the number killed in the most severe event.", "Remove the TTP node.",
          "Change the date of that attack to 2015.", "Create a link between these two events.",
          "Drop the Event table.", "Merge the two duplicate events."]
PREDICT = ["Predict where the next attack will happen.", "Will there be an attack in Lyari next month?",
           "Which area will be hit next?", "Forecast the number of attacks in 2025.",
           "Who is going to attack Karachi next?", "How likely is another bombing in Saddar this year?",
           "What will the trend in attacks be over the next five years?"]
COORDS = ["Which attacks happened within 2 km of Clifton Bridge?", "Show attacks near my house.",
          "What happened within walking distance of the airport?", "Which incidents occurred within 5 km of Saddar?"]
TALIBAN = ["What did the Taliban do in Karachi?", "List Taliban attacks.", "Taliban activity since 2012?",
           "Show events by the Taliban in 2014."]
NEED_TEXT = ([(t, n) for t, n in Q1_T] + [(t, 1) for t in Q5_T[:4] + Q8_T[:4] + Q14_T[:4]]
             + [(t, 2) for t in Q12_T[:3]] + list(Q10_T[:5]))


def make_refusals():
    cat = []
    cities = [(f"{t.format(c=c, y=ry())}", 0, f"REFUSE: The data covers Karachi only, so there is nothing for {c}.")
              for c in CITIES for t in ["How many attacks happened in {c} in {y}?", "Show me the deadliest incidents in {c}.",
                                        "List bombings in {c}.", "Which groups were active in {c}?"]]
    years = []
    for y in list(range(1970, 2000)) + list(range(2021, 2027)):
        for t in ["Show me all attacks in {y}.", "What was the deadliest incident in {y}?",
                  "How many incidents were there in {y}?", "Which groups were active in {y}?"]:
            years.append((t.format(y=y), 0, f"REFUSE: The data covers 2000 to 2020, so there is nothing for {y}."))
    for y1, y2 in ((1985, 1992), (1990, 1999), (2022, 2025)):
        years.append((f"Show attacks between {y1} and {y2}.", 0,
                      f"REFUSE: The data covers 2000 to 2020, so there is nothing for {y1} to {y2}."))
    groups = [(t.format(g=g), 0, f"REFUSE: No events are attributed to {g} in the data.")
              for g in UNKNOWN_GROUPS for t in ["Which attacks did {g} carry out?", "List events attributed to {g}.",
                                                "What has {g} done since 2010?"]]
    taliban = [(t, 0, "REFUSE: Which Taliban group do you mean: TTP, Punjabi Taliban, TTI or Haqqani Network?")
               for t in TALIBAN]
    off = [(t, 0, "REFUSE: This tool only answers questions about Karachi security incidents from 2000 to 2020.")
           for t in OFF_TOPIC]
    wr = [(t, ctx(0), "REFUSE: This tool is read-only, so it cannot change the data.") for t in WRITES]
    pr = [(t, 0, "REFUSE: The data records past incidents only, so it cannot predict future ones.") for t in PREDICT]
    co = [(t, 0, "REFUSE: The data has no coordinates, so it cannot search by distance.") for t in COORDS]
    ne = []
    for t, need in NEED_TEXT:
        n = rng.randint(0, need - 1)
        reply = ("REFUSE: Which event do you mean? No event has been selected yet." if need == 1 else
                 f"REFUSE: Which events do you mean? You have selected {n} and I need {need}.")
        ne.append((t, n, reply))
    for items, n in ((cities, 12), (years, 12), (groups, 10), (taliban, 4), (off, 14), (wr, 7), (pr, 7), (co, 4),
                     (ne, 14)):
        for text, ev, reply in rng.sample(items, min(n, len(items))):
            add_pair("REFUSE", "refuse", style(text), ev, reply)


# ---------- build ----------
fill("Q0b", 38, m_q0b)
fill("Q0b", 14, m_q0b_one)
fill("Q1", 14, m_q1)
fill("Q2", 34, m_q2)
fill("Q3", 28, m_q3)
fill("Q4", 24, m_q4)
fill("Q5", 10, m_q5)
fill("Q6", 20, m_q6)
fill("Q7", 14, m_q7)
fill("Q9", 18, m_q9)
fill("Q11", 12, m_q11)
fill("Q12", 12, m_q12)
fill("Q13", 24, m_q13)
fill("LOC", 14, m_loc)
fill("AREA", 14, m_area)
fill("PLACE", 24, m_place)
fill("ORG", 20, m_org)
make_fast(14)
fill("AGG", 44, m_agg)
make_refusals()

# Q12 wording is answered by the Q10 handler (decision of 2026-10-24): relabel after generation,
# so the random stream, and with it every other pair, stays identical.
for p in pairs:
    if p["query_id"] == "Q12":
        p.update(query_id="Q10", type="fast", reply="FAST: Q10")
    elif p["query_id"] == "Q1":      # promoted to FAST on 2026-10-24 (under 4 of 5 on dev)
        p.update(type="fast", reply="FAST: Q1")
rng.shuffle(pairs)
for i, p in enumerate(pairs, 1):
    p["id"] = f"t{i:04d}"
os.makedirs("train", exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    for p in pairs:
        f.write(json.dumps(p, ensure_ascii=False) + "\n")
driver.close()

by_type = Counter(p["type"] for p in pairs)
print(f"\nwrote {len(pairs)} pairs to {OUT}")
print("by type:", dict(by_type), f"| FAST share {by_type['fast'] / len(pairs):.1%}")
print("by query:", dict(sorted(Counter(p["query_id"] for p in pairs).items())))
print("skipped candidates:", dict(skipped))
print(f"pools: groups {len(GROUPS)}, areas {len(AREAS)}, localities {len(LOCALITIES)}, "
      f"road names {len(ROADS)}, organisations {len(ORGS)}")


