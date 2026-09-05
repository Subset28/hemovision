# OpenRouter Integration Audit — Phase H Retry Failure Analysis

Audit only. Zero live chat-completion HTTP requests were made in the course of this
work. `research/llm_usage.json` is unchanged (`{"2026-09-05": 3}`) before and after.

Every conclusion below is labeled **VERIFIED** (directly observed in code/artifacts),
**STRONGLY SUPPORTED** (evidence points one way, no live confirmation possible),
**PLAUSIBLE** (a reasonable hypothesis, not the only one), or **UNKNOWN** (cannot be
determined from retained evidence).

---

## 1. Executive conclusion

Both real bugs of Phase H's *first* attempt (router fallback-loop burning 3 requests
on 1 step) were already fixed before this retry, and that fix (`_call_llm` in
`research/dry_run/pipeline.py`) is confirmed correct by code inspection — **VERIFIED**.

Of the retry's three failures:
- **Laguna 429**: consistent with free-tier/shared-model throttling, not an OmniLab
  bug — **STRONGLY SUPPORTED**.
- **LFM "empty completion"**: OpenRouter's own envelope was well-formed but
  `choices[0].message.content` was empty/whitespace; root cause behind *why* the
  model produced nothing is **UNKNOWN** because no raw diagnostic was retained.
- **Nemotron "HTTP 200 but empty/non-JSON"**: **this is a confirmed, real gap**, not
  simple free-tier flakiness. OpenRouter's envelope parsed fine and `message.content`
  was non-empty (the call is recorded `succeeded: true` with a real `model_used`) —
  the JSON error happened one layer up, in OmniLab's own client-side parser
  (`research/llm/structured_output.py::_parse_json_object`) trying to `json.loads()`
  the model's raw text reply. OmniLab never asked OpenRouter for structured output in
  the first place (no `response_format` is ever sent — **VERIFIED**), so any model
  that doesn't reply with a bare, fence-free JSON object as its entire message will
  fail this check regardless of whether OpenRouter's request succeeded. This is
  OmniLab's failure mode, not an OpenRouter defect — **VERIFIED** for the mechanism,
  **PLAUSIBLE** for markdown-fence-wrapping being the specific cause (content itself
  was never retained to confirm).
- No proposal was fabricated or manufactured to compensate; the pipeline's stop
  conditions and validation were not weakened during this audit — **VERIFIED**.

Phase H remains blocked. Nothing in this audit unblocks it. No code change was made
that affects behavior (see §20).

---

## 2. Documentation consulted (real URLs, fetched during this audit)

- `https://openrouter.ai/docs/api-reference/chat-completion` — request/response
  schema: `model`, `messages`, `response_format` (text/json_object/json_schema/
  grammar/python), `max_tokens`/`max_completion_tokens`, `provider` routing
  preferences; response envelope (`id`, `model`, `choices[].message.content`,
  `choices[].finish_reason`, `usage.{prompt_tokens,completion_tokens,total_tokens}`);
  error envelope `{error: {code, message, metadata}}` for 4xx/5xx (400/401/402/403/
  429/5xx).
- `https://openrouter.ai/docs/features/structured-outputs` — `response_format:
  {type:"json_schema", json_schema:{..., strict:true}}` is a request-time opt-in;
  "Support is determined per endpoint, not just per model"; catalog exposes a
  `structured_outputs`/`response_format` capability per model+provider; an
  unsupported model "will fail with an error indicating lack of support" (no silent
  fallback); `require_parameters: true` in `provider` preferences restricts routing
  to compatible endpoints only; a "Response Healing" plugin exists to repair
  malformed JSON from imperfect model output.
- `https://openrouter.ai/docs/features/model-routing` — the documented mechanism is
  `openrouter/auto`/`openrouter/auto-beta` (spend-weighted auto-routing via a
  `plugins: [{id:"auto-router", ...}]` config), not a `models:[...]` array or a
  `route` parameter (these appear to be from an older/different doc generation, or
  do not currently exist as documented top-level request fields — **UNKNOWN** whether
  a `models` array still exists as a separate mechanism; not found in the fetched
  page). Response always carries a `model` field identifying which model actually
  answered, confirmed for auto-routing.
- `https://openrouter.ai/docs/api-reference/limits` — two independent limit
  categories: credit limits (402 on exhaustion) and rate limits (429). Free model
  (`:free` suffix) requests are capped by lifetime spend tier: below $10 spent →
  20 req/min & 50 req/day; $10+ spent → 20 req/min & 1000 req/day; these are
  **platform-wide / free-tier caps that key off account spend tier, not a strictly
  isolated per-account small quota** — importantly the doc frames this as a
  request-frequency cap tied to the `:free` variant, consistent with shared
  capacity/model-level throttling rather than a generic per-account daily
  chat-completion budget. Rate-limit responses carry `X-RateLimit-Limit`,
  `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers when OpenRouter itself
  enforces the cap; provider-side 429s may carry `provider_code` metadata and
  `Retry-After` instead.
- `https://openrouter.ai/api/v1/models` (public catalog, unauthenticated GET — not a
  chat completion, permitted) — queried for the three models actually attempted:
  - `liquid/lfm-2.5-2.6b:free` — exists, context_length 65,536,
    `supported_parameters` includes **`response_format` and `structured_outputs`**.
  - `nvidia/nemotron-3.5-lightning:free` — exists, context_length 1,000,000,
    `supported_parameters` = `include_reasoning, max_tokens, reasoning, seed,
    temperature, tool_choice, tools, top_p` — **no `response_format`, no
    `structured_outputs`**. Also exposes `reasoning`/`include_reasoning`, i.e. it is
    a reasoning-capable model whose thinking tokens can consume part of the
    `max_tokens` budget if not explicitly suppressed.
  - `poolside/laguna-s-2.1:free` — exists, context_length 262,144,
    `supported_parameters` = `include_reasoning, max_tokens, reasoning, temperature,
    tool_choice, tools` — **no `response_format`, no `structured_outputs`**; also a
    reasoning-capable model.

No other OpenRouter endpoint was contacted. No chat-completion request was made.

---

## 3. Request-path audit — is our request format correct?

Traced `research/dry_run/pipeline.py::_call_llm` → `LLMRouter._role_config` (reads
`research/llm/roles.yaml`) → `OpenRouterProvider.complete()` →
`OpenRouterProvider._dispatch()` (`research/llm/openrouter.py:173-259`).

Exact JSON body constructed (`openrouter.py:137-140`):
```json
{
  "model": "<role_cfg.preferred_model>",
  "messages": [{"role": "user", "content": "<full rendered prompt>"}],
  "max_tokens": 1024   // researcher; 768 for reviewer — from roles.yaml
}
```
No `temperature`, no `response_format`, no `provider` preferences, no `seed`, no
`tools`. `messages` is always a single `user`-role turn — the system policy text
(`research/llm/prompts/system_policy.md`) is concatenated as plain text at the top of
the *user* message by the prompt templates (`researcher_proposal.md` /
`reviewer_critique.md`), not sent as a `system`-role message.

Prompt size: `researcher_proposal.md` embeds the full `context_packet_json` (Phase E
memory context) plus the system policy text plus the candidate-problem list plus the
full required-JSON-schema example. Rough size at time of the failed calls: several KB
of JSON + ~1-2KB of instructions — a conservative estimate is 1,500-3,000 input
tokens, well under all three models' context windows (65K-1M) but **not small
relative to a 1,024-token *output* budget** if a reasoning-capable model spends
tokens thinking before answering.

Comparison against OpenRouter's documented schema (§2): every field OmniLab sends
(`model`, `messages`, `max_tokens`) is a documented, current field — **VERIFIED,
nothing malformed or deprecated is sent**. Nothing undocumented is sent. The gap is
what is *not* sent: no `response_format` (see §4), and for the two reasoning-capable
models, no `reasoning: {exclude: true}`/`max_tokens` split to bound reasoning-token
spend, which the docs list as an available parameter (`reasoning`) neither model role
config nor the provider ever populates.

---

## 4. Structured-output implementation — correct, but it's prompt-and-hope, not native

**VERIFIED**: `OpenRouterProvider.complete()`/`_dispatch()` never constructs or sends
a `response_format` field (`openrouter.py:137-140`, confirmed by reading every line —
`body` is built from exactly `model`, `messages`, optional `max_tokens`, then
`body.update(kwargs)`; nothing in `router.py::complete()` or
`pipeline.py::_call_llm`'s `call_kwargs` ever sets `response_format`). Compliance is
requested entirely via plain-text instructions in the prompt templates ("Respond with
ONE JSON object and nothing else (no markdown fences, no prose outside the JSON)" —
`researcher_proposal.md:60-61`), and enforcement happens **entirely client-side**,
after the HTTP round-trip, in `research/llm/structured_output.py::parse_and_validate_proposal`
→ `_parse_json_object` → `json.loads(raw_text)`.

This is a deliberate, working design for the JSON-*parsing* concern (it correctly
rejects invalid/adversarial payloads, and its forbidden-field checks are sound and
independently tested) — but it means "structured output compatibility" per §7's OpenRouter
capability metadata was never actually exercised, because OmniLab never asks OpenRouter
to enforce anything. The parser also does **not** strip common LLM artifacts before
`json.loads` — no markdown-fence stripping (` ```json ... ``` `), no leading/trailing
prose trimming, no first/last-`{`/`}` extraction. This is a real, narrow gap
(**VERIFIED** by reading `_parse_json_object`, `structured_output.py:206-215`, which is
a bare `json.loads(raw_text)` with no preprocessing).

---

## 5. LFM 2.5 "empty completion" — exact diagnosis

`DRYRUN-0002.json`'s only `call_record`: `error: "OpenRouter returned an empty
completion"`, `model_used: null`, `succeeded: false`.

The exact code path (`openrouter.py:224-244`):
```python
data = resp.json()                              # succeeded (no MALFORMED_RESPONSE)
choices = data["choices"]; text = choices[0]["message"]["content"]   # succeeded (no shape error)
if not text or not str(text).strip():
    raise OpenRouterProviderError("OpenRouter returned an empty completion",
                                   category=ErrorCategory.EMPTY_RESPONSE)
```
So: the HTTP response was 200, the JSON envelope parsed, `choices[0].message.content`
existed as a key and did not throw a `KeyError`/`IndexError`/`TypeError` — but its
value was either `""`, `None`-coerced, or all-whitespace. **VERIFIED** this is the
exact and only condition that produces this literal string.

Does the code retain the raw response anywhere for diagnosis? **No — VERIFIED.** Once
`OpenRouterProviderError` is raised, only its message string (`"OpenRouter returned an
empty completion"`) propagates; `resp`, `data`, `finish_reason`, `usage`, and the
request id are all local variables inside `_dispatch()` that are discarded on the
exception path (they are only attached to `LLMResponse` on the *success* return at
`openrouter.py:251-259`). `CallRecord` (`pipeline.py:132-137`) stores only
`step, role, model_used, succeeded, error` — `model_used` is `None` on any failure
path (it's only populated from the successful `LLMResponse`), so the actual model that
answered isn't even distinguishable from "never reached the provider" in a failure
record.

**Conclusion**: the raw response body was not retained/logged anywhere accessible; we
cannot determine from local artifacts whether `finish_reason` was `"length"` (cut off
before any content), `"stop"` with genuinely empty content, a content-moderation
refusal collapsed to empty string, or something else. **UNKNOWN** — not knowable from
retained diagnostics. `REQUIRES FUTURE CONTROLLED LIVE TEST` to resolve with certainty.

---

## 6. Nemotron "HTTP 200 but empty/non-JSON" — exact diagnosis (the important one)

`DRYRUN-0003.json`'s call record: `error: null, model_used:
"nvidia/nemotron-3.5-lightning:free", succeeded: true`. `stopped_reason`:
`"initial proposal response failed structured-output validation: response is not
valid JSON: Expecting value: line 1 column 1 (char 0)"`.

This is decisive: `succeeded: true` in the call record can **only** happen via
`pipeline.py:229-235`'s success branch, which is only reached if
`router.provider.complete()` returned a value rather than raising — which in turn
requires `_dispatch()` to have gotten past *both* the JSON-envelope parse (`resp.json()`,
`openrouter.py:224-230`) *and* the `choices[0].message.content` extraction
(`openrouter.py:232-239`) *and* the empty/whitespace check (`openrouter.py:241-244`)
without raising. In other words: **OpenRouter's own HTTP response envelope was
syntactically valid JSON, `choices` existed, `message.content` existed and was a
non-empty, non-whitespace string.** `response.text` (that content) was then handed to
`parse_and_validate_proposal(response.text)` (`pipeline.py:293`) →
`_parse_json_object` → `json.loads(raw_text)` (`structured_output.py:208`), and *that*
call is what raised `json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.

**This error is on `response.text` (the model's message content), not on OpenRouter's
outer envelope — VERIFIED, not inferred.** OpenRouter's own JSON parsing already
happened successfully one call earlier inside `_dispatch()`; if the outer envelope had
been malformed, the code would have raised `MALFORMED_RESPONSE` from
`openrouter.py:227-230` and the call record would show `succeeded: false`, which it
does not.

What does `"Expecting value: line 1 column 1 (char 0)"` mean given that the string is
known to be non-empty/non-whitespace (it passed the `openrouter.py:241` check)? This
exact message is what `json.loads()` raises whenever the very first non-whitespace
character of the input is not a valid JSON value start (`{`, `[`, `"`, a digit, `t`/`f`/`n`
for true/false/null, `-`). It is emitted identically whether the string is empty *or*
begins with any other character `json` doesn't recognize as a value-start — e.g. a
markdown code fence opener (`` ``` ``), a backtick, or the start of an unrequested
prose sentence ("Here is my proposal:..."). Since we've established the string is
non-empty, the only remaining explanations consistent with this exact message are:
the model wrapped its JSON in a code fence or preceded it with prose despite the
prompt explicitly forbidding both (**PLAUSIBLE** — the single most likely cause, given
`structured_output.py`'s parser does no fence-stripping, §4), or the model's true first
character was itself somehow non-ASCII/invisible in a way that still reads as
"non-whitespace" to Python's `.strip()` (far less likely).

This distinguishes it clearly from the LFM case: LFM's completion was empty at
OpenRouter's own extraction layer (`openrouter.py`); Nemotron's completion had real
content that OmniLab's own JSON parser rejected. **This is exactly the crux the user
asked about, and the answer is: the failure is in OmniLab's client-side parsing
expectations, not in OpenRouter's response.**

Could this be a token-limit/reasoning-token issue? Nemotron is confirmed
reasoning-capable (`include_reasoning`/`reasoning` in `supported_parameters`, §2) and
`roles.yaml`'s researcher `max_tokens: 1024` is not generous for a model that may spend
tokens on hidden reasoning before answering. However, a reasoning-token-exhaustion
failure mode would typically manifest as `content` being **empty** (all budget consumed
by reasoning, nothing left to emit) — which is exactly the LFM failure mode, not this
one, since here `content` was demonstrably non-empty and passed the empty-string
check. So while `max_tokens: 1024` is a real, independently worth-raising concern for
these reasoning-capable free models, it does not fit Nemotron's specific symptom as
well as the fence/prose-wrapping hypothesis does. **PLAUSIBLE, not the primary
explanation for this specific error.**

Because `response.text`'s actual content was never persisted anywhere (not in
`CallRecord`, not in the JSON artifact, not logged — the same gap as §5), the exact
first characters of the model's reply cannot be recovered from local evidence.
**UNKNOWN in the sense of "we cannot see the literal string"; STRONGLY SUPPORTED in
the sense of "the failure layer is definitively OmniLab's client-side JSON parser
acting on real model content, not OpenRouter's envelope."**

---

## 7. Laguna 429 — best-supported diagnosis

`DRYRUN-0004.json`: `error: "OpenRouter rate limit hit, HTTP 429"`, raised from
`openrouter.py:210-213`, which does nothing but map any HTTP 429 status to
`ErrorCategory.RATE_LIMIT` — it does **not** read or retain `X-RateLimit-Limit`/
`X-RateLimit-Remaining`/`X-RateLimit-Reset`/`Retry-After` headers, nor the error
response body's `error.metadata`/`provider_code` (**VERIFIED gap** — `resp.headers`
is never touched anywhere in `_dispatch()`).

Per §2's documented free-tier limits (20 req/min, 50-1000 req/day depending on
lifetime spend, keyed to the `:free` model variant) and the user's own observation
that their OpenRouter Activity dashboard shows only a handful of total requests
today: an account-level daily-quota exhaustion is inconsistent with "a handful of
requests total" against a 50-1000/day cap. A per-minute burst cap is also unlikely
given the low request cadence across this session (single digits, minutes apart per
DRYRUN artifact timestamps). This leaves upstream-provider capacity throttling
(OpenRouter passing through a 429 from the actual Poolside-served backend for this
specific free model, which is shared across all OpenRouter users of that slug) as the
best fit. This exact same model (`poolside/laguna-s-2.1:free`) also returned 429 in
Phase H's very first attempt (DRYRUN-0001), on a different day/session, which is
consistent with a chronically capacity-constrained free model rather than a one-off
account fluke.

Confidence: **STRONGLY SUPPORTED** (evidence points to a shared free-tier/upstream
capacity limit, not an account-level cap) — not **VERIFIED**, since this audit cannot
independently query OpenRouter's dashboard or the raw 429 response headers/body,
which were never retained.

---

## 8. Model-capability validation before requests

**Confirmed: no, capabilities are never checked before a request is sent.**
`LLMRouter._role_config()` (`router.py:77-97`) reads `preferred_model`/`fallback_models`
directly from `roles.yaml` as opaque strings; nothing in `router.py`, `pipeline.py`, or
`openrouter.py` ever calls `/api/v1/models`, caches its `supported_parameters`, or
gates model selection on any capability flag. This is why two of the three roles.yaml
entries currently point at models (`nemotron-3.5-lightning`, `laguna-s-2.1`) that the
catalog shows do **not** support `response_format`/`structured_outputs` at all — moot
today only because OmniLab never requests that mechanism (§4), but a real gap if that
changes later.

---

## 9. `openrouter/free` — tradeoff analysis (not adopted)

No live-fetched OpenRouter documentation page in this audit described a distinct
`openrouter/free` pseudo-model; the only documented auto-routing mechanism found was
`openrouter/auto`/`openrouter/auto-beta` (spend-weighted, not free-tier-specific) — **UNKNOWN**
whether `openrouter/free` exists as advertised in the task brief; treat any reference
to it as unconfirmed until independently verified against current docs.

Assuming a free-tier auto-router of this shape does exist:
- **Provenance**: auto-routing documentation confirms the response always carries a
  `model` field naming which underlying model actually served the request — if
  `openrouter/free` behaves like `openrouter/auto`, provenance is likely preservable
  (record `response.model_used` per call, which OmniLab already does for successes).
  **PLAUSIBLE**, not verified for this specific pseudo-model.
- **Structured-output awareness**: no evidence the auto-router considers
  `response_format`/JSON-mode requirements when selecting a backing model — the
  documented `require_parameters: true` provider preference is the *documented*
  mechanism for that, and it's a `provider` object we never send. **UNKNOWN** how
  `openrouter/free` intersects with it.
- **Reproducibility tradeoff**: a research lab that wants an experiment's proposal
  step attributable to a *specific, chosen* model (for later comparison/repro) loses
  some of that if the router silently varies models call-to-call — mitigated only if
  `model_used` is faithfully recorded and durable (it is, on success, in `LLMResponse`
  — but currently *not* persisted into `CallRecord`'s failure path or into the final
  JSON artifact beyond the single top-level `model_used` per call record, which is
  already recorded today).
- **Recommendation, not a decision**: worth a small controlled test later (§17) if
  free-tier reliability keeps being the recurring failure mode; do not adopt without
  first confirming the feature exists as documented and that it reports the serving
  model reliably.

---

## 10. Server-side (`models` array) vs. client-side fallback vs. pinned vs. `openrouter/free`

The fetched model-routing doc page did not surface a `models:[...]` server-side
fallback array as a currently-documented top-level parameter (only `openrouter/auto`
+ `plugins`) — **UNKNOWN** whether it still exists as a distinct feature under a
different doc path; the task brief describes it as if well-established, but this
audit could not independently confirm it in the pages fetched. Tradeoffs below are
therefore presented conditionally.

| Strategy | Availability | Cost control | Local budget accuracy | Auditability | Reproducibility | Role separation | Provenance | Failure semantics | Maps to a deterministic experiment record |
|---|---|---|---|---|---|---|---|---|---|
| **OmniLab client-side fallback** (original Phase H bug, now removed from `_call_llm`, still exists in `LLMRouter.complete()` for other callers) | High (tries N models) | Poor — 1 logical step can cost N real HTTP requests/budget units invisibly | Poor — `UsageTracker`/`RunBudget` see N calls for 1 logical step unless caller accounts for it | Good — each attempt is a separate, inspectable `CallRecord`-equivalent | Poor — which model "actually" answered varies run to run | Good — OmniLab fully controls per-role model lists | Good — records `model_used` for the one that succeeded | Fails logical step only if *every* listed model fails | Awkward — 1 logical step maps to N HTTP events |
| **OpenRouter server-side `models` array** (if it exists) | High, in 1 request | Better — 1 HTTP call from OmniLab's perspective, but true cost/attempts still unknown from OmniLab's side unless OpenRouter's response says how many were tried | **UNKNOWN** — does OmniLab's local per-call budget counters see 1 decrement or should they logically see N? Ambiguous without confirming what OpenRouter's Activity log shows per such a request | Weaker from OmniLab's side — the underlying attempt sequence lives in OpenRouter's account log, not a local artifact | Weaker unless the response's `model` field is captured every time (it is, per docs) | OmniLab still chooses the ordered list, so role separation intact | Preserved via the response's `model` field, if captured | One local exception only if *all* fail | Clean 1:1 HTTP-request-to-logical-step mapping, at the cost of losing local visibility into which attempts within it failed and why |
| **Pinned single model, no fallback** (Phase H's *current* `_call_llm` behavior) | Lowest — one dead/rate-limited model fails the whole step | Best — exactly 1 request per logical step, always | **Best** — 1:1, no ambiguity | **Best** — one `CallRecord` per logical step, one clear pass/fail | **Best** — the attempted model is always known in advance and recorded | Best — no ambiguity about which role used which model | Best — always known before the call | Fails immediately on any single-model issue (including a transient one) | Cleanest possible 1:1 mapping |
| **`openrouter/free`** | Unknown — depends on undocumented internals | Unknown | Unknown | Weakest — the actual serving model is opaque until the response arrives | Weakest — model varies per call unless recorded from response.model | Weakest — a "role" no longer maps to a chosen model, only an outcome | Conditionally preserved if response.model is always populated and captured (§9) | Unknown | Unknown |

No strategy is chosen here. The current pinned-single-model behavior in `_call_llm`
is the most auditable and reproducible of the four, at the direct cost of exactly the
availability problem Phase H is now hitting (a single dead/rate-limited free model
fails the whole logical step with no automatic recovery).

---

## 11. Response observability — gaps identified

What `CallRecord` (`pipeline.py:131-137`) currently retains for a failed call:
`step`, `role`, `model_used` (always `None` on failure — see §5), `succeeded=False`,
`error` (the exception's string message only).

What is **not** retained anywhere reachable from a persisted artifact, for either
success or failure:
- HTTP status code
- OpenRouter's own error code/body (`error.code`/`error.message`/`error.metadata`)
- request id (captured in `LLMResponse.request_id` on success but never copied into
  `CallRecord`, and entirely absent on failure since the exception path never builds
  an `LLMResponse`)
- `finish_reason`
- whether the JSON envelope parsed vs. not (currently collapsed into the same
  `MALFORMED_RESPONSE` category as a shape mismatch)
- whether `choices` existed at all vs. content being empty (collapsed into
  `MALFORMED_RESPONSE`/`EMPTY_RESPONSE` category names only, no structural detail)
- content length (not content itself — even the *length* is untracked)
- `usage` fields (`prompt_tokens`/`completion_tokens`/`total_tokens` — `LLMResponse`
  does capture `tokens_used` as an aggregate total on success only, never on failure,
  and it's not copied into `CallRecord`)
- latency (`LLMResponse.latency_ms` is computed on success only — a failed call's
  actual round-trip time is discarded, only the raised exception propagates)
- 429-specific rate-limit headers (§7)
- structured-parser failure detail beyond the raw exception string (e.g. "empty
  string" vs. "non-JSON-leading-character" vs. "missing required field X" are all
  just different text in the same `error` string field, not distinguishable
  programmatically)

This is a genuine, confirmed gap (**VERIFIED**) — it is the direct reason §5 and §6
above have to reason from indirect evidence (whether `succeeded` is true/false, plus
message text) rather than direct inspection. A concrete, safe, additive proposal
(not implemented in this audit, per §16): add `http_status: Optional[int]`,
`finish_reason: Optional[str]`, `content_length: Optional[int]`, and `request_id:
Optional[str]` to `CallRecord`, populated from `LLMResponse` on success and from a
small additional payload attached to `OpenRouterProviderError` (never the raw
prompt/response text) on failure — never persisting the prompt or completion body
itself, consistent with the existing secret-safety discipline in `openrouter.py`.

---

## 12. Usage-persistence (`research/llm_usage.json`) disappearance — root-cause

Exhaustive re-check performed:
- `grep -rn "LLM_USAGE_LOG\|UsageTracker(" research/ tests/` — every test-suite
  construction of `UsageTracker(...)` passes an explicit `path=tmp_path/...`
  (`test_llm_router.py`, `test_llm_openrouter_errors.py`, `test_llm_budget.py`,
  `test_dry_run_safety.py`, `test_dry_run_pipeline.py`) — **no test in the suite uses
  the real default path**. Only two call sites use the bare default
  (`UsageTracker()` with no `path`): `research/cli.py:239` and
  `research/llm/smoke_test.py:133` — both are real CLI/manual-script entry points,
  neither is exercised by pytest.
- `research/git_isolation.py::discard_non_experiment_changes` — re-read in full
  (`git_isolation.py:135-183`). Its `keep_prefixes` tuple explicitly includes
  `"research/"` (line 138). `research/llm_usage.json`'s git-relative path is
  `research/llm_usage.json`, which `.startswith(("research/", ...))` is `True` —
  **this function would NOT discard it**, whether tracked or untracked, since both
  the tracked-modification branch and the untracked-file-removal branch filter on
  the same `keep_prefixes` check. **VERIFIED this function is not the cause.**
- `git check-ignore -v research/llm_usage.json` → `.gitignore:20:research/llm_usage.json
  research/llm_usage.json` — the ignore pattern matches correctly, no exclude-standard
  edge case reproduced (confirmed directly against the live repo state, not a
  constructed reproduction — the pattern is a plain full-path literal with no glob
  ambiguity, so a cwd/timing edge case is very unlikely to apply here regardless).
- No `unlink`, `os.remove`, `shutil.rmtree`, or `Path(...).unlink()` call anywhere in
  `research/` or `tests/` targets this filename or a matching glob.

**Conclusion: UNKNOWN.** No code path in this repository was found that explains the
file's earlier disappearance between sessions. This is reported honestly as
unresolved, not guessed at.

Authority-model clarification (explicitly answered per the task): the local
`UsageTracker`/`llm_usage.json` counter is **OmniLab's own, sole, first-party
enforcement mechanism** for its daily call cap — it is checked *before* every real
call and is entirely independent of OpenRouter's own account Activity dashboard,
which OmniLab has no API access to query and which cannot be used as a
safety-relevant source of truth by design. Because this file is a plain, ungoverned
JSON file with no locking, no backup, and (per the above) an unresolved history of
having gone missing at least once, **a silent reset of this file is a real,
safety-relevant gap**: it would let the daily cap be exceeded across a reset boundary
without any code path noticing. Today's actual call volumes (single digits) are
nowhere near the 40/day cap, so the practical risk today is low, but the gap itself
is real and worth flagging plainly rather than dismissing because it hasn't mattered
yet.

---

## 13. Duplicated vs. necessary responsibilities

**Genuinely OmniLab's to own** (not something OpenRouter provides or should provide):
explicit authorization gating (`authorization.py`), local daily/per-run budget
enforcement (`base.py::UsageTracker`/`RunBudget`), privacy/injection guards
(`privacy_guard.py`, `injection_guard.py`), context packaging from Phase E memory
(`memory_context.py`), the proposal-vs-result field separation and forbidden-field
enforcement (`structured_output.py`, `experiment_spec.py`), and experiment-provenance
linking (`_placeholder_experiment_id`, `baseline_run_id`).

**Responsibilities that overlap with something OpenRouter already offers, and which
layer should own what going forward**:
- *Model availability/fallback selection*: OpenRouter's `models` array (if confirmed
  to exist, §10) or `openrouter/auto` should own the mechanics of trying alternate
  backends within a single logical request; **OmniLab should own the decision of
  which models are eligible for a given role** (the curated list in `roles.yaml`) and
  must always capture which one actually answered (`response.model`) into the
  persisted call record for provenance — today it captures this only on success, not
  systematically enough (§11).
- *Provider/capacity routing*: OpenRouter, not OmniLab, is positioned to know
  real-time upstream provider health; OmniLab should not attempt to re-implement
  429-aware backoff heuristics beyond what it already has (bounded retry for
  TIMEOUT/NETWORK_ERROR only, deliberately excluding RATE_LIMIT from
  `RETRYABLE_CATEGORIES` — correct, since immediate retry against the same
  rate-limited free model rarely helps).
- *Capability-based model selection* (does this model support JSON mode?): this
  should be OmniLab's decision (which models are configured per role) informed by
  OpenRouter's catalog data, but is currently not checked at all (§8) — recommended,
  not implemented, that `roles.yaml` model choices be periodically cross-checked
  against `/api/v1/models`' `supported_parameters` before being adopted, not
  validated automatically inside the hot request path.

---

## 14. Confirmed implementation bugs (evidenced only)

1. **No native structured-output request is ever sent** (`response_format` is never
   populated) despite `research/llm/structured_output.py` implying a
   parse-and-validate contract against model output — this is a design gap, not a
   crash, but it is the direct, confirmed mechanism behind the Nemotron failure
   (§4, §6). **VERIFIED.**
2. **`structured_output.py::_parse_json_object` performs no markdown-fence or
   leading-text stripping** before `json.loads` — a model that wraps valid JSON in
   ` ```json ... ``` ` or prefaces it with a sentence will always fail parsing even
   though its actual proposal content might be perfectly valid. **VERIFIED** by
   reading the function; **PLAUSIBLE** (not proven) as the specific cause of the
   Nemotron failure, since the raw text was never retained (§6, §11).
3. **`CallRecord`/`LLMResponse` observability gaps** enumerated in §11 — confirmed by
   reading every field each dataclass carries and every call site that populates
   them. **VERIFIED.**
4. **429 response headers/body are never read or retained** in `_dispatch()` — the
   status code alone drives categorization; `resp.headers` and the JSON error body's
   `error.metadata` are discarded. **VERIFIED.**
5. **Two of three `roles.yaml` free-tier model entries lack any `response_format`
   support** per the current OpenRouter catalog (`nemotron-3.5-lightning`,
   `laguna-s-2.1`) — moot today only because point 1 means it's never requested, but
   would immediately become a hard failure if native structured output were adopted
   without changing these models. **VERIFIED.**

None of these were fixed during this audit (per the task's explicit instruction and
§16); no code was changed.

---

## 15. Recommended minimal changes (not implemented)

- Add `http_status`, `finish_reason`, `content_length`, `request_id` to `CallRecord`,
  populated safely from `LLMResponse`/a small failure-detail object attached to
  `OpenRouterProviderError` — never the prompt or completion text itself (§11).
- Add fence/prose stripping (a narrow, well-tested pre-processing step — e.g. extract
  the first balanced `{...}` block, or strip a leading/trailing ` ```json `/` ``` `
  fence) to `structured_output.py::_parse_json_object` before calling `json.loads`,
  since the prompt already explicitly asks for bare JSON and models routinely ignore
  this instruction (§4, §6, §14.2).
- Capture 429 response headers (`X-RateLimit-Reset`/`Retry-After`) and the error
  body's `metadata` into the raised exception's (redacted, non-prompt) detail, so a
  future 429 is diagnosable without a live test (§7, §11).
- Periodically cross-check `roles.yaml` model choices against
  `/api/v1/models`' `supported_parameters` as a manual/CI-time check (not a runtime
  gate) before relying on any model for structured output (§8, §13).
- Consider lowering researcher/reviewer `max_tokens` risk by explicitly setting
  `reasoning: {exclude: true}` (a documented, currently-unused parameter, §2) for the
  two reasoning-capable free models, or raising `max_tokens` modestly, to reduce the
  chance of reasoning-token exhaustion producing an empty completion (§5's LFM case;
  not confirmed as the cause, but a cheap, safe mitigation either way).

None of the above were implemented; all are recommendations only, per explicit
instruction not to optimize for making Phase H pass.

---

## 16. Recommended model/routing strategy for Phase H's eventual retry

Not a decision, an input for the human operator: keep the current pinned
single-model-per-role `_call_llm` behavior (best auditability/reproducibility, §10)
but (a) actually send `response_format: {type:"json_schema", ...}` with `strict:
true` only for models whose catalog entry lists `structured_outputs` support (today
only `liquid/lfm-2.5-2.6b:free` of the three attempted), and add fence-stripping as a
belt-and-suspenders fallback for any model without that support (§14.2); (b) prefer
models the catalog confirms support `response_format` when choosing `roles.yaml`
entries going forward, cross-checked manually before adoption (§8, §13); (c) do not
switch to `openrouter/free`, a `models` array, or client-side multi-model fallback
without first resolving the observability gaps in §11, since none of those
alternatives would currently produce a diagnosable failure any better than today's.

---

## 17. Proposed next controlled live test (described only — NOT executed)

**Model**: `liquid/lfm-2.5-2.6b:free` (the only one of the three already-attempted
models confirmed to support `response_format`/`structured_outputs` per the catalog).

**Exact payload** (single HTTP POST, `max_retries=0`):
```json
{
  "model": "liquid/lfm-2.5-2.6b:free",
  "messages": [{"role": "user", "content": "<full researcher_proposal.md prompt, rendered with the current context packet>"}],
  "max_tokens": 1024,
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "proposal_response",
      "strict": true,
      "schema": { "<JSON Schema mirroring ProposalResponse's required fields>" }
    }
  }
}
```

**Success criteria**: HTTP 200; `choices[0].message.content` non-empty; content is
directly `json.loads()`-able with no pre-processing; parses through
`parse_and_validate_proposal` with no `ValidationError`.

**Failure criteria and what each would mean**: HTTP 4xx on the `response_format`
field itself → catalog's `structured_outputs` flag was wrong/stale for this exact
serving endpoint (docs note support is per-endpoint, not just per-model, §2); HTTP
200 with empty content → same LFM failure mode as DRYRUN-0002, now ruled out as a
JSON-formatting issue since strict mode was requested — points at token-budget or a
genuine model-side flakiness that native structured output can't fix; HTTP 200 with
non-empty but still-invalid content → strict mode is not actually enforced by this
particular serving provider despite catalog listing, a genuine OpenRouter/provider
inconsistency worth reporting upstream.

Before running: capture `resp.status_code`, `resp.headers` (redacted of nothing
sensitive — these are OpenRouter's own headers, not ours), full `data` JSON body, and
`response.text`'s raw content to a local, non-committed diagnostic file, specifically
to close the §5/§6/§11 observability gap for this one call, then discard/redact
before any report referencing it is committed.

**REQUIRES FUTURE CONTROLLED LIVE TEST** — not performed as part of this audit.

---

## 18. Test count / results

`uv run pytest tests/ -q` → **426 passed**, unchanged from baseline. No trivial fix
was made (see §20), so the count and every test's identity is unchanged.

## 19. Secret-safety scan result

No `sk-or-v1-` pattern or any suspiciously long token string found in the audit diff
(this report file is the only new/changed file — no code was touched). Scan command:
`grep -rn "sk-or-v1-"` across the diff surface returned nothing.

## 20. Confirmation of unchanged surfaces

- `git diff --stat -- ios/ benchmark/config.py` → empty.
- `benchmark/results/baseline/` → `git status --porcelain` empty, untouched.
- No new `experiment/*` branches — `git branch -a` shows only the pre-existing
  `experiment/EXP-0001` .. `experiment/EXP-0005`.
- `research/omnilab.db` → queried directly, contains exactly `EXP-0001` through
  `EXP-0005`, no `EXP-0006`.
- `research/llm_usage.json` → `{"2026-09-05": 3}`, byte-identical to its value at
  task start. **No live call occurred during this audit.**

## 21. Phase H status

Phase H remains blocked. This audit made zero chat-completion requests, did not run
`smoke_test.py`, did not invoke `omnilab dry-run --authorize`, and did not modify
`roles.yaml`, `openrouter.py`, `structured_output.py`, `router.py`, or `pipeline.py`.
Nothing here unblocks or advances Phase H.

## 22. Concerns to fix before another API request is made

In priority order: (1) the observability gap (§11) — the next live attempt should not
happen without at least the diagnostic capture described in §17, or another failure
will again be undiagnosable; (2) confirm whether native `response_format` should be
adopted for `liquid/lfm-2.5-2.6b:free` before spending another live attempt on
prompt-and-hope JSON (§4, §17); (3) resolve or explicitly accept the unresolved
`llm_usage.json` persistence gap (§12) — a repeat disappearance right before another
authorized batch of calls would remove the only first-party enforcement of the daily
cap.
