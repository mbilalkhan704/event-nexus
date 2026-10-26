"""
Validator for model output (the open lane). Pure text checks, no database.

validate_cypher(query, events, names) -> Check   rules from DECISIONS.md and the schema prompt
validate_fast(text, events, groups)   -> Check   FAST: Q8, Q10, Q14 or Q15 <group>
exposed_id_columns(keys, rows)        -> list    event ids must only leave in underscore columns
build_names(raw)                      -> dict    value lists, plus lower-cased places for the fallback check
"""
import re
from dataclasses import dataclass, field

from config import VALIDATOR_RULES

LABELS = {"Event", "Group", "Area", "Locality", "AttackType", "WeaponType",
          "TargetType", "TargetOrg", "Source"}
REL_TYPES = {"ATTRIBUTED_TO", "OCCURRED_IN", "OCCURRED_AT", "PART_OF", "REPORTED_BY",
             "HAS_ATTACK_TYPE", "USED_WEAPON", "TARGETED", "TARGETED_ORG",
             "SAME_ACTOR_NEARBY", "SAME_SOURCE", "SAME_MO_LOCAL", "FOLLOWED_BY"}
ALLOWED_PARAMS = {"ref": 1, "ref_a": 2, "ref_b": 2}   # parameter -> events needed in context
WRITE_WORDS = ("CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE", "DROP",
               "CALL", "LOAD", "FOREACH")
FAST_SIMPLE = {"Q1": 1, "Q8": 1, "Q10": 2, "Q14": 1}           # query -> events needed in context
NAME_LABELS = ("Group", "Area", "Locality", "AttackType", "WeaponType", "TargetType")
TYPE_PROPS = {"attack_type": "AttackType", "weapon_type": "WeaponType", "target_type": "TargetType"}

_STRING = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_LIT = r"'((?:[^'\\]|\\.)*)'"


@dataclass
class Check:
    ok: bool
    problems: list = field(default_factory=list)
    params: set = field(default_factory=set)
    query: str = ""


def build_names(raw):
    """raw: {label: set of names}. Adds '_place_lower' (Area and Locality, lower case)."""
    names = {k: set(v) for k, v in raw.items()}
    names["_place_lower"] = {n.lower() for n in names.get("Area", set()) | names.get("Locality", set())}
    return names


def clean(query):
    """Drop comments and a trailing semicolon."""
    q = re.sub(r"/\*.*?\*/", " ", query or "", flags=re.S)
    q = re.sub(r"(?m)//[^\n'\"]*$", "", q).strip()
    return re.sub(r";\s*$", "", q).strip()


def validate_cypher(query, events=0, names=None, rules=VALIDATOR_RULES):
    problems = []
    q = clean(query)
    if not q:
        return Check(False, ["empty query"])
    masked = _STRING.sub("''", q)          # string contents removed, so keywords inside text never count
    upper = masked.upper()

    # read-only
    if ";" in masked:
        problems.append("more than one statement")
    for w in WRITE_WORDS:
        if re.search(rf"\b{w}\b", upper):
            problems.append(f"{w} is not allowed (read-only, no CALL)")
    if re.search(r"\b(APOC|DBMS|DB)\s*\.", upper):
        problems.append("procedures are not allowed")
    if not re.search(r"\bRETURN\b", upper):
        problems.append("no RETURN")

    # LIMIT
    m = re.search(r"\bLIMIT\s+(\d+)\s*$", masked, re.I)
    if not m:
        problems.append("query must end with LIMIT <number>")
    elif int(m.group(1)) > rules["max_limit"]:
        problems.append(f"LIMIT above {rules['max_limit']}")

    # parameters and ids
    params = set(re.findall(r"\$(\w+)", masked))
    for p in sorted(params):
        need = ALLOWED_PARAMS.get(p)
        if need is None:
            problems.append(f"parameter ${p} is not allowed")
        elif events < need:
            problems.append(f"${p} needs {need} event(s) in context, got {events}")
    if re.search(r"\b\d{11,12}\b", masked):
        problems.append("literal event ids are not allowed")

    # schema: labels and relationship types
    for lab in re.findall(r"\(\s*\w*\s*:\s*(\w+)", masked):
        if lab not in LABELS:
            problems.append(f"unknown label {lab}")
    for body in re.findall(r"\[\s*\w*\s*:\s*([^\]\{\*]+)", masked):
        for t in re.split(r"[|:]", body):
            t = t.strip()
            if t and t not in REL_TYPES:
                problems.append(f"unknown or forbidden relationship type {t}")

    # GTD_RELATED may only be excluded; some properties are never used
    rest = re.sub(r"<>\s*'GTD_RELATED'", "", q)
    rest = re.sub(r"NOT\s+type\(\s*\w+\s*\)\s*=\s*'GTD_RELATED'", "", rest, flags=re.I)
    if "GTD_RELATED" in rest.upper():
        problems.append("GTD_RELATED may only be excluded with type(r) <> 'GTD_RELATED'")
    if (re.search(r"\.\s*(cluster|multiple|embedding|gname)\b", masked, re.I)
            or re.search(r"[{,]\s*(cluster|multiple|embedding|gname)\s*:", masked, re.I)):
        problems.append("cluster, multiple, embedding and gname are never used")

    # variable-length patterns: FOLLOWED_BY only, and directed (its chains are linear, so any length is safe)
    for left, inner, right in re.findall(r"(<?)-\s*\[([^\[\]]*)\]\s*-(>?)", masked):
        if "*" not in inner:
            continue
        tm = re.match(r"\s*\w*\s*:\s*([^\*\{]+)", inner)
        types = {t.strip() for t in re.split(r"[|:]", tm.group(1)) if t.strip()} if tm else set()
        if types != {"FOLLOWED_BY"}:
            problems.append("variable-length patterns are allowed only on FOLLOWED_BY")
        if bool(left) == bool(right):
            problems.append("variable-length FOLLOWED_BY must be directed")

    # CONTAINS: location, summary_clean, TargetOrg name; literals only
    found = re.findall(r"(?:toLower\(\s*)?([A-Za-z_]\w*)\.(\w+)\s*\)?\s+CONTAINS\s+(?:toLower\(\s*)?" + _LIT, q, re.I)
    if len(found) != len(re.findall(r"\bCONTAINS\b", upper)):
        problems.append("CONTAINS must compare a property with a string literal")
    place_fb = org_fb = False
    for var, attr, lit in found:
        if attr.lower() in ("location", "summary_clean"):
            place_fb = True
            if names and lit.strip().lower() in names["_place_lower"]:
                problems.append(f"'{lit}' is an Area or Locality: use OCCURRED_IN or OCCURRED_AT")
        elif attr.lower() == "name" and re.search(rf"\(\s*{re.escape(var)}\s*:\s*TargetOrg\b", masked):
            org_fb = True
        else:
            problems.append(f"CONTAINS is not allowed on {var}.{attr}")
    if place_fb and not re.search(r"\bAS\s+place_match\b", q, re.I):
        problems.append("text search on places must return 'text' AS place_match")
    if org_fb and not (re.search(r"\bAS\s+org_match\b", q, re.I) and re.search(r"\bAS\s+org_name\b", q, re.I)):
        problems.append("organisation search must return 'text' AS org_match and o.name AS org_name")

    # exact names
    if names:
        for label in NAME_LABELS:
            for nm in re.findall(rf"\(\s*\w*\s*:\s*{label}\s*\{{\s*name\s*:\s*" + _LIT, q):
                if nm not in names[label]:
                    problems.append(f"{label} '{nm}' is not in the list")
        for prop, nm in re.findall(r"\.(attack_type|weapon_type|target_type)\s*=\s*" + _LIT, q):
            if nm not in names[TYPE_PROPS[prop]]:
                problems.append(f"{prop} '{nm}' is not in the list")
        for var, nm in re.findall(r"\b(\w+)\.name\s*=\s*" + _LIT, q):
            lm = re.search(rf"\(\s*{re.escape(var)}\s*:\s*(\w+)", masked)
            if lm and lm.group(1) in NAME_LABELS and nm not in names[lm.group(1)]:
                problems.append(f"{lm.group(1)} '{nm}' is not in the list")
    return Check(not problems, problems, params, q)


def validate_fast(text, events=0, groups=None):
    """Check.query holds the normalised call: 'Q8', 'Q10', 'Q14' or 'Q15 <group>'."""
    t = (text or "").strip()
    m = re.fullmatch(r"(Q10|Q14|Q1|Q8)", t, re.I)
    if m:
        q = m.group(1).upper()
        if events < FAST_SIMPLE[q]:
            return Check(False, [f"{q} needs {FAST_SIMPLE[q]} event(s) in context, got {events}"], query=q)
        return Check(True, query=q)
    m = re.fullmatch(r"Q15\s+(.+)", t, re.I)
    if m:
        group = m.group(1).strip()
        if groups is not None and group not in groups:
            return Check(False, [f"group '{group}' is not in the list"], query=f"Q15 {group}")
        return Check(True, query=f"Q15 {group}")
    return Check(False, ["FAST must be Q1, Q8, Q10, Q14 or Q15 <group>"], query=t)


def exposed_id_columns(keys, rows):
    """Columns that leak event ids: not underscore-prefixed, and named like an id or holding 12-digit ints."""
    bad = []
    for i, k in enumerate(keys):
        if k.startswith("_"):
            continue
        leaks = any(isinstance(r[i], int) and not isinstance(r[i], bool) and 10**11 <= r[i] < 10**12
                    for r in rows)
        if "eventid" in k.lower() or leaks:
            bad.append(k)
    return bad