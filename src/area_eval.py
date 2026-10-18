import pandas as pd
from difflib import SequenceMatcher
from areas import normalise, valid, build_gazetteer, extract_area

EQUIV = {"dha": "defence housing authority", "defense": "defence housing authority",
         "fb area": "federal b"}


def canon(name):
    n = normalise(name).lower().replace("-", " ")
    return EQUIV.get(n, n)


def same(a, b):
    a, b = canon(a), canon(b)
    return a == b or SequenceMatcher(None, a, b).ratio() >= 0.85


def clean_text(s):
    return " ".join(str(s).split()) if pd.notna(s) else ""


def add_keys(d):
    d["key"] = d["location"].map(clean_text) + "||" + d["summary_clean"].map(clean_text)
    return d


def predictions(df, gliner_path):
    gaz = build_gazetteer(df)
    res = df.apply(lambda r: extract_area(r["location"], r["summary_clean"], r["city_raw"], gaz),
                   axis=1, result_type="expand")
    rule_pred = pd.Series(res[0].values, index=df["eventid"])

    raw = pd.read_parquet(gliner_path)
    raw["name"] = raw["text"].map(normalise)
    raw = raw[raw["label"].isin(["neighbourhood", "locality", "landmark"]) & raw["name"].map(valid)]
    counts = raw.groupby("name")["eventid"].nunique()
    raw = raw[raw["name"].isin(counts[counts >= 2].index)]
    best = raw.sort_values("score", ascending=False).groupby("eventid").first()
    gliner_pred = pd.Series(best["name"]).reindex(df["eventid"])

    hybrid_pred = rule_pred.where(rule_pred.notna(), gliner_pred)
    known = [canon(n) for n in set(gaz) | set(counts[counts >= 2].index)]
    return {"rules": rule_pred, "gliner": gliner_pred, "hybrid": hybrid_pred}, known


def evaluate(gold, pred, label, known):
    rows = []
    for _, g in gold.iterrows():
        p = pred.get(g["eventid"])
        predicted = p is not None and pd.notna(p)
        alts = str(g["gold_area"]).split("|")
        has_gold = str(g["gold_area"]).lower() != "none"
        correct = has_gold and predicted and any(same(p, x) for x in alts)
        recurring = has_gold and any(same(x, k) for x in alts for k in known)
        rows.append({"gold": g["gold_area"], "pred": p if predicted else None,
                     "location": g["location"], "has_gold": has_gold,
                     "predicted": predicted, "correct": correct, "recurring": recurring})
    r = pd.DataFrame(rows)
    tp = int((r.has_gold & r.correct).sum())
    rec_n = int((r.has_gold & r.recurring).sum())
    rec_tp = int((r.has_gold & r.correct & r.recurring).sum())
    return r, {
        "method": label,
        "coverage": round(r.predicted.mean(), 2),
        "precision": round(tp / max(int(r.predicted.sum()), 1), 2),
        "recall": round(tp / max(int(r.has_gold.sum()), 1), 2),
        "recall_recurring": round(rec_tp / max(rec_n, 1), 2),
        "accuracy": round(((r.has_gold & r.correct) | (~r.has_gold & ~r.predicted)).mean(), 2),
    }