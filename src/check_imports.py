import importlib

packages = [
    "torch", "pandas", "numpy", "openpyxl", "sklearn", "matplotlib",
    "plotly", "networkx", "spacy", "gliner", "transformers", "datasets",
    "accelerate", "sentence_transformers", "umap", "fastapi", "uvicorn",
    "pydantic", "neo4j", "dotenv",
]

for name in packages:
    try:
        module = importlib.import_module(name)
        print(f"OK   {name:25s} {getattr(module, '__version__', '')}")
    except Exception as e:
        print(f"FAIL {name:25s} {e}")
        