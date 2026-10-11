# EasySQLiteRAG

Turn your own data into a local SQLite RAG app with a provided Vite UI, FastAPI/Pydantic backend, source-backed chat and a point map. The app is titled **Local RAG**. This starter ships with **no documents, sample records, embeddings or database**.

The included skill tells your coding agent how to inspect your data, ask the necessary questions, design chunking/hierarchy, flag missing content during processing and connect the app. It starts with POTION-base-2M embeddings and Granite `granite4.2:3b` through Ollama after confirming those choices with you. Stronger models need agent-configured backend adapters and settings.

## Use with your coding agent

1. Open this repo folder in Codex, Claude Code, Gemini CLI or another coding agent that can read/edit local files.
2. Put your actual input files in `documents/`, or leave them elsewhere and tell the agent their path. `documents/`, databases and `.env` are ignored by Git. Do not use this repo's source code as the dataset.
3. Paste this exact message into the agent:

```text
Read skills/easy-rag/SKILL.md and follow it to configure this EasySQLiteRAG repo for my own data. Read the linked frontend and model-output references when integrating those parts.

First inspect this folder for my data. If the intended sources are missing or ambiguous, ask me where they are and which to include. Ask whether POTION-base-2M and Ollama granite4.2:3b are acceptable, and ask for optional theme colors.

Use the existing Vite UI and FastAPI/Pydantic backend. Keep the Local RAG title and layout. Have the answer model use simple instructions and return schema-validated JSON. Do not invent or add example data.

Inspect the source structure, preserve its hierarchy and citations, and design chunking for my actual files. Detect extraction problems and missing or truncated content, including PDF and spreadsheet gaps. Tell me where the problems are and ask follow-up questions as they appear, not just during onboarding. Continue unaffected work while answers are pending.

Populate SQLite, implement any dataset-specific ingestion and retrieval pieces that are needed, compute stable map coordinates from real embeddings, and connect the supplied chat, map, filters and issue panel. Preserve keyword browsing if a model is unavailable. Run the skill's checks against my data and selected models, then give me exact startup commands and an honest coverage report. Keep documents, generated data and secrets out of Git. Do not push, publish or install the skill globally.
```

No global skill installation or agent-specific slash command is needed: the prompt directs the agent to the local instructions. Answer its data/model questions, and let it complete the setup. Private documents may be visible to the coding agent's provider even when the finished app uses local models; choose an agent environment suitable for your data.

## Run the starter

Use **Python 3.11+** and **Node.js 22.12+**. Docker is not required. From the repo root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e './backend[dev]'
cp .env.example .env
npm --prefix frontend ci
npm --prefix frontend run build
python -m uvicorn local_rag.app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**. Startup creates empty tables in `data/rag.sqlite3`; it does not ingest files or download models. Expect an empty app until your agent processes your data. Do not overwrite an existing `.env` when rerunning setup; preserve your chosen settings.

After accepting local embeddings, install their optional dependency:

```sh
source .venv/bin/activate
python -m pip install -e './backend[embeddings]'
```

Install/start [Ollama](https://ollama.com/) if needed, then download the selected answer model:

```sh
ollama pull granite4.2:3b
```

The coding agent handles the first embedding-model download during ingestion. Model downloads require internet and disk space; generation needs adequate RAM and can be slow on limited CPUs. Larger models can improve quality. Changing embedding model/configuration requires re-embedding and rebuilding map coordinates. Put provider credentials only in the backend `.env`; never use `VITE_` variables for secrets.

For frontend development, keep FastAPI running on port 8000 and use a second terminal:

```sh
npm --prefix frontend run dev
```

Open **http://127.0.0.1:5173/**. Vite proxies `/api` to FastAPI. Production uses the built frontend through FastAPI; no Node server is needed to serve that build. [Vite guide](https://vite.dev/guide/).

## What is provided

- `frontend/`: the existing Chat/Map UI on Vite, with shared filters, source previews, keyboard List navigation and ongoing data-quality warnings.
- `backend/local_rag/`: typed FastAPI endpoints, empty SQLite schema with FTS5 update triggers, scoped exact cosine retrieval and rank fusion, stored-coordinate map pagination, and a local Ollama JSON adapter.
- `skills/easy-rag/`: the included ingestion/setup skill, UI contract, model-output instructions and validation workflow.
- `.env.example`: local model defaults and theme settings, without credentials.

The backend sends the model Pydantic's JSON schema, validates its returned JSON, rejects unsupported citation IDs and allows at most one repair attempt. Source objects come from the database. JSON validation helps enforce structure; it does not prove answer correctness. [Ollama structured output](https://docs.ollama.com/capabilities/structured-outputs).

Your agent still builds the extractor and ingestion workflow appropriate to your data, chooses chunk boundaries, prepares embeddings/maps and checks quality. The starter uses the original query and bounded ranked retrieval. The skill directs the agent to add optional query expansion/follow-up planning and paginated exhaustive-list handling when needed; a ranked result list is not complete enumeration.

## How the map works

Each point links to an actual indexed passage. The agent projects your embeddings into two dimensions, using UMAP where suitable or PCA as a lighter alternative, then stores coordinates in SQLite. Colors identify meaningful groups. Filtering reuses those coordinates so points stay in place. Nearby points suggest embedding similarity, not a proven factual connection. Hierarchy containers appear in Filters, and records with missing embeddings remain visible there or in Data issues. No positions or connections are fabricated.

Colors requested during setup configure `THEME_PRIMARY` and `THEME_SECONDARY` through `/api/config`; the existing UI applies them without a redesign and darkens overly light accents for contrast.

## Check your setup

```sh
source .venv/bin/activate
python -m pytest backend/tests
npm --prefix frontend run build
```

Automated tests create isolated temporary records to exercise retrieval and model validation; they are not a bundled dataset. Ask your coding agent to also validate actual extraction coverage, a few real searches/cited answers, missing content, model availability, map interactions and keyboard/mobile navigation as described in the skill. Model-output tests mock Ollama; passing them does not establish that your local model is installed or accurate.

When sharing, include source files and `frontend/package-lock.json`. Exclude `.env`, documents, SQLite databases, downloaded models, `.venv`, `node_modules`, `dist` and generated test outputs. The starter has no deployment or hosted database requirement.
