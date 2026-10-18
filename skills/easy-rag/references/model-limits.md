# Model limits, chunking and complete evidence

Read before choosing chunk sizes or configuring a different model. Embedding limits and answer-context limits are separate. Token counts are model-specific; a character, UTF-8 byte and token are different units. Never compare a byte/character count to a token budget.

## Selected defaults

| Setting | Default and meaning |
|---|---|
| Embeddings | `minishlab/potion-base-2M`, Model2Vec; static pooled 64-dimensional vectors |
| `EMBEDDING_MAX_TOKENS` | `512`, explicit configurable encoder cap for both queries and document inputs |
| Answer model | Ollama `granite4.2:3b`; keep this Featherweight default unless the user chooses otherwise |
| `LLM_TOKENIZER_MODEL` | `ibm-granite/granite-4.2-3b`; official fast tokenizer and chat template |
| `LLM_TOKENIZER_REVISION` | `main`; resolve and record the downloaded revision for reproducibility, or pin a verified revision |
| `LLM_CONTEXT_TOKENS` | `8192`, intentionally below Granite’s published 131,072-token architectural maximum |
| `LLM_MAX_OUTPUT_TOKENS` | `768`, reserved for compact JSON answers with thinking disabled |
| `LLM_CONTEXT_RESERVE_TOKENS` | `512`, additional token allowance for provider/template variation; repair is also counted explicitly |
| `RETRIEVAL_CAP` | `3` for Featherweight / Granite 3B; recommend `5` for Lightweight, `10` for Middleweight or `15` for Heavyweight, then obtain user approval; see [retrieval-settings.md](retrieval-settings.md) |
| `CONTEXT_NEIGHBORS` | `0`, merge selected neighbors without automatically fetching extra context; enable a bounded amount only for demonstrated continuations/dependencies |

These are starting settings, not universal optimal sizes or minimum hardware guarantees. Verify exact installed models, tokenizers and provider behavior.

POTION does not have a transformer position-window limit of 512. Model2Vec commonly defaults to truncating `encode` inputs at 512; `max_length=None` disables that cap. The starter deliberately uses an explicit cap. Increasing it is allowed after reviewing the data and measuring retrieval quality; longer pooled passages can dilute specific details. Do not assume that accepting a whole document makes its embedding useful for finding every detail. See [Model2Vec implementation](https://github.com/MinishLab/model2vec/blob/main/model2vec/model.py) and [POTION model card](https://huggingface.co/minishlab/potion-base-2M).

Granite’s context maximum is documented in its [official configuration](https://huggingface.co/ibm-granite/granite-4.2-3b/blob/main/config.json). A large supported maximum does not mean a modest laptop should allocate it. Keep the 8K application setting initially; verify memory, latency and provider limits before increasing it. Obtain the official tokenizer files independently of the model weights; the starter’s Transformers dependency works for tokenizers without PyTorch. Never install another copy of the generation weights for token counting.

## Embedding configuration

1. Verify the chosen encoder/tokenizer and any automatic truncation. Include titles/ancestry when measuring the complete embedding input, not only body text.
2. Select an explicit cap and natural boundaries suited to the data. Keep qualifications and exceptions together where practical. Do not force a page break to create a new semantic section. If splitting, retain stable section IDs, source order and precise citations so retrieval can reconnect continuations.
3. Confirm every input fits before encoding. Do not rely on encoder truncation to hide oversized content. Use identical preprocessing, tokenizer, cap and model configuration for document/query vectors. Reject or explicitly revise oversized queries.
4. Changing the cap, input construction, model, normalization or dimensions requires rebuilding affected embeddings/map and recording a new configuration ID. A generation-model change alone does not require re-embedding.

## Answer configuration

Verify usable context, output limit, tokenizer/chat template and schema overhead for the selected local or remote provider. Configure the actual tokenizer separately from the provider’s model tag. When switching away from the default, explicitly supply a verified tokenizer or implement the provider’s official counting endpoint; do not inherit Granite’s counter. Implement and test remote adapters before claiming they work.

Count the complete prompt with the actual answer tokenizer/template: instructions, question, full evidence with ancestry/locators, schema and allowed citation IDs. Reserve the configured output allowance and template/provider overhead. Account for the one possible repair message before the first call. Build the final schema constraints before measuring.

Deduplicate identical bodies (whitespace-normalized, case/numbers/punctuation preserved), retaining all eligible source occurrences. Merge only verified contiguous selected chunks from the same section in source order; remove exact suffix/prefix overlap and retain the full union of evidence. Original chunks remain available for previews. The starter returns assembled citations with `source_refs`; the trace reports joins, duplicates and overlap removed. A derived context ID refers to the assembled excerpt returned in the response, not a new stored document.

Pack whole passages in priority order, skipping entire passages that cannot fit and continuing to smaller later ones. A merged run is prioritized by its strongest seed; if it cannot fit, try its complete original subunits in retrieval priority order. Return included and skipped IDs in the optional trace, including oversized derived runs that fall back. Never silently prefix-cut, halve text or remove the end of a rule. A section too large for one original passage needs appropriate complete subunits at ingestion. When all evidence is too large, report this directly rather than returning a fabricated answer.

Compare actual provider `prompt_eval_count`/usage with the local counter on representative real calls; investigate differences beyond the reserve. Verify one long but fitting passage remains unchanged in the provider request, and a truly oversized passage is skipped without starving later evidence. Preserve original evidence for source previews; retrieval metadata or grounded navigation summaries are not replacements for the underlying text.
