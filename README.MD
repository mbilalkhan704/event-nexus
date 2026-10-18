# EventNexus

Knowledge-graph and NLP tool for cross-event analysis of Karachi security incidents. Links events through shared actors, targets, and areas using Neo4j, entity recognition, embeddings, and trained models, with evidence-backed answers.

> **Status:** work in progress. Setup, data triage, graph design, graph build and place extraction are complete; embeddings and clustering are next.

## What it does

Most incident databases answer questions about single events. EventNexus is built to answer questions *across* events:

- Which incidents share the same actor, target type, weapon, or area?
- How do patterns change over time and place?
- Which past events resemble a given incident?

Every answer points back to the specific events it came from, so results can be checked.

## How it works

1. **Data:** incident records from the Global Terrorism Database (GTD), narrowed to Karachi and to the columns that matter.
2. **Graph:** events, actors, targets, weapons, and areas are loaded into Neo4j, with links between events that share attributes.
3. **Place extraction:** a rule-based extractor with a gazetteer assigns each event an Area (town level) and, when the text is more specific, a Locality (for example Gulshan-e-Maymar in Gadap). It was evaluated against GLiNER and a hybrid on hand-labelled events.
4. **Embeddings and clustering:** summaries are embedded so events can be compared by what happened, then grouped into patterns.
5. **Trained models:** a fine-tuned text classifier and an event-similarity model.
6. **Question answering:** a language model turns questions into graph queries and summarises the results with event citations. A hosted model is used during development, with a local model (via Ollama) as the offline fallback.
7. **Interface:** a FastAPI backend with a browser UI showing the answer, the evidence trail, and the graph.

Design goal: after a one-time download of the models, the whole application runs without internet.

## Current state

- 1,664 Karachi incidents (2000 to 2020) from GTD, cleaned to 30 columns plus derived fields.
- A Neo4j graph with 9 node types and 14 relationship types, rebuilt from scratch by one command and verified by 16 automated checks.
- Cross-event links that each carry a rule, a strength and evidence: 632 same-actor-nearby, 607 same-source, 184 same-method-and-place, and 280 followed-by (chains of events in the same area within a week).
- Place extraction: 74% of events get an Area and 225 also get a specific Locality. On 30 held-out hand-labelled events, an earlier version of the extractor reached precision 0.95 and recall 0.77 (see `docs/area_evaluation.md`).

## Tech stack

- **Graph database:** Neo4j (local, via Neo4j Desktop)
- **NLP:** spaCy, GLiNER, Hugging Face Transformers, sentence-transformers
- **ML:** PyTorch, scikit-learn, UMAP
- **Language model:** Gemini API (development) and Ollama with a small local model (offline mode)
- **Backend:** FastAPI, Uvicorn
- **Frontend:** plain HTML, CSS, JavaScript with D3
- **Language:** Python 3.12

## Project structure

```
EventNexus/
├── app/                     # API and frontend
├── data/
│   ├── raw/                 # source data (not tracked by git)
│   └── processed/           # converted and cleaned datasets (not tracked by git)
├── docs/                    # data dictionary, graph schema, area extraction evaluation
├── models/                  # downloaded and trained models (not tracked by git)
├── notebooks/               # exploration and evaluation
├── src/                     # pipeline code, graph build, place extraction, setup scripts
├── .env                     # local credentials (not tracked by git)
├── DECISIONS.md             # log of design decisions and the reasons for them
├── requirements.txt         # top-level dependencies
└── requirements-lock.txt    # exact versions used during development
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

LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
```

### 6. Data

The raw data is not included in this repository. EventNexus uses the Global Terrorism Database (GTD), maintained by START at the University of Maryland. Obtain it from the official GTD site, check its terms of use, and place the file at:

```
data/raw/raw.xlsx
```

Then convert it once to Parquet, so later steps load in seconds instead of minutes:

```
python src/convert_to_parquet.py
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

### 8. Language model

The application can use a hosted model or a local one.

- **Hosted (development):** create an API key in [Google AI Studio](https://aistudio.google.com) and put it in `.env` as `GEMINI_API_KEY`.
- **Local (offline mode):** install [Ollama](https://ollama.com), then pull a small model:

```
ollama pull llama3.2:1b
```

### 9. Verify the setup

```
python src/check_imports.py     # all libraries import
python src/test_neo4j.py        # database connection works
python src/test_models.py       # models load and run
python src/smoke_test.py        # one event through Neo4j, embedding and LLM
uvicorn app.main:app --reload   # stub app at http://127.0.0.1:8000
```

### 10. Build the dataset and the graph

```
python src/make_scope.py            # Karachi events from 2000 to 2020
python src/clean_data.py            # cleaning rules, see docs/data_dictionary.md
python src/setup_schema.py          # graph constraints and indexes
python src/build_graph.py --reset   # build the whole graph (safe to re-run)
python src/check_graph.py           # 16 checks on the finished graph
```

The graph build does not need the downloaded models. To reproduce the place-extraction comparison, run `python src/areas_gliner.py` and the evaluation notebooks; the hand-labelled files are not included because they contain GTD text.

## Roadmap

- [x] Setup (environment, Neo4j, libraries, models)
- [x] Data triage and cleaning
- [x] Graph design
- [x] Graph build
- [x] Place extraction from incident text (Areas and Localities)
- [ ] Embeddings and clustering
- [ ] Trained models
- [ ] Cross-event analysis queries
- [ ] Question-answering layer
- [ ] API and interface
- [ ] Evaluation and comparison
- [ ] Packaging and documentation

## License

See [LICENSE](LICENSE).