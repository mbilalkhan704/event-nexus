"""
Shared base for every model (bake-off models, the demo).

A model only has to implement ModelClient.generate(system_prompt, user_message).
Everything else (prompt, message format, parsing, validation, read-only execution,
timeout, scoring) lives here, so all models are judged by identical code.

    answer(question, events, client, driver, names, refs)   -> Result
    same_result(model_keys, model_rows, gold_keys, gold_rows) -> bool  (execution accuracy)
"""
import re
import time
from collections import Counter
from dataclasses import dataclass, field

from neo4j import unit_of_work
from neo4j.exceptions import Neo4jError

import validator
from config import DB, VALIDATOR_RULES, run

PROMPT_FILE = "src/prompts/schema_prompt.txt"
NAME_QUERIES = {
    "Group": "MATCH (n:Group) RETURN n.name AS n",
    "Area": "MATCH (n:Area) RETURN n.name AS n",
    "Locality": "MATCH (n:Locality) RETURN n.name AS n",
    "AttackType": "MATCH (n:AttackType) RETURN n.name AS n",
    "WeaponType": "MATCH (n:WeaponType) RETURN n.name AS n",
    "TargetType": "MATCH (n:TargetType) RETURN n.name AS n",
}


# ---------- model interface ----------
class ModelClient:
    name = "base"

    def generate(self, system_prompt, user_message):
        raise NotImplementedError


class FakeClient(ModelClient):
    """Returns a fixed reply, or reply(user_message) if callable. For tests."""
    name = "fake"

    def __init__(self, reply):
        self.reply = reply

    def generate(self, system_prompt, user_message):
        return self.reply(user_message) if callable(self.reply) else self.reply


# ---------- prompt and message ----------
def load_prompt(path=PROMPT_FILE):
    with open(path, encoding="utf-8") as f:
        return f.read().rstrip()


def build_user_message(question, events):
    return f"CONTEXT: events={events}\n{question.strip()}"


def load_names(driver):
    return validator.build_names({lab: {r["n"] for r in run(driver, q)} for lab, q in NAME_QUERIES.items()})


# ---------- parsing ----------
@dataclass
class Parsed:
    kind: str     # CYPHER, REFUSE, FAST or INVALID
    text: str


def _unfence(t):
    t = re.sub(r"^```[A-Za-z]*\s*", "", t.strip())
    return re.sub(r"\s*```$", "", t).strip()


def parse_reply(raw):
    t = _unfence(raw or "")
    m = re.match(r"(?is)^(CYPHER|REFUSE|FAST)\s*:\s*(.*)$", t)
    if not m:
        return Parsed("INVALID", t)
    kind, body = m.group(1).upper(), m.group(2).strip()
    if kind == "CYPHER":
        body = _unfence(body).rstrip(";").strip()
    elif kind == "FAST":
        body = body.splitlines()[0].strip() if body else ""
    return Parsed(kind, body)


# ---------- execution ----------
def _freeze(v):
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, (list, tuple)):
        return tuple(_freeze(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _freeze(x)) for k, x in v.items()))
    return str(v)          # dates and other driver types


def execute_readonly(driver, cypher, params=None, timeout_s=None):
    """Run in a read-only transaction with a timeout. Returns (keys, rows as lists)."""
    timeout_s = timeout_s or VALIDATOR_RULES["timeout_s"]

    def work(tx):
        result = tx.run(cypher, **(params or {}))
        return list(result.keys()), [[_freeze(x) for x in r.values()] for r in result]

    work = unit_of_work(timeout=timeout_s)(work)
    with driver.session(database=DB, default_access_mode="r") as session:
        return session.execute_read(work)


def is_timeout(err):
    return "TimedOut" in (getattr(err, "code", "") or "") or "timed out" in str(err).lower()


# ---------- the whole pipeline for one question ----------
@dataclass
class Result:
    question: str
    events: int
    raw: str = ""
    kind: str = ""        # CYPHER, REFUSE, FAST, INVALID
    status: str = ""      # ok, refused, fast, invalid, rejected, error, timeout
    text: str = ""        # the query, the refusal reason or the FAST call
    problems: list = field(default_factory=list)
    keys: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    error: str = ""
    seconds: float = 0.0


def answer(question, events, client, driver, names, refs=None, system_prompt=None):
    """refs: {'ref': id, 'ref_a': id, 'ref_b': id} supplied by the app (dev items carry them)."""
    t0 = time.perf_counter()
    res = Result(question, events)
    res.raw = client.generate(system_prompt or load_prompt(), build_user_message(question, events))
    parsed = parse_reply(res.raw)
    res.kind, res.text = parsed.kind, parsed.text

    if parsed.kind == "INVALID":
        res.status, res.problems = "invalid", ["reply does not start with CYPHER:, REFUSE: or FAST:"]
    elif parsed.kind == "REFUSE":
        res.status = "refused"
    elif parsed.kind == "FAST":
        chk = validator.validate_fast(parsed.text, events, names["Group"])
        res.text = chk.query
        res.status, res.problems = ("fast", []) if chk.ok else ("rejected", chk.problems)
    else:
        chk = validator.validate_cypher(parsed.text, events, names)
        res.text = chk.query
        missing = [p for p in chk.params if not (refs and p in refs)]
        if not chk.ok or missing:
            res.status = "rejected"
            res.problems = chk.problems + [f"no value supplied for ${p}" for p in missing]
        else:
            try:
                keys, rows = execute_readonly(driver, chk.query, {p: refs[p] for p in chk.params})
                bad = validator.exposed_id_columns(keys, rows)
                if bad:
                    res.status, res.problems = "rejected", [f"event ids exposed in column(s): {', '.join(bad)}"]
                else:
                    res.status, res.keys, res.rows = "ok", keys, rows
            except Neo4jError as e:
                res.status = "timeout" if is_timeout(e) else "error"
                res.error = str(e)[:300]
    res.seconds = round(time.perf_counter() - t0, 3)
    return res


# ---------- execution accuracy ----------
def _values(rows, j):
    return sorted(repr(r[j]) for r in rows)


def _match_columns(model_keys, model_rows, gold_rows, gold_cols):
    """For each gold column, find a not-yet-used model column holding the same values."""
    used, mapping = set(), []
    for i in gold_cols:
        want = _values(gold_rows, i)
        for j in range(len(model_keys)):
            if j not in used and _values(model_rows, j) == want:
                used.add(j)
                mapping.append(j)
                break
        else:
            return None
    return mapping


def same_result(model_keys, model_rows, gold_keys, gold_rows):
    """Gold returns events (underscore columns): same set of events.
    Otherwise: same rows on the gold's columns. Gold columns are matched to model columns by
    value, so names, column order and extra model columns do not matter; row order never does."""
    if not gold_rows and not model_rows:
        return True
    gold_ids = [i for i, k in enumerate(gold_keys) if k.startswith("_")]
    if gold_ids:
        ids = [j for j, k in enumerate(model_keys) if k.startswith("_")]
        sub_rows = [[r[j] for j in ids] for r in model_rows]
        mapping = _match_columns(ids, sub_rows, gold_rows, gold_ids)
        if mapping is None:
            return False
        return ({tuple(r[j] for j in mapping) for r in sub_rows}
                == {tuple(r[i] for i in gold_ids) for r in gold_rows})
    mapping = _match_columns(model_keys, model_rows, gold_rows, range(len(gold_keys)))
    if mapping is None:
        return False
    return (Counter(tuple(r[j] for j in mapping) for r in model_rows)
            == Counter(tuple(r) for r in gold_rows))


# ---------- scoring for the test set (lists above the LIMIT, single events) ----------
def strip_limit(cypher):
    return re.sub(r"\s*LIMIT\s+\d+\s*$", "", cypher.strip(), flags=re.I)


def same_list(model_keys, model_rows, f_keys, f_rows, key_cols, unordered=False, cap=50):
    """f_* is the gold without its LIMIT (the full set F). Correct when the model's rows are all in F,
    have no duplicates, and number min(cap, |F|). On lists of fewer than cap rows this is the same-set rule."""
    cols = [f_keys.index(k) for k in key_cols]
    norm = (lambda t: tuple(sorted(map(repr, t)))) if unordered else tuple
    full = {norm(tuple(r[i] for i in cols)) for r in f_rows}
    n = min(cap, len(full))
    used, mapping = set(), []
    for i in cols:
        want = ({r[c] for r in f_rows for c in cols} if unordered else {r[i] for r in f_rows})
        for j in range(len(model_keys)):
            if j not in used and {r[j] for r in model_rows} <= want:
                used.add(j)
                mapping.append(j)
                break
        else:
            return n == 0 and not model_rows
    got = [norm(tuple(r[j] for j in mapping)) for r in model_rows]
    return len(got) == n and len(set(got)) == len(got) and set(got) <= full


def same_single(model_keys, model_rows, ref):
    """A single-event lookup: one row whose _ref is the referred event."""
    return "_ref" in model_keys and len(model_rows) == 1 and model_rows[0][model_keys.index("_ref")] == ref