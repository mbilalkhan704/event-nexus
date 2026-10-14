from pathlib import Path
from gliner import GLiNER
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModel

MODELS = Path("models")
MODELS.mkdir(exist_ok=True)

# 1. Entity recognition
ner = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")
ner.save_pretrained(MODELS / "gliner")

# 2. Embeddings
embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
embedder.save(str(MODELS / "minilm-embedder"))

# 3. Base encoder for the classifier
tok = AutoTokenizer.from_pretrained("distilbert-base-uncased")
enc = AutoModel.from_pretrained("distilbert-base-uncased")
tok.save_pretrained(MODELS / "distilbert-base")
enc.save_pretrained(MODELS / "distilbert-base")

print("All models saved to", MODELS.resolve())
