"""
Builds eval/test.jsonl: the 60 tester questions from eval/test_draft.jsonl plus label, events,
refs and gold. Every gold query is validated and executed. Hard problems (validator failure, no
rows, tie at a top-N cut) stop the write; warnings (list reaches the LIMIT of 50) are reported
and recorded as "truncated". Question text is copied here only to check the draft order.

    python src/make_test.py
"""
import json
import re
import sys
from collections import Counter

import qa_core
import validator
from config import get_driver
from gold import Q1_GOLD, _agg_where, agg_by, agg_count, agg_killed, lit, q0b, q3, where, yr

DRAFT, OUT = "eval/test_draft.jsonl", "eval/test.jsonl"
driver = get_driver()
NAMES = qa_core.load_names(driver)


def y(n):
    d_from, d_to = yr(n)
    return {"d_from": d_from, "d_to": d_to}


def lst(extra=(), **f):
    return ("MATCH (e:Event)\n" + where(_agg_where(extra=list(extra), **f), "\n  AND ")
            + "RETURN e.eventid AS _ref, e.date AS date\nORDER BY e.date\nLIMIT 50")


def cnt(extra=(), **f):
    return ("MATCH (e:Event)\n" + where(_agg_where(extra=list(extra), **f), "\n  AND ")
            + "RETURN count(e) AS incidents\nLIMIT 1")


def org_text(word):
    return ("MATCH (e:Event)-[:TARGETED_ORG]->(o:TargetOrg)\n"
            "WHERE toLower(o.name) CONTAINS toLower(" + lit(word) + ")\n"
            "RETURN e.eventid AS _ref, e.date AS date, o.name AS org_name, " + lit(word)
            + " AS org_match\nORDER BY e.date\nLIMIT 50")


GROUPS_BOTH = """MATCH (e:Event)-[:ATTRIBUTED_TO]->(g:Group)
WITH g, count(CASE WHEN e.date >= date('2000-01-01') AND e.date <= date('2009-12-31') THEN 1 END) AS events_2000s,
     count(CASE WHEN e.date >= date('2010-01-01') AND e.date <= date('2019-12-31') THEN 1 END) AS events_2010s
WHERE events_2000s > 0 AND events_2010s > 0
RETURN g.name AS group
ORDER BY group
LIMIT 50"""
AREA_DEATHS = """MATCH (e:Event)-[:OCCURRED_IN]->(a:Area)
WHERE e.nkill IS NOT NULL
WITH a, e.nkill - coalesce(e.nkillter, 0) AS victims_killed
RETURN a.name AS area, sum(victims_killed) AS victims_killed
ORDER BY victims_killed DESC, area
LIMIT 1"""
DEADLIEST_YEAR = """MATCH (e:Event)
WHERE e.nkill IS NOT NULL
WITH e.date.year AS year, e.nkill - coalesce(e.nkillter, 0) AS victims_killed
RETURN year, sum(victims_killed) AS victims_killed
ORDER BY victims_killed DESC, year
LIMIT 1"""
SAME_MONTH = """MATCH (e:Event)-[:OCCURRED_IN]->(a:Area)
WITH a, e.date.year AS year, e.date.month AS month, count(e) AS incidents
WHERE incidents >= 2
RETURN DISTINCT a.name AS area
ORDER BY area
LIMIT 50"""
GROUP_TARGET_TYPES = """MATCH (e:Event)-[:ATTRIBUTED_TO]->(g:Group), (e)-[:TARGETED]->(t:TargetType)
RETURN g.name AS group, count(DISTINCT t) AS target_types
ORDER BY target_types DESC, group
LIMIT 1"""
BALDIA_GROUPS = """MATCH (e:Event)-[:OCCURRED_IN]->(:Area {name: 'Baldia'})
MATCH (e)-[:ATTRIBUTED_TO]->(g:Group)
RETURN DISTINCT g.name AS group
ORDER BY group
LIMIT 50"""
MOSQUE_SHRINE = """MATCH (e:Event)
WHERE toLower(e.location) CONTAINS toLower('mosque') OR toLower(e.summary_clean) CONTAINS toLower('mosque')
   OR toLower(e.location) CONTAINS toLower('shrine') OR toLower(e.summary_clean) CONTAINS toLower('shrine')
RETURN e.eventid AS _ref, e.date AS date, 'text' AS place_match
ORDER BY e.date
LIMIT 50"""
JAN_2000 = ("MATCH (e:Event)\nWHERE e.date = date('2000-01-17')\n"
            "RETURN e.eventid AS _ref, e.date AS date, e.summary_clean AS summary\nORDER BY e.eventid\nLIMIT 50")
LAST_EVENT = ("MATCH (e:Event)\nRETURN e.eventid AS _ref, e.date AS date\n"
              "ORDER BY e.date DESC, e.eventid DESC\nLIMIT 1")
CONSULATES = """MATCH (e:Event)
WHERE e.target_type = 'Government (Diplomatic)'
   OR EXISTS { (e)-[:OCCURRED_IN]->(a:Area) WHERE a.name IN ['Chinese Consulate', 'U.S. Consulate'] }
   OR EXISTS { (e)-[:OCCURRED_AT]->(:Locality {name: 'Saudi Arabian Consulate'}) }
RETURN e.eventid AS _ref, e.date AS date
ORDER BY e.date
LIMIT 50"""
LINKED_2002 = """MATCH (a:Event)-[:SAME_ACTOR_NEARBY|SAME_SOURCE|SAME_MO_LOCAL|FOLLOWED_BY]-(b:Event)
WHERE a.date >= date('2002-01-01') AND a.date <= date('2002-12-31')
RETURN DISTINCT b.eventid AS _ref, b.date AS date
ORDER BY b.date
LIMIT 50"""
AREA_LINKS = """MATCH (e1:Event)-[:SAME_ACTOR_NEARBY]-(e2:Event)
WHERE e1.eventid < e2.eventid
MATCH (e1)-[:OCCURRED_IN]->(a1:Area), (e2)-[:OCCURRED_IN]->(a2:Area)
WHERE a1 <> a2
WITH CASE WHEN a1.name < a2.name THEN a1.name ELSE a2.name END AS area_a,
     CASE WHEN a1.name < a2.name THEN a2.name ELSE a1.name END AS area_b, count(*) AS links
RETURN area_a, area_b, links
ORDER BY links DESC, area_a, area_b
LIMIT 50"""


def sources(k):
    return ("MATCH (e:Event)-[:REPORTED_BY]->(s:Source)\n"
            "RETURN s.citation AS source, count(e) AS incidents\n"
            f"ORDER BY incidents DESC, source\nLIMIT {k}")


SEV = ("victims_killed", "victims_wounded")
G = []


def c(id_, q, qid, gold, topn=0, tie=(), ev=0, ref=None, note="", empty_ok=False):
    """gold may be a list of (gold, topn) candidates; the first without a tie is used."""
    G.append(dict(id=id_, q=q, expect="cypher", qid=qid, gold=gold, topn=topn, tie=tie, ev=ev, ref=ref,
                  note=note, empty_ok=empty_ok))
    

def f(id_, q, call, ev, ref=None, note=""):
    G.append(dict(id=id_, q=q, expect="fast", qid=call, gold=call, topn=0, tie=(), ev=ev, ref=ref, note=note))


def r(id_, q, note):
    G.append(dict(id=id_, q=q, expect="refuse", qid="REFUSE", gold=None, topn=0, tie=(), ev=0, ref=None, note=note))


# ---------- tester 1 ----------
c("x001", "How many incidents happened in Karachi in 2013?", "AGG", agg_count(**y(2013)))
c("x002", "Which area of Karachi had the most incidents overall?", "AGG", agg_by("area", "top", 1), 1, ("incidents",))
c("x003", "What was the deadliest incident in the database?", "Q0b", q0b("severity", 1), 1, SEV)
c("x004", "Who was the target in that incident, and how many were killed?", "Q1", Q1_GOLD, ev=1, ref="deadliest",
  note="follow-up to x003")
c("x005", "Which group is blamed for the most attacks?", "AGG", agg_by("group", "top", 1), 1, ("incidents",))
c("x006", "How many incidents have an unknown perpetrator?", "AGG", agg_count(unattributed=True))
c("x007", "Show me all bombings in Lyari.", "Q0b", lst(area="Lyari", attack="Bombing/Explosion"))
c("x008", "What were the most common weapons used between 2010 and 2015?", "AGG",
  agg_by("weapon_type", "top", d_from="2010-01-01", d_to="2015-12-31"), note="full ranking; no N given")
c("x009", "Which year had the fewest incidents?", "AGG", agg_by("year", "bottom", 1), 1, ("incidents",))
c("x010", "How many people were killed in Karachi in 2014 in total?", "AGG", agg_killed("sum", **y(2014)))
c("x011", "List incidents that targeted police.", "Q0b", lst(target="Police"))
c("x012", "Which attacks targeted religious figures or institutions?", "Q0b", lst(target="Religious Figures/Institutions"))
c("x013", "What happened in Orangi Town in 2009?", "Q0b", lst(area="Orangi", **y(2009)), empty_ok=True,
  note="Orangi Town = Area Orangi; no events there in 2009, so the true answer is none")
r("x014", "Can you give me the exact GPS coordinates of the incident in Clifton?", "no coordinates in the data")
c("x015", "Were there any attacks near Karachi airport?", "Q0b", lst(area="Jinnah International Airport"),
  note="Karachi airport = Area Jinnah International Airport")
# ---------- tester 2 ----------
c("x016", "How many incidents involved firearms versus explosives?", "AGG",
  agg_by("weapon_type", "top", extra=["e.weapon_type IN ['Firearms', 'Explosives']"]))
c("x017", "Which months tend to have the most incidents?", "AGG", agg_by("month", "top"), note="full ranking; no N given")
c("x018", "Which incidents had more than 10 people wounded?", "Q0b",
  lst(extra=["e.nwound IS NOT NULL", "e.nwound - coalesce(e.nwoundte, 0) > 10"]), note="victims_wounded > 10")
c("x019", "What were the biggest attacks in 2012?", "Q0b", q0b("severity", 5, *yr(2012)), 5, SEV,
  note="N not given: library default 5")
c("x020", "Did attacks on journalists happen in Karachi? Which ones?", "Q0b", lst(target="Journalists & Media"))
c("x021", "Which groups were active in both the 2000s and the 2010s?", "AGG", GROUPS_BOTH, note="2010s = 2010 to 2019")
c("x022", "How has the number of incidents changed from 2000 to 2020?", "AGG", agg_by("year"))
c("x023", "Which incidents are linked to the same group within a few weeks?", "Q3", q3(None, 21),
  note="AMBIGUOUS: 'a few weeks' read as 3 weeks = 21 days")
c("x024", "What attacks took place in Saddar?", "Q0b", lst(area="Saddar"))
c("x025", "Which targets were hit most often: police, private citizens, or businesses?", "AGG",
  agg_by("target_type", "top", extra=["e.target_type IN ['Police', 'Private Citizens & Property', 'Business']"]))
c("x026", "Tell me about the incident on 17 January 2000.", "Q0b", JAN_2000)
f("x027", "Which other incidents are similar to that one?", "Q14", 1, "jan2000", "follow-up to x026")
c("x028", "What was the last incident recorded in the database?", "Q0b", LAST_EVENT, 1, ("date",))
r("x029", "Will there be another attack in Karachi next year?", "prediction, outside the data")
c("x030", "Which area saw the most deaths?", "AGG", AREA_DEATHS, 1, ("victims_killed",))
# ---------- tester 3 ----------
c("x031", "Were there any assassinations of political party members?", "Q0b",
  lst(attack="Assassination",
      extra=["(e.target_type = 'Violent Political Party' OR e.target_subtype IN "
             "['Political Party Member/Rally', 'Politician or Political Party Movement/Meeting/Rally'])"]),
  note="target_subtype is not in the frozen prompt: expected miss, a coverage gap")
c("x032", "Show incidents where the attackers used a vehicle bomb.", "Q0b",
  lst(weapon="Explosives", extra=["e.weapon_subtype = 'Vehicle'"]),
  note="weapon_subtype is not in the frozen prompt: expected miss, a coverage gap")
c("x033", "Which incidents involved attacks on educational institutions?", "Q0b", lst(target="Educational Institution"))
c("x034", "Was there an attack on a foreign consulate in Karachi?", "Q0b", CONSULATES,
  note="Diplomatic targets plus the Chinese, US and Saudi consulate places")
c("x035", "How many incidents in 2007 had no casualties?", "AGG", cnt(extra=["e.nkill = 0", "e.nwound = 0"], **y(2007)),
  note="true answer is 0 whether wounded is 0 or unknown")
c("x036", "Which neighbourhoods had repeated attacks within the same month?", "AGG", SAME_MONTH,
  note="two or more incidents in one calendar month")
f("x037", "How is the second one connected to the first?", "Q10", 2, "saddar2", "follow-up to a list")
c("x038", "What type of attack was most common in Korangi?", "AGG", agg_by("attack_type", "top", 1, area="Korangi"), 1,
  ("incidents",))
c("x039", "Which incidents targeted the Rangers?", "ORG", org_text("rangers"))
c("x040", "Which news sources reported the most incidents?", "AGG", sources(5), 5, ("incidents",),
  note="N not given: 5; ties at the cutoff allowed")
c("x041", "Compare the number of incidents in 2008 and 2018.", "AGG", agg_by("year", extra=["e.date.year IN [2008, 2018]"]))
c("x042", "Which attacks happened near a mosque or shrine?", "PLACE", MOSQUE_SHRINE, note="text fallback")
r("x043", "How does Karachi compare with Lahore for incidents?", "data covers Karachi only")
c("x044", "What happened in Karachi in the week after Benazir Bhutto's assassination?", "Q0b",
  lst(d_from="2007-12-28", d_to="2008-01-03"), empty_ok=True,
  note="needs outside knowledge: 27 Dec 2007; no events in the window, so the true answer is none")
c("x045", "Which group attacked the most different types of targets?", "AGG", GROUP_TARGET_TYPES, 1, ("target_types",))
# ---------- tester 4 ----------
c("x046", "How many incidents involved kidnapping?", "AGG", agg_count(attack="Hostage Taking (Kidnapping)"))
c("x047", "Which incidents are connected to the 2002 attacks?", "LINK", LINKED_2002,
  note="AMBIGUOUS: events linked to any 2002 event by the four link types; all 7 results are inside 2002")
c("x048", "List all incidents in Gulshan-e-Iqbal.", "Q0b", lst(area="Gulshan-e-Iqbal"))
c("x049", "Which incident was that, and what was its date?", "Q1", Q1_GOLD, ev=1, ref="gulshan1",
  note="follow-up to x048: first event of the list")
c("x050", "What was the average number of people killed per incident?", "AGG", agg_killed("avg"),
  note="unrounded average")
r("x051", "Which incidents occurred on a national holiday or during Muharram?", "no holiday or calendar data")
c("x052", "Were there any attacks on bus or transport targets?", "Q0b", lst(target="Transportation"))
c("x053", "Which areas are connected to each other by repeated incidents?", "LINK", AREA_LINKS,
  note="AMBIGUOUS: read as the same group within 30 days across two Areas")
c("x054", "Show me incidents in Malir with at least one death.", "Q0b",
  lst(area="Malir", extra=["e.nkill IS NOT NULL", "e.nkill - coalesce(e.nkillter, 0) >= 1"]), note="victims_killed >= 1")
c("x055", "Which incidents targeted utilities like gas or electricity infrastructure?", "Q0b", lst(target="Utilities"))
c("x056", "What was the deadliest year, and what caused it?", "AGG", DEADLIEST_YEAR, 1, ("victims_killed",),
  note="the cause is not in the data; the answer must say so")
r("x057", "Who ordered the attack on 12 May 2007?", "no command or planning data")
c("x058", "Which group was responsible for attacks in Baldia Town?", "AGG", BALDIA_GROUPS, note="Baldia Town = Area Baldia")
c("x059", "Which incidents involved suicide attackers?", "Q0b", lst(extra=["e.suicide = true"]))
c("x060", "What attacks took place in North Nazimabad?", "Q0b", lst(area="North Nazimabad"))


KIND = {}
for kind, ids in {
    "list": "x007 x011 x012 x013 x015 x018 x020 x023 x024 x026 x031 x032 x033 x034 x039 x042 x044 x047 x048 x052 x054 x055 x059 x060",
    "ranked": "x002 x003 x005 x009 x019 x028 x030 x038 x040 x045 x056",
    "agg": "x001 x006 x008 x010 x016 x017 x021 x022 x025 x035 x036 x041 x046 x050 x058",
    "single": "x004 x049", "fast": "x027 x037", "refuse": "x014 x029 x043 x051 x057"}.items():
    for i in ids.split():
        KIND[i] = kind
KIND["x053"] = "list"
LIST_OPTS = {"x023": {"unordered": True}, "x053": {"key_cols": ["area_a", "area_b"], "unordered": True}}
assert len(KIND) == 60 and set(KIND) == {g["id"] for g in G}, "kind map does not cover the 60 questions"


# ---------- checks ----------
def run_q(gold, params=None):
    return qa_core.execute_readonly(driver, gold, params or {})


def check(g, refs):
    cands = g["gold"] if isinstance(g["gold"], list) else [(g["gold"], g["topn"])]
    last = None
    for gold, topn in cands:
        chk = validator.validate_cypher(gold, g["ev"], NAMES)
        if not chk.ok:
            return None, [f"validator: {'; '.join(chk.problems)}"], [], 0, gold
        try:
            params = {p: refs[p] for p in chk.params}
        except KeyError as e:
            return None, [f"missing ref {e}"], [], 0, gold
        keys, rows = run_q(chk.query, params)
        problems, warns = [], []
        if not rows:
            if g.get("empty_ok"):
                warns.append("gold is empty by design (the true answer is no incidents)")
            else:
                problems.append("no rows")
        if topn:
            if len(rows) != topn:
                problems.append(f"top-{topn} returned {len(rows)} rows")
            k2, r2 = run_q(re.sub(r"LIMIT\s+\d+\s*$", f"LIMIT {topn + 1}", chk.query), params)
            if len(r2) > topn:
                def val(row, col):
                    v = row[k2.index(col)]
                    return (v or 0) if col == "victims_wounded" else v
                if tuple(val(r2[topn - 1], t) for t in g["tie"]) == tuple(val(r2[topn], t) for t in g["tie"]):
                    problems.append("tie at the cut")
        else:
            if len(rows) >= 50:
                warns.append("list reaches the LIMIT of 50 (truncated)")
            if len(rows) == 1 and len(keys) == 1 and rows[0][0] in (0, None):
                warns.append("scalar result is zero or null")
        if not problems:
            return gold, [], warns, len(rows), gold
        last = problems
    return None, last, [], 0, cands[-1][0]


def first_ids(gold, n=1):
    keys, rows = run_q(gold)
    if len(rows) < n:
        raise SystemExit(f"cannot build refs: only {len(rows)} rows")
    return [row[0] for row in rows[:n]]


REFS = {"deadliest": lambda: {"ref": first_ids(q0b("severity", 1))[0]},
        "gulshan1": lambda: {"ref": first_ids(lst(area="Gulshan-e-Iqbal"))[0]},
        "jan2000": lambda: {"ref": first_ids(JAN_2000)[0]},
        "saddar2": lambda: dict(zip(("ref_a", "ref_b"), first_ids(lst(area="Saddar"), 2)))}

with open(DRAFT, encoding="utf-8") as fh:
    draft = {d["id"]: d for d in (json.loads(line) for line in fh if line.strip())}
if len(draft) != len(G) or any(draft.get(g["id"], {}).get("question") != g["q"] for g in G):
    sys.exit("eval/test_draft.jsonl does not match the questions in this script (order or text differs)")

out, bad, truncated = [], [], []
for g in G:
    refs = REFS[g["ref"]]() if g["ref"] else {}
    gold, problems, warns, nrows, shown = g["gold"], [], [], 0, None
    if g["expect"] == "cypher":
        gold, problems, warns, nrows, shown = check(g, refs)
        if problems:
            bad.append((g["id"], g["q"], problems))
        if any("truncated" in w for w in warns):
            truncated.append((g["id"], g["q"]))
        topn = next((t for gg, t in (g["gold"] if isinstance(g["gold"], list) else [(g["gold"], g["topn"])]) if gg == gold),
                    g["topn"])
    else:
        topn = 0
    d = draft[g["id"]]
    out.append({"id": g["id"], "tester": d["tester"], "question": d["question"], "events": g["ev"], "refs": refs,
                "expect": g["expect"], "query_id": g["qid"] if g["expect"] == "cypher" else
                ("REFUSE" if g["expect"] == "refuse" else g["qid"]),
                "gold": gold, "topn": topn or None, "note": g["note"],
                "truncated": any("truncated" in w for w in warns),
                "kind": KIND[g["id"]], **LIST_OPTS.get(g["id"], {}),
                "empty_gold": any("empty by design" in w for w in warns)})
    for w in warns:
        print(f"WARNING {g['id']}: {w}")
driver.close()

print("\nexpect:", dict(Counter(o["expect"] for o in out)))
print("query_id:", dict(sorted(Counter(o["query_id"] for o in out).items())))
print(f"truncated lists ({len(truncated)}):", [t[0] for t in truncated])
if bad:
    print("\nHARD PROBLEMS, nothing written:")
    for id_, q, p in bad:
        print(f"  {id_} {q}\n     {p}")
    sys.exit(1)
with open(OUT, "w", encoding="utf-8") as fh:
    for o in out:
        fh.write(json.dumps(o, ensure_ascii=False) + "\n")
print(f"\nwrote {len(out)} items to {OUT}")