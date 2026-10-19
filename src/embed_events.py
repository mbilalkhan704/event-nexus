from pathlib import Path
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/processed/karachi_events_clean.parquet"
OUT = ROOT / "data/processed/event_embeddings.npz"

df = pd.read_parquet(SRC)
assert df["eventid"].is_unique

model = SentenceTransformer(str(ROOT / "models/minilm-embedder"))
vecs = model.encode(
    df["summary_clean"].tolist(),
    batch_size=64,
    normalize_embeddings=True,
    show_progress_bar=True,
)

np.savez(OUT, eventids=df["eventid"].to_numpy(), vectors=vecs.astype("float32"))
print(vecs.shape, "norm check:", np.linalg.norm(vecs, axis=1)[:3])
