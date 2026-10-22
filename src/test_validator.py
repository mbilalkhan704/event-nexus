"""
Tests for the shared base. Run from the repo root:  python src/test_validator.py
Needs Neo4j running. Add --no-db to run only the text checks.
"""
import sys

from neo4j.exceptions import Neo4jError

import qa_core
import validator
from config import get_driver, run

NAMES = validator.build_names({
    "Group": {"Tehrik-i-Taliban Pakistan (TTP)", "Lashkar-e-Jhangvi"},
    "Area": {"Lyari", "Orangi", "Clifton"},
    "Locality": {"Manghopir"},
    "AttackType": {"Bombing/Explosion", "Armed Assault"},
    "WeaponType": {"Explosives", "Firearms"},
    "TargetType": {"Police"},
})

RANKING = """MATCH (e:Event)
WHERE e.date >= date('2016-01-01') AND e.date <= date('2020-12-22') AND e.nkill IS NOT NULL
OPTIONAL MATCH (e)-[:OCCURRED_IN]->(a:Area)
WITH e, a, e.nkill - coalesce(e.nkillter, 0) AS victims_killed,
     CASE WHEN e.nwound IS NULL THEN null ELSE e.nwound - coalesce(e.nwoundte, 0) END AS victims_wounded
RETURN e.eventid AS _ref, e.date AS date, a.name AS area, victims_killed, victims_wounded
ORDER BY victims_killed DESC, coalesce(victims_wounded, 0) DESC
LIMIT 5"""

# (name, query, events, expected ok, substring expected in a problem)
CASES = [
    ("ranking query", RANKING, 0, True, ""),
    ("area and type filter",
     "MATCH (e:Event)-[:OCCURRED_IN]->(:Area {name: 'Lyari'}) WHERE e.attack_type = 'Bombing/Explosion' "
     "RETURN e.eventid AS _ref, e.date AS date LIMIT 50", 0, True, ""),
    ("group count",
     "MATCH (e:Event)-[:ATTRIBUTED_TO]->(g:Group {name: 'Tehrik-i-Taliban Pakistan (TTP)'}) "
     "RETURN count(e) AS n LIMIT 1", 0, True, ""),
    ("place text fallback",
     "MATCH (e:Event) WHERE toLower(e.location) CONTAINS toLower('chundrigar') "
     "OR toLower(e.summary_clean) CONTAINS toLower('chundrigar') "
     "RETURN e.eventid AS _ref, 'text' AS place_match LIMIT 50", 0, True, ""),
    ("org text fallback",
     "MATCH (e:Event)-[:TARGETED_ORG]->(o:TargetOrg) WHERE toLower(o.name) CONTAINS toLower('muttahida') "
     "RETURN e.eventid AS _ref, 'text' AS org_match, o.name AS org_name LIMIT 50", 0, True, ""),
    ("directed bounded chain",
     "MATCH p = (a:Event)-[:FOLLOWED_BY*..6]->(b:Event) WHERE NOT ()-[:FOLLOWED_BY]->(a) "
     "AND NOT (b)-[:FOLLOWED_BY]->() RETURN a.eventid AS _ref_a, b.eventid AS _ref_b, "
     "length(p) AS links ORDER BY links DESC LIMIT 5", 0, True, ""),
    ("why linked (excludes GTD_RELATED)",
     "MATCH (a:Event {eventid: $ref_a}), (b:Event {eventid: $ref_b}) OPTIONAL MATCH (a)-[r]-(b) "
     "WHERE type(r) <> 'GTD_RELATED' RETURN a.eventid AS _ref_a, collect(type(r)) AS types LIMIT 1", 2, True, ""),
    ("no LIMIT", "MATCH (e:Event) RETURN e.eventid AS _ref", 0, False, "LIMIT"),
    ("LIMIT too high", "MATCH (e:Event) RETURN e.eventid AS _ref LIMIT 500", 0, False, "LIMIT above"),
    ("write", "MATCH (e:Event) SET e.nkill = 0 RETURN e.eventid AS _ref LIMIT 1", 0, False, "SET"),
    ("CALL", "CALL db.labels() YIELD label RETURN label LIMIT 5", 0, False, "CALL"),
    ("SIMILAR_TO", "MATCH (a:Event)-[:SIMILAR_TO]-(b:Event) RETURN a.eventid AS _ref LIMIT 5", 0, False, "SIMILAR_TO"),
    ("var-length over other links",
     "MATCH (a:Event)-[:SAME_SOURCE*..3]-(b:Event) RETURN b.eventid AS _ref LIMIT 5", 0, False, "FOLLOWED_BY"),
    ("unbounded FOLLOWED_BY chain is fine",
     "MATCH (a:Event)-[:FOLLOWED_BY*2..]->(b:Event) RETURN b.eventid AS _ref LIMIT 5", 0, True, ""),
    ("group compared by name",
     "MATCH (e:Event)-[:ATTRIBUTED_TO]->(g:Group) WHERE g.name = 'Lashkar-e-Jhangvi' "
     "RETURN count(e) AS n LIMIT 1", 0, True, ""),
    ("unknown group compared by name",
     "MATCH (e:Event)-[:ATTRIBUTED_TO]->(g:Group) WHERE g.name = 'Nobody' "
     "RETURN count(e) AS n LIMIT 1", 0, False, "not in the list"),
    ("undirected chain",
     "MATCH (a:Event)-[:FOLLOWED_BY*..3]-(b:Event) RETURN b.eventid AS _ref LIMIT 5", 0, False, "directed"),
    ("CONTAINS on Area name",
     "MATCH (e:Event)-[:OCCURRED_IN]->(a:Area) WHERE toLower(a.name) CONTAINS toLower('lya') "
     "RETURN e.eventid AS _ref LIMIT 5", 0, False, "CONTAINS is not allowed"),
    ("fallback on a known Area",
     "MATCH (e:Event) WHERE toLower(e.location) CONTAINS toLower('Lyari') "
     "RETURN e.eventid AS _ref, 'text' AS place_match LIMIT 5", 0, False, "OCCURRED_IN"),
    ("fallback without place_match",
     "MATCH (e:Event) WHERE toLower(e.location) CONTAINS toLower('teen talwar') "
     "RETURN e.eventid AS _ref LIMIT 5", 0, False, "place_match"),
    ("literal event id", "MATCH (e:Event {eventid: 201304280011}) RETURN e.date AS d LIMIT 1", 0, False, "literal"),
    ("unknown parameter", "MATCH (e:Event) WHERE e.nkill > $n RETURN e.eventid AS _ref LIMIT 5", 0, False, "$n"),
    ("$ref without context", "MATCH (e:Event {eventid: $ref}) RETURN e.eventid AS _ref LIMIT 1", 0, False, "context"),
    ("unknown label", "MATCH (e:Incident) RETURN count(e) AS n LIMIT 1", 0, False, "unknown label"),
    ("unknown group", "MATCH (e:Event)-[:ATTRIBUTED_TO]->(:Group {name: 'TTP'}) RETURN count(e) AS n LIMIT 1",
     0, False, "not in the list"),
    ("unknown area", "MATCH (e:Event)-[:OCCURRED_IN]->(:Area {name: 'Lyri'}) RETURN count(e) AS n LIMIT 1",
     0, False, "not in the list"),
    ("GTD_RELATED used", "MATCH (a:Event)-[:GTD_RELATED]-(b:Event) RETURN a.eventid AS _ref LIMIT 5",
     0, False, "GTD_RELATED"),
    ("forbidden property", "MATCH (e:Event) WHERE e.cluster = 3 RETURN e.eventid AS _ref LIMIT 5", 0, False, "never used"),
]

FAST_CASES = [
    ("FAST Q8 with event", "Q8", 1, True), ("FAST Q8 without event", "Q8", 0, False),
    ("FAST Q10 with one event", "Q10", 1, False), ("FAST Q10 with two", "Q10", 2, True),
    ("FAST Q14", "Q14", 1, True), ("FAST Q15 known group", "Q15 Lashkar-e-Jhangvi", 0, True),
    ("FAST Q15 unknown group", "Q15 Nobody", 0, False), ("FAST Q9", "Q9", 1, False),
]

failed = 0


def report(name, ok, detail=""):
    global failed
    failed += not ok
    print("PASS" if ok else "FAIL", name, detail if not ok else "")


# ---------- text checks ----------
for name, query, events, want_ok, needle in CASES:
    chk = validator.validate_cypher(query, events, NAMES)
    ok = chk.ok == want_ok and (want_ok or any(needle in p for p in chk.problems))
    report(f"validator: {name}", ok, f"ok={chk.ok} problems={chk.problems}")
for name, text, events, want_ok in FAST_CASES:
    chk = validator.validate_fast(text, events, NAMES["Group"])
    report(f"validator: {name}", chk.ok == want_ok, str(chk.problems))

for raw, kind, text in [
    ("CYPHER: MATCH (e:Event) RETURN count(e) AS n LIMIT 1;", "CYPHER", "MATCH (e:Event) RETURN count(e) AS n LIMIT 1"),
    ("```\nCYPHER: ```cypher\nMATCH (e:Event) RETURN e LIMIT 1\n```\n```", "CYPHER", "MATCH (e:Event) RETURN e LIMIT 1"),
    ("REFUSE: Not about Karachi.", "REFUSE", "Not about Karachi."),
    ("FAST: Q15 Lashkar-e-Jhangvi\nextra line", "FAST", "Q15 Lashkar-e-Jhangvi"),
    ("The answer is 42", "INVALID", "The answer is 42"),
]:
    p = qa_core.parse_reply(raw)
    report(f"parser: {raw[:30]!r}", (p.kind, p.text) == (kind, text), f"got {(p.kind, p.text)}")

keys_ok = (["_ref", "n"], [[201304280011, 3]])
report("exposed ids: underscore column is fine", validator.exposed_id_columns(*keys_ok) == [])
report("exposed ids: id column is caught", validator.exposed_id_columns(["id"], [[201304280011]]) == ["id"])
report("same_result: events by set, order ignored",
       qa_core.same_result(["_ref"], [[1], [2]], ["_ref"], [[2], [1]]))
report("same_result: different events differ",
       not qa_core.same_result(["_ref"], [[1]], ["_ref"], [[2]]))
report("same_result: rows by value, names ignored",
       qa_core.same_result(["n"], [[5]], ["count"], [[5]]))
report("same_result: extra model column is tolerated",
       qa_core.same_result(["n", "x"], [[5, 1]], ["count"], [[5]]))
report("same_result: column order ignored",
       qa_core.same_result(["b", "a"], [[2, 1]], ["a", "b"], [[1, 2]]))
report("same_result: wrong value differs",
       not qa_core.same_result(["n"], [[6]], ["count"], [[5]]))
report("same_result: both empty", qa_core.same_result(["_ref"], [], ["_ref"], []))

# ---------- database checks ----------
if "--no-db" not in sys.argv:
    driver = get_driver()
    names = qa_core.load_names(driver)
    report("names loaded: 39 groups, 95 areas, 43 localities",
           (len(names["Group"]), len(names["Area"]), len(names["Locality"])) == (39, 95, 43),
           str({k: len(v) for k, v in names.items()}))

    # read-only is enforced by the server, not only by the validator
    try:
        qa_core.execute_readonly(driver, "CREATE (n:ZzTmp) RETURN n")
        wrote = True
    except Neo4jError:
        wrote = False
    leftover = run(driver, "MATCH (n:ZzTmp) RETURN count(n) AS c")[0]["c"]
    if leftover:
        run(driver, "MATCH (n:ZzTmp) DELETE n")
    report("read-only transaction refuses writes", not wrote and leftover == 0, f"wrote={wrote} leftover={leftover}")

    # timeout turns into a clean error
    try:
        qa_core.execute_readonly(driver, "MATCH p=(a:Event {eventid: 201304280011})-[*1..9]-(b) RETURN count(p) AS n", timeout_s=1)
        timed_out = False
    except Neo4jError as e:
        timed_out = qa_core.is_timeout(e)
    report("1 s timeout stops a heavy query", timed_out)

    # whole pipeline with a fake model
    def run_fake(reply, events=0, refs=None):
        return qa_core.answer("test question", events, qa_core.FakeClient(reply), driver, names, refs,
                              system_prompt="unused")

    r = run_fake("CYPHER: MATCH (e:Event) WHERE e.date >= date('2014-01-01') AND e.date <= date('2014-12-31') "
                 "RETURN count(e) AS n LIMIT 1")
    report("pipeline: valid query runs", r.status == "ok" and r.rows and r.rows[0][0] > 0, f"{r.status} {r.problems} {r.error}")
    r = run_fake("CYPHER: MATCH (e:Event {eventid: $ref}) RETURN e.eventid AS _ref, e.date AS date LIMIT 1",
                 events=1, refs={"ref": 201304280011})
    report("pipeline: $ref is filled from refs", r.status == "ok" and len(r.rows) == 1, f"{r.status} {r.problems}")
    r = run_fake("CYPHER: MATCH (e:Event) RETURN e.eventid AS id LIMIT 1")
    report("pipeline: leaked id is rejected and rows dropped", r.status == "rejected" and not r.rows, f"{r.status}")
    r = run_fake("CYPHER: MATCH (e:Event) DETACH DELETE e")
    report("pipeline: write is rejected before running", r.status == "rejected", r.status)
    r = run_fake("REFUSE: That is outside the data.")
    report("pipeline: refusal", r.status == "refused", r.status)
    r = run_fake("FAST: Q8", events=0)
    report("pipeline: FAST without context is rejected", r.status == "rejected", r.status)
    r = run_fake("FAST: Q15 Lashkar-e-Jhangvi")
    report("pipeline: FAST Q15 accepted", r.status == "fast" and r.text == "Q15 Lashkar-e-Jhangvi", r.status)
    r = run_fake("I think the answer is 42.")
    report("pipeline: free text is invalid", r.status == "invalid", r.status)
    driver.close()

print("\nAll tests passed" if not failed else f"\n{failed} test(s) failed")
sys.exit(1 if failed else 0)
