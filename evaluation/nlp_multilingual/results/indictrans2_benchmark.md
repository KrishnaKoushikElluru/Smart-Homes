<!-- IndicTrans2 translation-then-parse benchmark — status report -->
# IndicTrans2 Benchmark — Status Report

**Result: EXECUTED.** The user supplied Hugging Face authentication in the isolated WSL environment; the full translate → parse → compare benchmark ran successfully against all 84 queries (65 translated + 19 English control). **Headline result: IndicTrans2 is a genuinely viable translation front-end for native-script Tamil/Hindi/Telugu queries (73.3% end-to-end exact-match, 100% proper-noun preservation, 94.4% numeric preservation, zero changes to the existing English parser) but is currently a poor fit for romanized code-mixed queries (34.3% exact-match) as tested.** Full numbers, real translation examples, and root-caused failures are in **§22** below. No number anywhere in this document is fabricated or estimated — every figure traces to `evaluation/nlp_multilingual/results/indictrans2_run_20260911T134144Z.json`, written by actually running `evaluation/nlp_multilingual/run_indictrans2_benchmark.py`.

> **Historical record, preserved unchanged below (§1-§21):** This investigation went through three real stages before execution was possible: (1) blocked entirely on Windows (no `IndicTransToolkit` wheel, no HF token), (2) the Windows/Cython blocker resolved by moving to WSL/Linux, still blocked on HF auth, (3) — see §22 — HF auth configured, three more real, previously-unknown compatibility bugs found and fixed (a `huggingface_hub` version conflict, a broken "xet" download transfer, and a legacy-KV-cache incompatibility in AI4Bharat's own model code), and the benchmark finally ran. Nothing in §1-§21 was edited after the fact; it is kept exactly as originally written for an accurate record of what was and wasn't known at each point.

## 1. Model/checkpoint selected

`ai4bharat/indictrans2-indic-en-dist-200M` — confirmed via the HuggingFace models API to be the smallest official AI4Bharat checkpoint for the Indic→English direction (the "dist" distilled 200M variant, vs. the full 1B model). `indictrans2-en-indic-dist-200M` is the wrong direction; `indictrans2-indic-indic-dist-320M` is Indic-to-Indic. MIT-licensed. Supports Tamil, Telugu, and Hindi (all three required languages), plus 22 other Indic languages.

## 2. Model size

Confirmed precisely via `HfApi.model_info(..., files_metadata=True)` (not estimated):
- `model.safetensors`: 913.4 MB
- `pytorch_model.bin`: 913.5 MB *(same weights, second format — only one would actually be downloaded)*
- Tokenizer/dictionary files: ~8.5 MB
- **Actual download required: ~922 MB**

## 3. Hardware/runtime environment

- Windows, no GPU (`torch.cuda.is_available()` → `False`)
- CPU-only PyTorch build installed: `torch 2.14.0+cpu`
- 43 GB free disk space (ample)
- Network access to PyPI, HuggingFace, and GitHub all confirmed reachable
- Isolated benchmark venv: `evaluation/nlp_multilingual/.venv` — Python 3.11.0, **completely separate from the project's own `.venv`**, gitignored (matches the existing `.venv/` pattern), never touches `requirements.txt`

## 4. Number of queries

**84**, built in `evaluation/nlp_multilingual/data/multilingual_dev_queries.json` (new, separate from the existing 244-query English set — that set was never opened for writing).

| Language | Count |
|---|---|
| en (control) | 19 |
| ta (Tamil) | 12 |
| ta-en (Tanglish) | 11 |
| hi (Hindi) | 8 |
| hi-en (Hinglish) | 13 |
| te (Telugu) | 10 |
| te-en (Telugu-English) | 11 |

| Category | Count |
|---|---|
| location_poi | 22 |
| nearby_facility | 12 |
| numeric_unit | 10 |
| multi_constraint | 9 |
| price_variant | 8 |
| simple_bhk | 7 |
| simple_multi | 7 |
| simple_furnishing | 5 |
| area_variant | 4 |

Includes all of the user-supplied worked examples verbatim (`"Chennai la 2 BHK flat venum 30k kulla"`, `"சென்னையில் 2 BHK பிளாட் வேண்டும்"`, `"Chennai mein 30k ke andar 2 BHK flat chahiye"`, `"చెన్నైలో 2 BHK ఫ్లాట్ కావాలి"`, `"Chennai lo 30k lopala 2 BHK flat kavali"`), dedicated numeric-preservation tests (20k/30k/50k/30 thousand/30 hazaar/30 ஆயிரம்/30 వేలు/lakh/crore/sqft/square feet), and dedicated POI-preservation tests (VIT Chennai, SRM, Mambakkam, Tata Homes, railway station, hospital, mall) in multiple scripts.

## 5–15. Translation / StructuredQuery / breakdown / preservation metrics

**Not run.** See §16-19 for exactly why, below.

## 16. Average translation latency / 17. Total benchmark runtime

**Not measured** — no translation call was ever made.

## 18. Dependency footprint

| Package | Status | Notes |
|---|---|---|
| `torch` 2.14.0+cpu | ✅ Installed | CPU-only wheel, ~800 MB of the venv |
| `transformers` 5.17.0 | ✅ Installed | |
| `sentencepiece` 0.2.2 | ✅ Installed | |
| `sacremoses` | ✅ Installed | IndicTransToolkit dependency; pure Python, no issue |
| `indic-nlp-library-itt` | ✅ Installed | IndicTransToolkit dependency; pure Python, no issue |
| **`IndicTransToolkit` 1.1.1** | ❌ **Failed to install** | Contains a Cython extension with no Windows wheel — see §19 |
| Model weights (~922 MB) | ❌ **Not downloaded** | Gated repository — see §19 |

**Isolated venv size so far: 975.8 MB** (everything above except the model weights and IndicTransToolkit itself). Nothing was added to the project's own `requirements.txt` or production `.venv`.

## 19. Whether CPU-only execution is practical

**Not yet determined — genuinely blocked, not "impractical due to slowness."** Two independent, hard blockers were found, confirmed with direct evidence, before a single translation could be attempted:

### Blocker 1 — `IndicTransToolkit` cannot be built on Windows

AI4Bharat's own recommended pre/post-processing package (`IndicTransToolkit`, 538-line `processor.pyx`) handles sentence normalization, Indic-digit-to-ASCII conversion, Moses+Indic tokenization, and placeholder-based protection of numbers/URLs/emails during translation — exactly the mechanics this benchmark most needs to measure (§E/§D of the original task: numeric and POI preservation).

- **PyPI publishes wheels for macOS (arm64), manylinux, musllinux, and PyPy — zero Windows wheels**, for any Python version (confirmed by listing every published file via the PyPI JSON API).
- Building from source requires **Microsoft Visual C++ 14.0+ Build Tools**, which are not installed on this machine.
- Installing them would be a multi-GB, machine-wide system change — explicitly out of scope for an "isolated benchmark environment," and not something this session should do unilaterally.
- Every *other* dependency in the chain (`sacremoses`, `indic-nlp-library-itt`, `transformers`, `sentencepiece`, `torch`) installed cleanly — **this is a single, narrow, precisely-identified blocker**, not a general Windows-incompatibility across the whole stack.

### Blocker 2 — the model itself is gated

All three AI4Bharat IndicTrans2 repositories checked (`indictrans2-indic-en-dist-200M`, `-1B`, `-en-indic-dist-200M`) report `"gated": "auto"` via the HuggingFace API. A direct anonymous request for `config.json` returns **HTTP 401 Unauthorized**. Downloading requires a HuggingFace account that has accepted the model's license, plus an access token — **independent of Blocker 1**: even with a working compiler, the weights still could not be fetched anonymously.

### What was deliberately NOT done to route around these

Per this task's own explicit instruction ("stop and report... instead of silently switching to a hosted API"):
- Did **not** install MSVC Build Tools system-wide.
- Did **not** attempt to create a HuggingFace account or otherwise obtain credentials.
- Did **not** reimplement `IndicTransToolkit`'s 538-line preprocessing class from scratch — its logic (digit-script normalization tables, placeholder-based entity protection, Moses/Indic tokenization) is substantial and directly determines the POI/numeric-preservation results this benchmark cares about most; an unverified from-scratch port would measure *this session's own reimplementation*, not AI4Bharat's real, published behavior, undermining the benchmark's whole purpose.
- Did **not** switch to a paid or hosted translation API.

## 20. Recommendation

**Do not proceed with this exact configuration silently.** Two concrete unblock paths exist, both requiring a decision or action from the user — neither is something this session can complete alone:

1. **Get past Blocker 2 first (cheapest to check)**: the user (or someone with a free HuggingFace account) visits the model page, accepts AI4Bharat's license, and generates a read-access token. If that token is supplied to this environment (e.g., via an environment variable, never typed into chat), Blocker 1 still remains — the token alone does not solve the Windows/Cython compile problem.
2. **Get past Blocker 1**: either install Microsoft Visual C++ Build Tools on this machine (a real, visible, multi-GB system change — flagging it explicitly rather than doing it unasked), or run this exact same benchmark on a Linux or macOS machine / container, where `IndicTransToolkit` has a pre-built wheel and neither blocker applies to the toolkit itself (Blocker 2 — the gate — would still need a token regardless of OS).

Both blockers must be resolved for this benchmark to run at all; resolving only one is not sufficient. Once both are cleared, the dataset (`multilingual_dev_queries.json`, 84 queries, ready now) and the isolated venv are already in place — the actual translate→parse→compare run itself is a small, fast follow-up, not a redesign.

**No claim is made here about whether IndicTrans2 would or would not be "good enough" for SmartHomes multilingual search** — that question remains genuinely open, exactly as it was before this phase, because it was never actually tested.

---

## 21. WSL/Linux follow-up investigation

### 21.1 WSL and Linux environment status

WSL2 was already installed and enabled on this machine — no installation was performed. Default distro: **Ubuntu 24.04.4 LTS**, 8 CPUs, 7.6 GB RAM, **954 GB free** on the native Linux filesystem (vs. 43 GB on the Windows side), full network access to PyPI and HuggingFace confirmed.

### 21.2 Building an isolated Linux venv without sudo

WSL Ubuntu's system Python ships with no `ensurepip`/`venv` support out of the box (`python3 -m venv` fails with an explicit prompt to `apt install python3.12-venv`, requiring `sudo`). The user was asked and **approved** a `sudo apt install python3.12-venv python3-pip` (via AskUserQuestion → "Yes, install it"). That command then hung indefinitely because `sudo` in this non-interactive environment cannot satisfy an interactive password prompt (confirmed via `sudo -n true` → "a password is required"). The hung process was killed cleanly (`sudo -k`), and rather than retry a blocking sudo prompt, this session used PyPA's official **`bootstrap.pypa.io/virtualenv.pyz`** — a self-contained zipapp that bootstraps a fully working venv + pip with **zero sudo, zero apt, zero system package changes**. This achieves the identical isolated-environment outcome the user approved, with a strictly smaller footprint than the approved path (no system packages installed at all), so it was used instead.

Result: `~/smarthomes_benchmark/.venv`, Python 3.12.3, pip 26.2.1 — entirely on the WSL native filesystem (not under `/mnt/c/...`), outside the Windows-visible repo tree, so it isn't a git-tracking concern for this specific directory.

### 21.3 Blocker 1 (Windows Cython compile) — RESOLVED on Linux

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install transformers sentencepiece sacremoses indic-nlp-library-itt IndicTransToolkit
```

All packages, **including `IndicTransToolkit`**, installed cleanly from pre-built wheels — no Cython compilation, no MSVC Build Tools needed at all. This directly confirms the original diagnosis (PyPI simply never published a Windows wheel for this package) and shows the actual fix is "run this on Linux," not "install a multi-GB Windows compiler toolchain."

**A newly-discovered issue, found only once the toolkit actually installed:** importing it failed —

```
ImportError: cannot import name 'PreTrainedTokenizerBase' from 'transformers.tokenization_utils'
```

`pip` had resolved `transformers` to `5.17.0` (a very new major release), whose internal module layout no longer matches what `IndicTransToolkit` 1.1.1's `collator.py` expects — unsurprising, since `IndicTransToolkit`'s own `pyproject.toml` has **no version pin** on `transformers` at all. Fixed by pinning `transformers<5`, which resolved to **4.57.6**; re-verified `from IndicTransToolkit.processor import IndicProcessor` imports successfully. This is genuinely new information the original Windows-phase report couldn't have surfaced, since it never got a working toolkit installation far enough to hit this.

Final WSL venv: **1.4 GB**, packages — `torch 2.14.0+cpu`, `transformers 4.57.6`, `sentencepiece 0.2.2`, `sacremoses 0.2.0`, `indic-nlp-library-itt 0.1.1`, `indictranstoolkit 1.1.1`, `numpy 2.5.3`, `regex 2026.9.10`, `tokenizers 0.22.2`.

### 21.4 Blocker 2 (HuggingFace model gating) — still blocked, confirmed platform-independent

Checked via a **local-only** call, `huggingface_hub.whoami()` — this reads the local cached-login state and does **not** itself contact the gated model repository, so it doesn't count as a repeated request against the gate. Result: `LocalTokenNotFoundError`. No token exists anywhere in the WSL environment (checked the relevant environment variables and both current and legacy cached-login file locations). Per the task's explicit instruction, no further request was made to the gated repo, and no model download was attempted.

This confirms Blocker 2 is genuinely **independent of the platform issue**: it is an authentication/licensing gate on AI4Bharat's HuggingFace repository, not a technical/compiler problem, so it blocks identically whether the toolkit runs on Windows or Linux.

### 21.5 What you (the user) need to do to unblock this — without pasting anything into chat

1. Create or log into a Hugging Face account: https://huggingface.co
2. Visit the model page and accept its license/access terms: https://huggingface.co/ai4bharat/indictrans2-indic-en-dist-200M
3. Generate a **read-access** token: https://huggingface.co/settings/tokens
4. Supply that token **directly inside your own WSL terminal** — never into this chat — using either:
   - `huggingface-cli login` (interactive prompt, run inside `~/smarthomes_benchmark/.venv`'s activated environment), or
   - `export HF_TOKEN=<your token>` in that same WSL shell before the benchmark script runs

This session will never see, request, or handle the token value. Once it's set up on your end, say so and the actual translate → parse → compare run against the ready 84-query dataset can proceed — it's a small, fast follow-up at that point, not a redesign, since the dataset and environment are both already in place.

### 21.6 Updated recommendation

**Still do not proceed silently — but only one blocker remains, and it is now a five-minute action for the user, not a system-engineering problem.** The platform/compiler blocker that looked like it might require installing Microsoft Visual C++ Build Tools is fully resolved by using WSL/Linux instead — no Windows system changes needed. The one remaining blocker (HuggingFace's model gate) was never a platform issue in the first place, and can only be resolved by the user themselves creating an account, accepting the license, and generating a token. No claim about IndicTrans2's real-world translation quality can be made yet — that remains genuinely untested on both platforms.

---

## 22. Execution results (the actual benchmark)

The user configured Hugging Face authentication directly in their own WSL terminal (`hf auth whoami` → confirmed logged in). Three more real, previously-unknown blockers surfaced on the way to a working run — all found, root-caused, and fixed, none papered over:

### 22.1 Three new bugs found and fixed before any translation could succeed

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| a | `IndicTransToolkit` import failed again with a fresh venv resolution | `pip` resolved `huggingface_hub` to `1.31.0`; `transformers` 4.57.6 requires `huggingface_hub>=0.34.0,<1.0` | Pinned `huggingface_hub<1.0`, resolved to `0.36.2`. HF auth state survived the downgrade (re-verified). |
| b | First model download: 35 minutes, then `OSError: I/O error: error decoding response body` | HuggingFace's newer "xet" transfer backend (`xet_get`) failing over this network path | `export HF_HUB_DISABLE_XET=1` — falls back to plain HTTP. Retry: tokenizer in 18s, full model in ~16 min, 211,780,608 params confirmed (matches the 200M-distilled checkpoint). |
| c | **Every single translation call crashed** (`translation_success_rate: 0.0`) with `AttributeError: 'NoneType' object has no attribute 'shape'` | AI4Bharat's own custom remote model code (`modeling_indictrans.py`, loaded via `trust_remote_code=True`, internally pinned to `transformers==4.32.1`) does `past_key_values[0][0].shape[2]`, assuming the old legacy tuple KV-cache format. `transformers==4.57.6`'s `generate()` now pre-populates an empty `DynamicCache` object instead of `None`, even on the first decoding step, breaking that indexing. | Pass `use_cache=False` to `model.generate()` — avoids the incompatible cache object entirely (verified: 100% failure with `use_cache=True`, 100% success with `use_cache=False`, same transformers version). **Cost: slower, uncached decoding** — a real, disclosed latency penalty from the version mismatch, not hidden. |

None of these required reimplementing AI4Bharat's code or IndicTransToolkit — all three are dependency-version pins or a documented `generate()` flag, the same category of fix as the earlier `transformers<5` pin.

### 22.2 Headline numbers (84 queries: 19 English control, 65 translated)

| Metric | Value |
|---|---|
| Translation success rate | **100%** (65/65, zero exceptions) |
| Overall exact-match accuracy | **54.8%** |
| Overall intent accuracy | **98.8%** |
| Overall slot F1 | **81.7%** |
| English control exact-match (untranslated) | 63.2% (see §22.5 — a pre-existing parser gap, not new) |
| **Native-script Indic exact-match** (ta/hi/te) | **73.3%** |
| **Code-mixed exact-match** (ta-en/hi-en/te-en) | **34.3%** |
| POI (proper-noun) preservation | **100%** |
| Numeric preservation | **94.4%** |
| Avg. translation latency | 722.6 ms/query (min 432.7, max 1256.3) |
| Total translation wall time | 47.0s for 65 queries |
| Peak RSS | 461.6 MB → 1287.4 MB |

### 22.3 Language breakdown

| Language | n | Exact-match | Intent acc. |
|---|---|---|---|
| en (control) | 19 | 63.2% | 100% |
| ta (Tamil, native script) | 12 | 58.3% | 91.7% |
| ta-en (Tanglish) | 11 | 36.4% | 100% |
| hi (Hindi, native script) | 8 | 87.5% | 100% |
| hi-en (Hinglish) | 13 | 30.8% | 100% |
| te (Telugu, native script) | 10 | 80.0% | 100% |
| te-en (Telugu-English) | 11 | 36.4% | 100% |

### 22.4 Category breakdown

| Category | n | Exact-match |
|---|---|---|
| area_variant | 4 | 100% |
| simple_bhk | 7 | 100% |
| simple_multi | 7 | 85.7% |
| simple_furnishing | 5 | 80.0% |
| multi_constraint | 9 | 66.7% |
| price_variant | 8 | 62.5% |
| nearby_facility | 12 | 50.0% |
| location_poi | 22 | 36.4% |
| numeric_unit | 10 | **0.0%** (see §22.5) |

### 22.5 Why English control (63.2%) and numeric_unit (0%) are low — and why it's not a translation problem

7 of the 10 `numeric_unit` failures are **English control queries that were never translated at all**: `"20k flat"`, `"30k flat"`, `"50k flat"`, `"30 thousand rupees flat"`, `"50 lakh flat"`, `"1.5 crore villa"`, `"1200 square feet flat"`. The existing, **unmodified** `services/nlp/numeric_parser.py` doesn't treat a bare `<number><unit> <property>` phrase as a price constraint without an explicit comparison word ("under", "below", "within"). The 3 translated failures in this category (Hindi-English `"30 hazaar wala flat"`, Tamil `"30 ஆயிரம் ரூபாய் பிளாட்"`, Telugu `"30 వేలు రూపాయలు ఫ్లాట్"`) show the *identical* missed-slot pattern for the identical reason — translation correctly rendered the number every time, the pre-existing parser gap is what drops it.

This also explains the English-control gap versus the production 244-query baseline (96.2%): this new 84-query set's `numeric_unit` category deliberately probes bare-number pricing, which the original 244-query set apparently under-samples. `services/nlp/` has zero diff — this is a genuinely pre-existing gap the multilingual dataset happened to surface, not a regression.

### 22.6 Proper-noun (POI) preservation — 100%, the most positive finding

Every proper noun tested — **VIT Chennai, Tata Homes, Mambakkam, SRM University, SBIOA** — survived translation verbatim, in every language and script, native and code-mixed alike. This was the specific failure mode (silent proper-noun mistranslation) this benchmark was built to catch, and it did not happen once.

### 22.7 Why code-mixed (34.3%) is much worse than native-script (73.3%)

IndicTrans2's Indic→English checkpoint was trained on **native-script** Tamil/Devanagari/Telugu text — not romanized Latin-script code-mixed text. Fed romanized Tanglish/Hinglish/Telugu-English, it behaves close to an **identity pass-through**: English words and proper nouns are left alone (correctly), but the untranslated Indic postposition words (Tamil "pakkathula"/"pakkam", Hindi "ke paas", Telugu "daggara" — all meaning "near") are usually **not** converted to English "near", and the model occasionally reorders the sentence into something garbled:

| Language | Original | Translated | What happened |
|---|---|---|---|
| ta-en | `VIT Chennai pakkathula flat venum` | `VIT Chennai Pakkathula Flat Venum` | "pakkathula" (near) left untranslated |
| hi-en | `VIT Chennai ke paas flat chahiye` | `Paas flat chaiye of VIT Chennai` | garbled reordering; "ke paas" (near) not rendered as "near" |
| te-en | `Tata Homes daggara flat kavali` | `Tata Homes Daggara Flat Kavali` | "daggara" (near) left untranslated |

**Downstream effect:** the existing, unmodified `services/nlp/location_extractor.py` expects an English preposition ("near X") to identify a POI mention. When translation leaves the source postposition untranslated, that pattern never fires, so the extractor falls back to grabbing the trailing city name instead — e.g. `"VIT Chennai Pakkathula Flat Venum"` gets `"Chennai"` extracted as a city rather than `"VIT Chennai"` as a POI. This is a real, specific interaction between IndicTrans2's weak code-mixed handling and the parser's preposition-dependent POI heuristic, not a defect in either piece alone.

**Conclusion: IndicTrans2 is a good fit for native-script Indic input, a poor fit for romanized code-mixed input, as tested.**

### 22.8 Real mistranslation and phrasing-interaction examples

| Language | Original | Translated | Issue |
|---|---|---|---|
| ta | `பாதி பர்னிஷ் செய்யப்பட்ட 2 BHK` | **"Half-burnished 2 BHK"** | Genuine mistranslation: "semi-furnished" → "burnished" (not "furnished"). The furnishing lexicon has no "burnished" pattern, so furnishing correctly returned nothing for this wrong string — a translation-quality bug, not a parser bug. |
| hi | `किराए के लिए विला` | "Villas for rent" | Translation is fluent and correct, but pluralizes "Villa" → "Villas". `services/nlp/entity_extractor.py:53`'s property_type pattern is `\bvilla\b` (singular-only, word-boundary-anchored) and doesn't match "Villas". Correct translation + a pre-existing singular-only lexicon gap = a missed slot. |
| te | `Tata Homes అపార్ట్మెంట్ కావాలి` | "i want a tata homes apartment" | Translation is fluent and correct, but the POI directly modifies "apartment" with no "near" preposition — structurally different from the pattern the existing POI extractor expects. location stayed unextracted. |

### 22.9 Representative translation examples (good and bad)

| Language | Original | Translated | Quality |
|---|---|---|---|
| ta | `சென்னையில் 2 BHK பிளாட் வேண்டும்` | "Need a 2 BHK flat in Chennai" | Excellent — fluent, fully correct |
| hi | `चेन्नई में 2 BHK फ्लैट चाहिए` | "Need a 2 BHK flat in Chennai" | Excellent — fluent, fully correct |
| te | `చెన్నైలో 2 BHK ఫ్లాట్ కావాలి` | "i want a 2 bhk flat in chennai" | Excellent — fluent, fully correct |
| ta-en | `Chennai la 2 BHK flat venum` | "Chennai la 2 BHK Flat Venom" | Poor — near-identity pass-through, "venum" mistranslated as "Venom" |
| hi-en | `Chennai mein 30k ke andar 2 BHK flat chahiye` | "Chennai mein 30k ke andar 2 BHK flat chhaiye" | Poor — almost entirely untranslated, only a spelling artifact changed |
| te-en | `Chennai lo 30k lopala 2 BHK flat kavali` | "Chennai lo 30k lopala 2 BHK flat kavali" | None — completely unchanged, zero translation occurred |

### 22.10 Per-field F1

| Field | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| listing_type | 1.000 | 1.000 | 1.000 | 8 |
| bedrooms | 1.000 | 1.000 | 1.000 | 32 |
| area | 1.000 | 1.000 | 1.000 | 16 |
| furnishing | 1.000 | 0.857 | 0.923 | 7 |
| property_type | 0.778 | 0.933 | 0.848 | 60 |
| location | 0.903 | 0.700 | 0.789 | 80 |
| price | 1.000 | 0.302 | 0.464 | 43 |
| amenities | 0.000 | — | — | 0 |

### 22.11 Regression checks (post-benchmark)

- Existing 392-test suite: **392/392 passed**, zero regression.
- Existing 244-query English evaluation: unaffected (dev 1.000, held-out 0.962) — `services/nlp/` and `evaluation/nlp/` have zero diff.
- No production code, `services/nlp/`, location/Ola/Mappls code, or the dataset (`multilingual_dev_queries.json`) was touched.
- No commit, no push.

### 22.12 Final recommendation

**IndicTrans2 is a genuinely viable translation front-end for native-script Tamil/Hindi/Telugu queries** feeding the existing, completely unmodified English NLP parser: 73.3% end-to-end exact-match, 100% proper-noun preservation, 94.4% numeric preservation. **It is not currently viable for romanized code-mixed queries** as tested (34.3% exact-match) — the model largely fails to translate the non-English words in code-mixed input, which breaks the parser's preposition-dependent POI extraction.

Of the concrete failure modes found: two are genuine translation-quality/phrasing issues (a real mistranslation, and fluent-but-differently-structured phrasing); two more (bare-number pricing, plural "Villas") are pre-existing English-parser lexicon gaps that translated text happened to probe more than the original 244-query English set did — disclosed here, not hidden or attributed to translation.

**This remains an experiment only.** No production integration has been made or is recommended by this report. If native-script multilingual support is wanted, the next step is a separate, explicitly-scoped integration decision — not a continuation of this benchmark.
