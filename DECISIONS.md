# EventNexus decision log

| Decision | Choice | Why |
|---|---|---|
| Scope | Karachi: any city spelling, plus Sindh events inside Karachi's coordinate box (about 2,800 events across all years) | Karachi alone has plenty of events; district-named events are included, Hub (Balochistan) is not |
| Time window | 2000 to 2020 (about 1,650 events) | Incident summaries exist only from 2000; the 1990s have almost no text and mostly unknown perpetrators |
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
| Area from text | Neighbourhoods are extracted from location and summary text, not coordinates | 1,627 of 1,664 events share one city-centre coordinate |
| Columns kept | 30 of 135 (identity, place, actor, method, target, outcome, cross-event hints, text, evidence) | Chosen for linking events, describing them, or evidence; the rest are mostly empty or redundant |
| Unknown is not a link | Values labelled "Unknown" (and generic groups) never create shared-attribute links in the graph | Two unknowns don't mean the same thing |