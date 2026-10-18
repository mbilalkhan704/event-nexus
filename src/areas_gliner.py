import pandas as pd
from tqdm import tqdm
from gliner import GLiNER
from config import DATA_CLEAN

LABELS = ["neighbourhood", "locality", "landmark", "road"]
THRESHOLD = 0.4

df = pd.read_parquet(DATA_CLEAN)
model = GLiNER.from_pretrained("models/gliner")

rows = []
for r in tqdm(df.to_dict("records")):
    has_location = isinstance(r["location"], str) and r["location"].strip() != ""
    text = r["location"] if has_location else r["summary_clean"]
    source = "location" if has_location else "summary"
    for e in model.predict_entities(text, LABELS, threshold=THRESHOLD):
        rows.append({
            "eventid": int(r["eventid"]),
            "source": source,
            "label": e["label"],
            "text": e["text"],
            "score": round(float(e["score"]), 3),
        })

out = pd.DataFrame(rows)
out.to_parquet("data/processed/area_gliner_raw.parquet")
print("Entities found:", len(out))
print("Events with at least one entity:", out["eventid"].nunique(), "of", len(df))
print(out["label"].value_counts())