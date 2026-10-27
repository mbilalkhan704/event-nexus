# EventNexus

Knowledge-graph and NLP tool for cross-event analysis of Karachi security incidents. Links events through shared actors, targets, and areas using Neo4j, entity recognition, embeddings, and a fine-tuned language model, with evidence-backed answers.

> **Status:** work in progress. Setup, data triage, graph design, graph build, place extraction, embeddings and clustering are complete. Phase 6 (trained model) is nearly done: the base-model bake-off, the fine-tune and the check of the shipped model file on the dev set are finished; the one-time test run (fine-tuned against untrained), the scope guard and the model packaging are still to do. No test-set result exists yet.

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
4. **Embeddings and clustering:** summaries are embedded (all-MiniLM-L6-v2) and stored on the events. Events link to their mutual nearest neighbours when they are very similar, and are grouped into themes with UMAP and HDBSCAN. Embeddings capture what happened and to whom, not which campaign an event belonged to, so each similarity link also carries the gap in days and whether the events share an Area.
5. **Trained model:** Gemma 4 E4B, fine-tuned with QLoRA on project questions, replies to a plain-English question with exactly one of `CYPHER: <query>`, `REFUSE: <reason>` or `FAST: <library query>`. It is compared with the same model before fine-tuning.
6. **Question answering:** two lanes. In the *fast lane* the model names a library query (Q1 event details and sources, Q8 what is reachable within 3 steps, Q10 how or why two events are connected, Q14 similar events, Q15 unattributed events resembling a group) and the app runs it. In the *open lane* the model writes read-only Cypher, which a validator checks (LIMIT required and at most 100, 10 s timeout, no CALL or writes, variable-length patterns only on FOLLOWED_BY, exact names from the lists) before it runs. The app then summarises the result with event citations.
7. **Interface:** a FastAPI backend with a browser UI showing the answer, the evidence trail, and the graph.

Design goal: after a one-time download of the models, the whole application runs without internet. No third-party hosted model is used.

## Current state

- 1,664 Karachi incidents (2000 to 2020) from GTD, cleaned to 32 columns plus derived fields.
- A Neo4j graph with 9 node types and 15 relationship types, rebuilt from scratch by one command and verified by 33 automated checks.
- Cross-event links that each carry a rule, a strength and evidence: 632 same-actor-nearby, 607 same-source, 184 same-method-and-place, 280 followed-by (chains of events in the same area within a week), and 928 similar-to (mutual nearest neighbours by embedding, cosine at least 0.85).
- Place extraction: 74% of events get an Area and 225 also get a specific Locality. On 30 held-out hand-labelled events, an earlier version of the extractor reached precision 0.95 and recall 0.77 (see `docs/area_evaluation.md`).
- Embeddings: all 1,664 summaries are embedded (384 dimensions) and indexed with a Neo4j vector index. 31 clusters group 80% of events; the rest are noise and get no cluster.
- Check against GTD's own related pairs (111 with different text, never used to build links): text similarity alone ranks the typical pair above 99.7% of all pairs (median; mean percentile 0.968), and 50% of the pairs are linked by similar-to.
- Evaluation data: a 105-question dev set (60 Cypher, 30 fast-lane, 15 should-refuse), a 60-question test set written by four testers (53 Cypher, 2 fast-lane, 5 should-refuse), and 481 training pairs. The prompt (version 3) and the test set are frozen with git tags before any model sees the test set.
- Model bake-off (dev set, before fine-tuning against after): Qwen2.5-Coder-3B went from 0/65 to 34/65 correct Cypher answers, Gemma 4 E4B from 4/65 to 48/65. Gemma 4 E4B won and was retrained on the final prompt.
- Shipped model file (Gemma 4 E4B fine-tuned, GGUF Q8_0, 7.97 GB), dev set only: 48 of 60 Cypher questions correct (80.0%, 95% interval 68 to 88%), all 30 fast-lane questions routed correctly, 13 of 15 refusals made, no answerable question wrongly refused. These are dev numbers used for tuning, not test results. Known weak spots: three open-lane queries (Q3, Q7, Q9) answer fewer than 4 of 5 phrasings correctly.
- Quantization finding: only Q8_0 keeps the fine-tune. Q6_K and Q4_K_M erase it (13/30 and 5/30 on a 30-question subset against 23/30 for Q8_0), because the fine-tune's correction is smaller than one rounding step of those grids. See `DECISIONS.md`.

## Tech stack

- **Graph database:** Neo4j (local, via Neo4j Desktop)
- **NLP:** spaCy, GLiNER, Hugging Face Transformers, sentence-transformers
- **ML:** PyTorch, scikit-learn, UMAP
- **Language model:** Gemma 4 E4B (Apache 2.0), fine-tuned with QLoRA (PEFT, bitsandbytes) on a Kaggle T4, served as a GGUF through llama.cpp or Ollama behind one OpenAI-compatible client
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
├── docs/                    # data dictionary, graph schema, query library, area extraction evaluation
├── eval/                    # dev and test sets (questions and gold queries), tester files, few-shot examples
├── models/                  # downloaded and trained models (not tracked by git)
├── notebooks/               # exploration and evaluation
├── results/                 # evaluation run outputs (not tracked by git)
├── results_hf/              # model replies downloaded from Hugging Face (not tracked by git)
├── src/                     # pipeline code, graph build, place extraction, validator, QA core, clients, evaluation scripts
│   └── prompts/             # schema_prompt.txt, the one frozen prompt
├── train/                   # training pairs for the fine-tune
├── .env                     # local credentials and server address (not tracked by git)
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
```

For the language model (step 8) add the address of the model server and its key, if it has one:

```
LLM_URL=http://127.0.0.1:8080
LLM_API_KEY=
```

Never commit `.env` or paste keys into chats or issues. A server behind a tunnel gets a new random key and URL at every start.

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

The fine-tuned query model is not part of this script yet (see step 8).

### 8. Language model

The app talks to one OpenAI-compatible server, whose address is `LLM_URL`. The fine-tuned model is a single GGUF file (Gemma 4 E4B, Q8_0, 7.97 GB). It will be published on Hugging Face Hub with a model card after the test run; until then it is not downloadable from this repository. Two ways to serve it:

- **Locally, fully offline:** run the GGUF with [llama.cpp](https://github.com/ggml-org/llama.cpp) (`llama-server`) or Ollama. Memory needed: about 8.2 GB of RAM was measured for llama-server on CPU at 4,608 tokens of context; a GPU needs roughly 9 to 10 GB of VRAM (an estimate, not yet measured on a GPU). Ollama support for this file and its thinking switch are not yet tested.
- **Without a capable PC:** run the same file with `llama-server` in a Kaggle notebook behind a cloudflared quick tunnel, then put the printed URL and key into `.env`. On the Kaggle CPU decoding is slow (about 4 to 5 tokens per second) and the first request takes about 200 s.

Two serving rules matter for correct answers:

- **Thinking mode must be off.** The model's default chat template adds a thinking line that the training prompt did not have. The client sends `enable_thinking: false`; when starting `llama-server` yourself, set the same default.
- **Keep the system prompt identical and first.** The prompt is about 3,000 tokens; the server reuses its cached copy only if every request starts with exactly the same text. Send one warm-up request after each server start.

Do not use a Q4 or Q6 quantization of this model: they lose the fine-tuning (see Current state).

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
python src/embed_events.py          # embeds every summary (needs the models from step 7)
python src/setup_schema.py          # graph constraints and indexes
python src/build_graph.py --reset   # build the graph (safe to re-run)
python src/embed_graph.py           # embeddings and vector index onto the events
python src/similar_links.py         # SIMILAR_TO links
python src/cluster_events.py        # clusters and the map file
python src/components.py            # component ids for path questions
python src/check_graph.py           # 33 checks on the finished graph
```

The graph build itself does not need the downloaded models; the embedding step does. `build_graph.py --reset` also removes the embeddings, similarity links and clusters, and leaves components.json stale, so run the four steps after it again. `embed_events.py` only needs rerunning if the data or the embedding model changes. To reproduce the place-extraction comparison, run `python src/areas_gliner.py` and the evaluation notebooks; the hand-labelled files are not included because they contain GTD text.

### 11. Evaluation data and checks

```
python src/make_dev.py              # dev set and few-shot examples (already generated; rerunning replaces dev.jsonl)
python src/make_dev_agg.py          # adds 10 aggregation questions to the dev set (run after make_dev.py)
python src/make_pairs.py            # training pairs (train/pairs_raw.jsonl)
python src/filter_pairs.py --test eval/test.jsonl   # drops pairs too close to a dev or test question
python src/make_test.py             # builds eval/test.jsonl from eval/test_draft.jsonl
python src/test_validator.py        # validator, parser and pipeline tests
python src/test_scorer.py           # scorer tests against every test gold
python src/run_eval.py --client fake --split dev --limit 10   # plumbing check, no model
```

Scoring a model server (PowerShell, each line on its own):

```
$env:LLM_URL = "http://127.0.0.1:8080"
$env:LLM_API_KEY = "your_key"
$env:LLM_TAG = "run-name"
python src/run_eval.py --client llm --split dev
```

Useful options: `--queries Q4,Q5` runs only those queries, `--limit N` runs a sample, `--resume results/<file>.jsonl` continues an interrupted run (it refuses if the prompt changed), and `--client replay --replies <file>.jsonl` scores replies generated elsewhere. The client sends temperature 0, at most 512 new tokens, and thinking off.

The tester question files are in `eval/test_raw/`. The test set is frozen before any model runs and is scored once; it is never uploaded to the training notebooks, and its questions reach the model only through the server.

## Roadmap

- [x] Setup (environment, Neo4j, libraries, models)
- [x] Data triage and cleaning
- [x] Graph design
- [x] Graph build
- [x] Place extraction from incident text (Areas and Localities)
- [x] Embeddings and clustering
- [ ] Trained models
  - [x] Validator, dev and test sets, training pairs, scorers
  - [x] Base-model bake-off and fine-tune (Gemma 4 E4B)
  - [x] Shipped GGUF file checked on the dev set
  - [ ] Test run: fine-tuned against untrained, with sign test
  - [ ] Scope guard
  - [ ] Publish the GGUF with a model card; test Ollama; measure GPU memory
- [ ] Cross-event analysis queries (query library and the Q10 handler)
- [ ] Question-answering layer
- [ ] API and interface
- [ ] Evaluation and comparison
- [ ] Packaging and documentation

## License

See [LICENSE](LICENSE). The fine-tuned model is a modified version of Google's Gemma 4 E4B, which is licensed under Apache 2.0; the published model file will include that licence and a notice that the weights were modified.