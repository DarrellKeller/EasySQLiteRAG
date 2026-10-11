# Local RAG frontend integration

Use the supplied Vite frontend: `index.html`, `src/main.js`, `src/styles.css`, `package.json`, lockfile and `vite.config.js`. Preserve the layout and connect its API endpoints; do not build a replacement UI. It has no bundled dataset, CDN fonts or frontend credentials. The title is Local RAG, without a subtitle; pages are Chat and Map.

From the frontend directory run `npm ci` and `npm run dev`. Vite serves `http://127.0.0.1:5173/` and proxies `/api` to the FastAPI backend at `http://127.0.0.1:8000`. Node 22.12+ is a suitable baseline. Without a backend it shows No database connected; with an empty backend it shows No data indexed yet and an empty map. Never substitute a sample collection.

Run `npm run build` for production. Serve only its `dist/` output through FastAPI, registering API routes before the static mount. Vite preview serves built assets but is not a replacement for the API server. Keep private settings in the backend `.env`; never expose model keys using `VITE_` variables. Use the frontend directory as Vite's root and keep its filesystem access restricted.

Colors chosen during intake go through `/api/config` into existing `--primary` and `--secondary` tokens and map group colors. Keep neutral reading surfaces, text contrast, visible focus and uniform borders. The frontend darkens excessively light accents; confirm the resulting colors with the user if that changes their requested appearance substantially. Add theme tokens only as needed; preserve components and navigation.

## Backend contract

Serve the Vite build and `/api/…` routes on the same origin. With FastAPI register API routes before mounting `frontend/dist/` at `/`. Mount only that build output, never `.env`, source documents or database files. Return JSON with appropriate error status codes and an `error` string. Validate requests, IDs, scope, limits and modes on the backend; frontend parameters are not authorization or unrestricted SQL.

The field definitions below describe shapes, not sample records. IDs are stable strings. Empty results are empty arrays; missing text is unavailable content, never fabricated data. All counts refer to the actual ingested corpus.

### GET /api/config

Return public configuration: optional `theme.primary` / `theme.secondary` six-digit hex colors. The frontend darkens light accents for readable white button text. Optional actual corpus counts may be exposed for integrations. Do not return secrets or override the Local RAG title with a marketing subtitle. Configuration retrieval must succeed even for an empty database.

### GET /api/nodes

Parameters: optional `parent_id`, `cursor`, and bounded `limit` (the frontend requests 100). No parent means roots. Return `nodes` and nullable `next_cursor`. Each node contains:

- `id`, nullable `parent_id`, `title`, `kind`, evidence-grounded `description`;
- `path` as an ordered array of titles; a precise source locator and optional safe HTTP(S) `source_url`;
- actual `child_count`, subtree `chunk_count`, and `status` (`ready`, `missing`, `partial`, or another documented status);
- optional `coverage_note` for unresolved gaps affecting this source.

Keep structural containers without text distinct from missing content. Hierarchy expansion loads direct children; Load more continues cursor pagination. Source titles are keyboard-accessible buttons that set branch scope; adjacent Preview buttons show descriptions/evidence. Native Tab/Enter/Space navigation works without interacting with the canvas.

### GET /api/nodes/{encoded_id}/chunks?limit=1

Return `chunks`, representative retrievable evidence from the eligible subtree. Return an empty array when text is unavailable, retaining the node's actual gap status/description. These previews must not embed export placeholders. Respect filters where applicable.

### GET /api/chunks/{encoded_id}

Return `id`, `node_id`, `title`, original evidence `text`, `path`, source `locator`, optional `source_url` and `coverage_note`. Search results use these stored IDs and may carry `source_refs` for identical eligible occurrences. Chat may return a derived `context-…` citation ID with a complete assembled excerpt and `source_refs` containing original chunk IDs, node IDs, titles, paths, locators and URLs. The dialog uses the returned text directly and shows its source locations; do not fetch a derived ID from the original-chunk endpoint. Original chunks remain retrievable under their stored IDs. The dialog displays text safely; source URLs permit only HTTP(S). For local documents, preserve file/page/row anchors and optionally implement a dedicated validated local-source route rather than exposing arbitrary file paths through a file server.

### POST /api/search and POST /api/chat

Accept `query` (original question), nullable `scope_node_id`, `group_ids` (array of actual selected groups), `mode` (`hybrid`, `keyword`, `semantic`) and bounded `history` entries with `role`/`content`. Null scope and empty groups mean the full eligible collection. Selected groups are combined as OR within the hierarchy scope. Filter eligible records **before** lexical limits and vector ranking. Reject unknown IDs rather than silently dropping a filter.

Search returns `results` (chunks), optional `coverage_note` and a backend `trace`. Chat returns `answer`, `citations` (chunks), `insufficient_evidence`, optional `coverage_note` and a backend `trace`. The model itself returns the smaller Pydantic-validated shape `answer`, `citation_ids`, `insufficient_evidence`; the backend resolves those IDs into trusted chunk/source objects. See [structured model output](model-output.md). Numbered answer references correspond to citation list order; validate every cited ID against evidence. An unsupported question gets an honest answer and no invented citation. Model failures produce clear errors, with keyword browsing still available.

The frontend sends up to eight recent successful chat turns, clears history on filter changes, and cancels/discards pending answers on scope changes or Stop. Backend context budgeting is still required. Displayed old messages retain scope labels. The Sources only checkbox switches submission to retrieval without generation. Enter submits; Shift+Enter inserts a newline; IME composition must not submit. Hybrid/Semantic/Keyword are accessible radio controls, shared with map search.

### GET /api/map

Parameters: optional `scope_node_id`, repeated `group_ids`, `query`, `mode`, `cursor`, bounded `limit` (frontend requests 5,000). Empty query returns the eligible map points, paginated. Nonempty query uses the same real retrieval implementation as source search. If a search is ranked/top-k rather than exhaustive, say so in `coverage_note` and count the returned search set accurately.

Return `points`, `groups`, `total_points`, nullable `next_cursor`, optional `coverage_note` and a `trace` for nonempty search queries:

- Each point has stable `id`, `chunk_id`, `node_id`, `title`, ordered `path`, optional `group_id`, and finite numeric `x`/`y`.
- Coordinates are persisted 2D projections of the actual embedding collection, not a circular tree layout, random values, fixture positions or newly recomputed positions after each filter. Link every point to real evidence. Exclude unavailable embeddings without concealing those sources in hierarchy/status views.
- Groups have stable `id` and grounded `title`. Return the available group directory for the hierarchy scope, including groups currently unselected, so filters can always be adjusted. Colors are supplemental; titles and List selection carry meaning independently.
- `total_points` is the actual result-set count, including not-yet-loaded pages. Cursor pagination must be stable for that result set. The UI deduplicates point IDs, displays loaded/total counts, and exposes Load more.

Generate map coordinates during preparation. Use a verified UMAP implementation when suitable, or PCA for a lighter dependency/hardware path. Record method, parameters, model/configuration hashes and projection version on the backend. Handle zero/one/two valid points safely rather than inventing a population or inferring clusters. A dimensionality-reduction layout is a navigation aid, not evidence that two records have a factual relationship. Projection and optional clustering do not change exact retrieval into ANN.

The map is a white canvas with colored outlined points, subtle dashed center axes, pan/zoom, Fit, hover titles and selected-source dialogs. It deliberately has no decorative hierarchy edges or radial hub. Hierarchy browsing belongs in Filters. List provides all loaded points through progressively expanded keyboard-accessible buttons, with API Load more for additional pages. No fixed drawing cap silently omits part of the collection.

### GET /api/issues

Return `issues` from the actual ingestion issue register. Each issue has stable `id`, `title`, `message`, actual `locator`, optional `node_id`, pending `question`, `status`, and affected count/severity fields as appropriate. Aggregate repetitive failures with meaningful counts and locators. Do not bake in an assumed number or format-specific problem.

The frontend checks after setup and successful requests, and every 15 seconds while the connected page is visible. Unresolved issues display a Data issues control; failed quality checks display Data status unavailable. Resolved issues disappear from the active panel but stay in the backend audit trail. Source previews and answers must include coverage notes when relevant gaps affect them.

The development agent asks the user about issues during extraction/chunking/indexing, records decisions and continues unaffected work. This panel keeps those problems visible after intake; it does not replace those conversations or imply a gap was resolved merely because partial ingestion was accepted.

## Acceptance

Verify real ingestion, FTS5, embeddings, map projection and generation separately from frontend tests. Temporary test fixtures may test API contracts, but must not ship as a dataset or appear as a fallback in the delivered app. Check empty/disconnected states, API errors, delayed/stale responses, safe text/URLs, filtered searches, model outages, data-quality updates, point selection, drag/zoom/Fit, keyboard hierarchy/List, pagination and mobile overflow. Keep the title and navigation simple; source details and quality explanations appear only when needed.

## Starter backend and ingestion

The standalone repo includes a FastAPI/Pydantic backend with empty SQLite tables, synchronized FTS5, filtered exact vector retrieval, ranked fusion, stored-coordinate map pagination and a schema-validated local Ollama adapter. It never imports or invents data on startup. A [MarkItDown extraction command](extraction.md) supplies local document-to-Markdown conversion and a source/hash/issue manifest. The coding agent reviews extraction, adds format-specific parsers/anchors as needed, transfers unresolved issues to SQLite, and designs dataset-specific ingestion, chunk boundaries, embedding inputs, hierarchy and map projection. Optional query expansion, follow-up planning and exhaustive record enumeration must be implemented and validated for the recipient's workflow; the starter explicitly labels its bounded retrieval as ranked matches. A static build or an empty API proves setup, not answer quality.

## Optional search traces

Render traces as collapsed native details elements, not a permanent activity panel. A trace contains `query`, `mode`, nullable `scope_node_id`, `group_ids`, actual `expansions` and ordered `steps`. Steps contain `name`, `status` (completed/skipped/failed), factual `detail`, measured `duration_ms`, nullable `result_count` and ordered `result_ids`. Show the real FTS MATCH expression, BM25 ordering, embedding model/config, exact scored-vector count/dimensions, rank fusion and limits. The original-query starter has no expansion or synonym/typo correction; do not imply these ran. Errors can return the partial trace so users can see which step failed. Preserve it on model errors. A map without a search simply retrieves stored coordinates and does not need a search trace. Never expose secret settings or model chain-of-thought.
