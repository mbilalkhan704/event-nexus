from pathlib import Path
from gliner import GLiNER
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModel

MODELS = Path("models")
text = "A bomb exploded near a police van in Lyari, Karachi, and a militant group claimed responsibility."

# NER
ner = GLiNER.from_pretrained(str(MODELS / "gliner"))
entities = ner.predict_entities(text, ["neighbourhood", "city", "organisation", "weapon"])
for e in entities:
    print(e["label"], "->", e["text"])

# Embeddings
embedder = SentenceTransformer(str(MODELS / "minilm-embedder"))
vec = embedder.encode(text)
print("Embedding size:", vec.shape)

# Base encoder
tok = AutoTokenizer.from_pretrained(MODELS / "distilbert-base")
enc = AutoModel.from_pretrained(MODELS / "distilbert-base")
out = enc(**tok(text, return_tensors="pt"))
print("Encoder output:", out.last_hidden_state.shape)
