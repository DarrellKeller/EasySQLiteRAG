# Agent-led setup and launch

Read this during setup. The user should only need to provide their data and answer necessary questions. Perform the commands yourself when tools and permissions allow; do not hand the user a technical checklist. Explain model downloads briefly before beginning. Preserve existing environments/settings and never overwrite unrelated work. Ask only for a user action you cannot perform, with one clear next step.

## Inspect prerequisites

Detect OS, architecture, available RAM/disk, Python, Node/npm and whether Ollama is already running. The backend requires Python 3.11+; Vite requires Node ^20.19.0 or >=22.12.0 (22.12+ is a suitable baseline). Prefer existing compatible tools. Check `.venv`, `.env`, installed models and existing services before creating duplicates. Runtime installs may need admin permissions; if blocked, give the user the exact official download/action, then resume after it is available.

If needed, install Python and Node using the user's existing trusted package manager or official installers: [Python](https://www.python.org/downloads/) and [Node.js](https://nodejs.org/en/download). On macOS with Homebrew already available, `brew install python node` is one option. Do not install a package manager solely for this task. Confirm versions after installation. Windows users may need a fresh terminal to see updated PATH.

## Create the local app environment

From the repo root, on macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e './backend[dev,embeddings,documents]'
npm --prefix frontend ci
npm --prefix frontend run build
```

On Windows use `py -3 -m venv .venv` after confirming its selected Python version, then `.venv\Scripts\python.exe -m pip install -e "./backend[dev,embeddings,documents]"`; npm commands are unchanged. Reuse an existing compatible `.venv`. Invoke its Python directly so activation and shell policy are unnecessary. If the user chose a different embedding adapter, install its actual dependencies rather than requiring Model2Vec.

Create `.env` from `.env.example` only if absent, then set confirmed choices. Preserve existing credentials and values. Keep model keys in this backend file, never `VITE_` variables or browser code. Keep it Git-ignored. Quote hex theme colors in `.env`, for example `THEME_PRIMARY="#163f3b"`. Defaults: `DATABASE_PATH=./data/rag.sqlite3`, `EMBEDDING_MODEL=minishlab/potion-base-2M`, `EMBEDDING_CONFIG_ID=potion-base-2M:cosine:v1`, `LLM_MODEL=granite4.2:3b`, `LLM_BASE_URL=http://localhost:11434`. Record the real embedding-input configuration and update its ID when it changes. Read [model-limits.md](model-limits.md), configure explicit embedding limits and the answer tokenizer/context/output independently, and verify them before ingestion.

Ask about the retrieval cap during onboarding. Configure `RETRIEVAL_CAP=5` for the selected 3B default, or the user’s value; for a different model use total billions of parameters + 2 as an adjustable starting heuristic. Keep `CONTEXT_NEIGHBORS=0` initially so selected adjacent passages merge without fetching extras for every hit. The unchanged 8K context is a ceiling, not an instruction to fill the prompt.

Verify SQLite FTS5 with a temporary in-memory `CREATE VIRTUAL TABLE ... USING fts5(...)` using the selected Python. If unavailable, select a compatible Python build; do not silently drop keyword search.

## Set up Ollama and the chosen local model

This applies after the local-model choice is confirmed. Local inference needs no Ollama account, cloud subscription or API key. Installing Ollama does not mean that the model is already downloaded or the service is running.

- macOS/Windows: use the [official Ollama download](https://ollama.com/download), install and open the app. If a trusted existing package manager can install it and the environment permits that, do so. Otherwise guide the user through only the installer action you cannot perform. On macOS an installed app can be started with `open -a Ollama`.
- Linux: use the [official installation instructions](https://docs.ollama.com/linux). Its standard installer is `curl -fsSL https://ollama.com/install.sh | sh`; inspect the installer before executing, and respect the environment's authorization rules. Do not start a duplicate system service.
- Check `http://localhost:11434/api/tags` for an actual JSON response. If Ollama is installed but not serving, start `ollama serve` as a managed background/terminal process. Keep localhost binding. Do not expose the model API publicly.
- Check the selected exact tag in `/api/tags` or `ollama list`. If absent, run `ollama pull granite4.2:3b` (or the confirmed alternative). Report download progress; verify success. If a tag is unavailable, ask about a replacement rather than silently changing it. Retry network failures reasonably; preserve useful keyword browsing while recovery is pending.
- Granite's current quantized 3B download is about 2.2 GB; working RAM and context overhead add to this. Measure on this user's hardware instead of promising speed. Keep the configured 8,192-token context unless a verified change is needed. Adjust context/output together, within the model's supported limits.
- Load the configured answer tokenizer using the supplied adapter (tokenizer files only, no PyTorch/model weights required), then make a real `/api/chat` request using the app's Pydantic-generated `format` schema, `stream=false`, `think=false` for Granite, temperature zero and configured context. Validate returned JSON and evidence IDs with the supplied backend adapter. Read [model-output.md](model-output.md). A tag listing proves availability, not that generation works. Record any unresolved inference failure.

Official references: [Ollama local quickstart](https://docs.ollama.com/quickstart), [Granite tag](https://ollama.com/library/granite4.2:3b), [structured outputs](https://docs.ollama.com/capabilities/structured-outputs). Verify current OS instructions/model availability if setup differs from these notes.

## Embeddings, ingestion and map

For the confirmed default, load `model2vec.StaticModel.from_pretrained("minishlab/potion-base-2M")` in the project Python environment. Use explicit `max_length=EMBEDDING_MAX_TOKENS` for both document and query encoding. Measure every document input first and split whole paragraphs/sections when needed; do not silently truncate. The configurable default is 512 library tokens, not POTION’s architectural limit. See [model-limits.md](model-limits.md). The first load downloads the model; verify it works before bulk ingestion. Use the same model, input preparation, dimensions and configuration for documents and queries. Batch encode actual chunks. Store float32 vectors and input/config hashes. Changing embedding models requires re-embedding and rebuilding the map; changing only the answer model does not.

The starter is empty and includes a reusable MarkItDown extraction command. Read [extraction.md](extraction.md), run `.venv/bin/python -m local_rag.extract documents --recursive` (or the confirmed source path), review its manifest and resolve/record extraction issues. This produces Markdown, not database records or embeddings. Implement a reusable dataset-appropriate ingestion command following the skill's extraction, hierarchy, chunking and issue rules, then run it on the selected files. It should be repeatable without duplicate records. Tell the user about gaps throughout processing. Compute persisted real map projections; do not add demonstration records to make the screen appear populated. Finish with real retrieval and a cited answer, or clearly report what is still unavailable.

## Run, verify and open

Run tests and the Vite build:

```sh
.venv/bin/python -m pytest backend/tests
npm --prefix frontend run build
.venv/bin/python -m uvicorn local_rag.app:app --host 127.0.0.1 --port 8000
```

On Windows replace the Python path as above. Launch Uvicorn in a managed terminal/background process and open `http://127.0.0.1:8000/` for the user after `/api/config` and the page respond. If the port is occupied, identify the service; reuse a verified matching app or choose another port and tell the user the actual URL. Do not kill unknown processes. For development, keep FastAPI on 8000 and run `npm --prefix frontend run dev`; it uses 5173 and proxies `/api` to 8000. Restart the backend after backend code or `.env` changes; rebuild the frontend after UI changes when serving production.

Exercise the user's data through Keyword, Semantic and Hybrid modes. Inspect the optional backend traces to verify actual searches and filters. Test Enter, Shift+Enter and Sources only, a cited answer, source preview and the real map. Make sure data and `.env` are not statically served. After required downloads, verify offline operation if claiming it.

Hand over the working URL, a short coverage/gap report and the exact restart command for this OS and chosen port. Keep detailed technical notes in project documentation rather than overwhelming the user's first-run instructions. If tools or inference are blocked, say exactly what remains and how to resolve it; never label an empty frontend a completed RAG app.
