# Model weight classes and context count

Use these recommendations during onboarding. A **context count** is the maximum number of unique retrieved passages selected for an answer, configured by `RETRIEVAL_CAP`. It is not a number of documents or a token limit. A passage may be a section, coherent table group or another natural source unit. The separate model-token budget still governs how many complete passages fit.

## Recommend a starting class

| Class | Open models: published total parameters | Proprietary models: provider positioning | Recommended context count |
|---|---|---|---:|
| **Featherweight** | Up to 4B; **LFM3 1.7B is the default** | Never assigned | **3** |
| **Lightweight** | Over 4B through 14B | Budget / mini / nano tier | **5** |
| **Middleweight** | Over 14B through 70B | Standard / balanced tier | **10** |
| **Heavyweight** | Over 70B | Flagship / frontier tier | **15** |

These are project-defined setup bands and starting recommendations, not benchmark-proven optimums or promises about speed and accuracy. For open models, use the published total parameter count, including all experts in a mixture-of-experts model; active parameters describe compute requirements separately. Hosting an open model through an API does not make it proprietary. For proprietary models, use the provider's documented positioning. Reserve Featherweight for small open models; every proprietary model starts at Lightweight or above, including a provider's smallest or nano tier. This is a setup convention, not a claim that proprietary models universally outperform open models. Provider tiers do not imply equivalent capability across companies.

If an open model's parameter count is undisclosed, say so and propose 3 passages provisionally without claiming a verified size class. If a proprietary model's positioning is unclear, say so and propose Lightweight 5 provisionally; never assign it Featherweight. Do not invent specifications or infer a class from context-window size alone. An explicit user count takes precedence over every class recommendation, so a user may choose fewer passages without changing the model's class.

## Obtain sign-off in plain language

Present one recommendation and a brief reason, then ask for approval. For example:

> I recommend up to 5 passages per answer for this small local model. More may help it find related details, but replies can take longer. Use 5, or would you prefer another count?

Wait for approval before running answer generation with a newly proposed count. A prior explicit selection or approval of the stated recommendation is sufficient; do not ask again. Silence, an unattended default or approval of the model alone is not approval of its context count. Continue independent source inspection, extraction and other data preparation while waiting. Record the approved number in `.env` and the handover.

Keep explanations short and nontechnical. Mention the considerations that matter for the user's setup:

- **Speed and cost:** more input usually means more work; hosted input/output usage can cost money, while local models use the user's hardware. Reasoning time and provider queues can also dominate. Measure real response time rather than promise seconds from a class label.
- **Coverage and focus:** a larger count can admit a needed qualification or comparison, but unrelated evidence can reduce answer quality. Better ranking and coherent chunks matter as much as count.
- **Passage size:** five long passages can cost more than fifteen short ones. Before proposing a count, check typical passage lengths against the selected model's verified token budget, reserving output/repair space. If the recommendation will not fit, propose fewer passages or a verified larger context with its memory/cost tradeoff for approval. Pack whole passages; never cut text to force a class count to fit.
- **Question type:** a specific lookup may need fewer passages than a cross-document comparison. Exhaustive lists need scoped pagination and coverage checks rather than a very large top-k.

## Adjust with evidence, not automatic promotion

After approval, review a small representative set of real questions with known source answers. Track whether the needed passage was retrieved and packed, whether the answer and citations are correct, response time and provider usage. Distinguish retrieval misses from a model misreading evidence already present.

If a larger count is worth testing, keep data, ranking and questions fixed so the comparison is meaningful, and obtain approval for the trial counts. Recommend the smallest tested count meeting the user's quality and speed goals. Changing models does not silently reset a previously approved cap; discuss a new recommendation if needed.

Merging selected adjacent chunks preserves their complete text without adding a new seed. Fetching additional neighbors can exceed the seed count, so keep `CONTEXT_NEIGHBORS=0` unless the user approves a bounded expansion. Show actual selected/packed counts, joins and skipped passages in the optional trace. Never fill the model's entire context merely because space is available.
