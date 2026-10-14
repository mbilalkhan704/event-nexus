# EventNexus decision log

| Decision | Choice | Why |
|---|---|---|
| Scope | Karachi events from GTD (final choice after counting; widen to Sindh if too few) | 3-4 day timeline; keeps the graph small and checkable |
| Main focus | Cross-event analysis, not information extraction | GTD is already structured; the value is in connecting events |
| Graph database | Local Neo4j Desktop, database `eventnexus-db` | Offline-capable, native vector index, built-in browser |
| Data format | GTD converted once to Parquet; notebooks for exploration, scripts for repeatable steps | Fast loading on an 8 GB machine; reproducible pipeline |
| NER | GLiNER (medium) plus spaCy baseline | Custom entity labels without training |
| Embeddings | all-MiniLM-L6-v2 | Small and fast on CPU |
| Classifier base | distilbert-base-uncased, fine-tuned on a GPU machine | Light enough for a 6 GB GPU |
| LLM | Provider switch: Gemini API in development, local Ollama model for offline mode | Speed and quality now, offline demo later |
| Optional extra | Fine-tune a ~1B model to pick queries from the query library | Only if the core app is finished |
| Frontend | Plain HTML, CSS, JavaScript with D3, served by FastAPI | No Node build step; works offline |
| PyTorch | Installed per machine, not in requirements.txt | CPU here, CUDA on the GPU machine |
| Data privacy | Raw and processed data are not tracked by git | GTD terms of use; file size |