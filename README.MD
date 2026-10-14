# EventNexus

Knowledge-graph and NLP tool for cross-event analysis of Karachi security incidents. Links events through shared actors, targets, and areas using Neo4j, entity recognition, embeddings, and trained models, with evidence-backed answers.

> **Status:** work in progress. Setup is under way; the analysis pipeline is being built.

## What it does

Most incident databases answer questions about single events. EventNexus is built to answer questions *across* events:

- Which incidents share the same actor, target type, weapon, or area?
- How do patterns change over time and place?
- Which past events resemble a given incident?

Every answer points back to the specific events it came from, so results can be checked.

## How it works

1. **Data:** incident records from the Global Terrorism Database (GTD), narrowed to Karachi and to the columns that matter.
2. **Graph:** events, actors, targets, weapons, and areas are loaded into Neo4j, with links between events that share attributes.
3. **NLP:** named-entity recognition on incident summaries adds finer-grained entities (neighbourhoods, organisations) to the graph.
4. **Embeddings and clustering:** summaries are embedded so events can be compared by what happened, then grouped into patterns.
5. **Trained models:** a fine-tuned text classifier and an event-similarity model.
6. **Question answering:** a language model turns questions into graph queries and summarises the results with event citations.
7. **Interface:** a FastAPI backend with a browser UI showing the answer, the evidence trail, and the graph.

Design goal: after a one-time download of the models, the whole application runs without internet.

## Tech stack

- **Graph database:** Neo4j (local, via Neo4j Desktop)
- **NLP:** spaCy, GLiNER, Hugging Face Transformers, sentence-transformers
- **ML:** PyTorch, scikit-learn, UMAP
- **Backend:** FastAPI, Uvicorn
- **Frontend:** plain HTML, CSS, JavaScript with D3
- **Language:** Python 3.12

## Project structure

```
EventNexus/
├── app/            # API and frontend
├── data/
│   ├── raw/        # source data (not tracked by git)
│   └── processed/  # cleaned datasets
├── models/         # downloaded and trained models (not tracked by git)
├── notebooks/      # exploration
├── src/            # pipeline code and setup scripts
├── .env            # local credentials (not tracked by git)
├── requirements.txt
└── requirements-lock.txt
```

## Setup

### 1. Python environment

Python 3.12 is recommended.

```
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
```

### 2. PyTorch (install separately on each machine)

PyTorch is not listed in `requirements.txt` because the right build depends on the machine.

CPU only:

```
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

NVIDIA GPU: use the selector at https://pytorch.org to get the command for your CUDA version.

### 3. Other dependencies

```
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

`requirements-lock.txt` records the exact versions used during development.

### 4. Neo4j

1. Install [Neo4j Desktop](https://neo4j.com/download/).
2. Create a local instance and a database named `eventnexus-db`.
3. Start the instance.

### 5. Environment variables

Create a `.env` file in the project root:

```
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password_here
NEO4J_DATABASE=eventnexus-db
```

### 6. Data

The raw data is not included in this repository. EventNexus uses the Global Terrorism Database (GTD), maintained by START at the University of Maryland. Obtain it from the official GTD site, check its terms of use, and place the file at:

```
data/raw/raw.xlsx
```

### 7. Models

Download the pretrained models once (requires internet). They are saved into `models/` and work offline afterwards.

```
python src/download_models.py
```

| Task | Model |
|---|---|
| Entity recognition | `urchade/gliner_medium-v2.1` |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| Classifier base | `distilbert-base-uncased` |

### 8. Verify the setup

```
python src/check_imports.py     # all libraries import
python src/test_neo4j.py        # database connection works
python src/test_models.py       # models load and run
```

## Roadmap

- [ ] Setup (environment, Neo4j, libraries, models)
- [ ] Data triage and cleaning
- [ ] Graph design
- [ ] Graph build
- [ ] Entity recognition on summaries
- [ ] Embeddings and clustering
- [ ] Trained models
- [ ] Cross-event analysis queries
- [ ] Question-answering layer
- [ ] API and interface
- [ ] Evaluation and comparison
- [ ] Packaging and documentation

## License

See [LICENSE](LICENSE).