"""
EXPERIMENT-ONLY. Deterministic Romanized/code-mixed normalization layer.

ITERATION 2 (evidence-based revision - see
evaluation/nlp_multilingual/results/romanized_experiment.json's
"iteration_1_regressions_found" for the raw evidence): a first version
of this module did plain word-for-word substitution (pakkathula->near,
la/mein/lo->in) and was tested via evaluation/nlp_multilingual/
run_romanized_experiment.py BEFORE this revision. That test found two
real, reproducible regressions, root-caused with services/nlp/
(read-only, never modified) directly:

  1. Tamil/Hindi/Telugu proximity and price-limit words are POSTPOSITIONS
     ("<place> pakkathula" = "near <place>", word AFTER the noun);
     English "near"/"under" are PREPOSITIONS (word BEFORE the noun). A
     plain word swap produces English in the wrong order ("VIT Chennai
     near flat want" instead of "near VIT Chennai flat want"), and the
     existing, unmodified services/nlp/location_extractor.py /
     numeric_parser.py only recognize the preposition order - confirmed
     directly: `extract_price("under 30000")` -> lte 30000,
     `extract_price("30000 under")` -> None.
  2. Placing "near" directly before a bare number (an artifact of the
     wrong word order above, e.g. "...near 3 BHK...") collided with
     numeric_parser.py's OWN existing "near <number>" approx-price
     pattern (confirmed directly: `extract_price("near 3 bhk")` ->
     operator='approx', value=3.0) - a second, independent failure mode
     from the same root cause.

Iteration 2 fixes both by REORDERING the anchor phrase ahead of the
postposition instead of substituting it in place ("<place> pakkathula
..." -> "near <place> ..."), which is still a deterministic regex
rewrite (Phase 3 approach A/B), not machine translation - and removes
the "la"/"mein"/"lo" ("in") rule entirely, since it fixed no observed
IndicTrans2 failure and iteration-1 testing showed it can make the
location extractor swallow an adjacent bare number (masking it out
before bedroom extraction ever sees it). Both iterations' actual test
results are reported side by side in
evaluation/nlp_multilingual/results/romanized_experiment.json and
docs/PHASE_5_6_ROMANIZED_CODEMIXED_EVALUATION.md - nothing is hidden.

Not used by production. Not imported by services/nlp/. Exists only to
answer one question for evaluation/nlp_multilingual/run_romanized_experiment.py:
does rewriting a small set of Romanized Tamil/Hindi/Telugu FUNCTION WORDS
(postpositions, "want"-verbs, unit words) into their English equivalents,
before either IndicTrans2 or the existing English parser sees the query,
recover any of the accuracy IndicTrans2 loses on romanized/code-mixed
input (see evaluation/nlp_multilingual/results/indictrans2_benchmark.md
section 22.7)?

WHERE THE LEXICON CAME FROM
----------------------------
Every entry below was read directly off the 35 code-mixed (ta-en/hi-en/
te-en) queries in evaluation/nlp_multilingual/data/multilingual_dev_queries.json
and their actual IndicTrans2 translations in
evaluation/nlp_multilingual/results/indictrans2_run_20260911T134144Z.json -
not invented or copied from a generic dictionary. Each group below cites
the specific queries that motivated it.

  NEAR_WORDS   ("near", REORDERED - see ITERATION 2 note above):
    ta: pakkathula, pakkam   - "VIT Chennai pakkathula flat venum" (id 22),
                                "Tata Homes pakkam flat venum" (id 28)
    hi: ke paas               - "VIT Chennai ke paas flat chahiye" (id 40)
    te: daggara                - "VIT Chennai daggara flat kavali" (id 58)
    IndicTrans2 leaves these untranslated or garbles them (see benchmark
    md 22.7); the existing services/nlp/location_extractor.py and
    nearby_facility_extractor.py (both UNMODIFIED) only recognize the
    English PREPOSITION "near" immediately BEFORE the place/facility, so
    "<place> pakkathula" is rewritten to "near <place>" (the postposition
    is consumed and reappears in front, not substituted in place).

  UNDER_WORDS  ("under", REORDERED - see ITERATION 2 note above):
    ta: kulla                 - "...30k kulla" (id 21), "30 thousand kulla 2 BHK" (id 27)
    hi: ke andar               - "Chennai mein 30k ke andar 2 BHK flat chahiye" (id 38)
    te: lopala                  - "Chennai lo 30k lopala 2 BHK flat kavali" (id 56),
                                "30 vela lopala 2 BHK" (id 63)
    services/nlp/numeric_parser.py's LTE operator words are English only
    (under/below/less than/up to/within/no more than/max/budget of) AND
    preposition-ordered (confirmed directly: extract_price("under 30000")
    works, extract_price("30000 under") returns None) - UNMODIFIED, per
    this experiment's own constraints - so "<number> kulla" is rewritten
    to "under <number>", not "<number> under".

  HOUSE_WORDS  ("house"):
    ta: veedu                 - "Mambakkam pakkam 3 BHK veedu venum" (id 23)
    hi: ghar                   - "Mambakkam ke paas 3 BHK ghar chahiye" (id 41)
    te: illu                    - "Mambakkam daggara 3 BHK illu kavali" (id 59)
    services/nlp/entity_extractor.py's property_type lexicon has
    `\bhouses?\b` -> independent_house (UNMODIFIED) but no Romanized form.

  THOUSAND_WORDS ("thousand"):
    hi: hazaar, hazar          - "30 hazaar ke andar 2 BHK" (id 45),
                                "30 hazaar wala flat" (id 70)
    te: vela, veta               - "30 vela lopala 2 BHK" (id 63) - IndicTrans2
                                itself mis-renders "vela" as "Veta" in one
                                translation, so both spellings are matched.
    numeric_parser.py's number+unit regex does not recognize these
    Romanized unit words, so price extraction fails to fire AT ALL (not
    just with the wrong operator) when they're present.

  WANT_WORDS   ("want"):
    ta: venum, irukkanum       - venum appears throughout the Tamil-English
                                subset; irukkanum did not occur in the 84-
                                query set but is included per this task's
                                own Phase 1 list, narrowly, as a same-class
                                intent-verb synonym.
    hi: chahiye                 - throughout the Hindi-English subset.
    te: kavali, undali          - kavali throughout the Telugu-English
                                subset; undali is Telugu's less-common
                                synonym, included for the same reason as
                                irukkanum.
    NOT required to fix any observed failure (intent accuracy was already
    100% on every code-mixed language group in the baseline run - the
    existing parser's single supported intent, property_search, does not
    depend on any of these words) but included because Phase 3's own
    category C explicitly asks for it, and normalizing it is harmless: it
    never collides with a real English word or a proper noun in this
    dataset (word-boundary-anchored, checked below).

  IN_WORDS     ("la"/"mein"/"lo" - REMOVED in iteration 2, see note above):
    ta: la, hi: mein, te: lo   - "Chennai la 2 BHK flat venum" (id 20),
                                "Chennai mein 2 BHK flat chahiye" (id 39),
                                "Chennai lo 2 BHK flat kavali" (id 57)
    services/nlp/location_extractor.py matches "Chennai" as an
    area_or_city directly with no "in" needed at all, so this rule fixed
    nothing - and iteration-1 testing showed inserting "in" immediately
    before a bare BHK number ("Chennai in 2 BHK...") made the location
    extractor's "in <X>" pattern swallow the "2" as part of a location
    mention, masking it out before the BHK count was ever extracted
    (bedrooms recall regressed 1.0 -> 0.733 on the tuning set under
    iteration 1). Left untouched (safe no-op) in iteration 2.

WHAT IS DELIBERATELY NOT HERE
------------------------------
- No LLM, no paid API, no network call of any kind.
- No POI/place-name translation or resolution - proper nouns are
  protected (see _protect_proper_nouns below), never rewritten.
- No coordinates, no calls to any location provider.
- No blind/generic dictionary: every rule above is traceable to an
  observed query in the actual benchmark dataset, not assumed.
- "wala" ("30 hazaar wala flat", id 70) is deliberately NOT mapped to
  "under" - unlike kulla/ke andar/lopala, "wala" is a generic Hindi
  possessive/attributive suffix ("X-wala" = "the one with X"), not
  specifically a price-comparison word, and gold for id 70 itself expects
  price_operator="eq" (an ambiguous bare number), not "lte". Silently
  mapping it to "under" would be exactly the kind of unjustified
  assumption this experiment is supposed to avoid.
"""
from __future__ import annotations

import re

# ── proper-noun protection ──────────────────────────────────────────────
# A maximal run of Title-Case or ALL-CAPS tokens in the ORIGINAL
# (pre-normalization) query is treated as a protected span and swapped
# for a placeholder before any lexicon substitution runs, then restored
# verbatim afterward. This is a generic heuristic (not a hardcoded list
# of this dataset's specific POI names) - it protects "VIT Chennai",
# "Tata Homes", "Mambakkam", "SRM University", "BHK", or any future
# capitalized proper noun / acronym the same way, without needing to
# know its name in advance. It deliberately does NOT protect lowercase
# words, so it never shields a Romanized function word from being
# rewritten (all of this module's target words - pakkathula, kulla,
# ghar, hazaar, venum, la, etc. - are lowercase in the dataset).
_PROTECTED_RUN = re.compile(r"\b[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*\b")


def _protect_proper_nouns(text: str) -> tuple[str, dict[str, str]]:
    placeholders: dict[str, str] = {}

    def _sub(m: re.Match) -> str:
        key = f"__PROPER_NOUN_{len(placeholders)}__"
        placeholders[key] = m.group(0)
        return key

    protected = _PROTECTED_RUN.sub(_sub, text)
    return protected, placeholders


def _restore_proper_nouns(text: str, placeholders: dict[str, str]) -> str:
    for key, original in placeholders.items():
        text = text.replace(key, original)
    return text


# ── lexicon (grounded in the 84-query dataset - see module docstring) ──
#
# PRICE reorder rules: "<number>[ <unit-word>] kulla/lopala/ke andar" ->
# "under <number>[ <unit-word>]". The anchor is explicitly a NUMBER
# (optionally with one adjoining unit word: k/thousand/hazaar/hazar/
# vela/veta/lakh/crore) - not a bare \S+ token - because a first
# implementation anchored on \S+ and, on "30 thousand kulla" (number and
# unit as TWO separate tokens), matched only the unit word "thousand"
# immediately before "kulla", producing the broken "30 under thousand"
# instead of "under 30 thousand". Confirmed fixed by widening the anchor
# to the full number(+unit) span.
_PRICE_UNIT = r"(?:k|thousand|hazaar|hazar|vela|veta|lakh|crore)"
_PRICE_NUM = rf"\d[\d,]*\.?\d*(?:\s*{_PRICE_UNIT})?"
_REORDER_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"({_PRICE_NUM})\s+kulla\b", re.IGNORECASE), r"under \1"),
    (re.compile(rf"({_PRICE_NUM})\s+lopala\b", re.IGNORECASE), r"under \1"),
    (re.compile(rf"({_PRICE_NUM})\s+ke\s+andar\b", re.IGNORECASE), r"under \1"),
]

# NEAR clauses are handled differently: not an in-place swap, but a
# MOVE to the end of the sentence (see _move_near_clauses_to_end below).
# A first implementation did an in-place "<anchor> pakkathula" -> "near
# <anchor>" swap and found a second real regression: services/nlp/
# location_extractor.py's POI pattern was apparently only ever exercised
# with "near <place>" as the LAST thing in the sentence (e.g. the
# production example "flat for rent near VIT Chennai") - given "near
# <place>" placed mid-sentence with more words trailing it ("near VIT
# Chennai flat want"), it captured EVERYTHING after "near" through the
# end of the string as the location name ("vit chennai flat want"), not
# just the place. Moving the whole "near <anchor>" clause to the end of
# the sentence (matching the shape the extractor was actually built
# against) fixed this - confirmed by re-testing.
_NEAR_TRIGGERS: list[re.Pattern] = [
    re.compile(r"(\S+)\s+pakkathula\b", re.IGNORECASE),
    re.compile(r"(\S+)\s+pakkam\b", re.IGNORECASE),
    re.compile(r"(\S+)\s+daggara\b", re.IGNORECASE),
    re.compile(r"(\S+)\s+ke\s+paas\b", re.IGNORECASE),
]


def _move_near_clauses_to_end(text: str) -> str:
    anchors: list[str] = []

    def _capture(m: re.Match) -> str:
        anchors.append(m.group(1))
        return " "

    for pattern in _NEAR_TRIGGERS:
        text = pattern.sub(_capture, text)
    if anchors:
        text = f"{text.strip()} near {' near '.join(anchors)}"
    return text

# Plain word-for-word rules (position-independent - safe as substitution,
# not reordering, because the field they feed does not depend on the
# word's position relative to other tokens; see module docstring).
_WORD_RULES: list[tuple[re.Pattern, str]] = [
    # house
    (re.compile(r"\bveedu\b", re.IGNORECASE), "house"),
    (re.compile(r"\bghar\b", re.IGNORECASE), "house"),
    (re.compile(r"\billu\b", re.IGNORECASE), "house"),
    # thousand (unit word, not an operator - order-independent since it
    # just needs to sit next to its number, which it already does)
    (re.compile(r"\bhazaar\b", re.IGNORECASE), "thousand"),
    (re.compile(r"\bhazar\b", re.IGNORECASE), "thousand"),
    (re.compile(r"\bvela\b", re.IGNORECASE), "thousand"),
    (re.compile(r"\bveta\b", re.IGNORECASE), "thousand"),
    # want / need (intent verb - not required by any observed failure,
    # included for Phase-3 completeness; see module docstring)
    (re.compile(r"\bvenum\b", re.IGNORECASE), "want"),
    (re.compile(r"\birukkanum\b", re.IGNORECASE), "want"),
    (re.compile(r"\bchahiye\b", re.IGNORECASE), "want"),
    (re.compile(r"\bkavali\b", re.IGNORECASE), "want"),
    (re.compile(r"\bundali\b", re.IGNORECASE), "want"),
    # "la"/"mein"/"lo" ("in") deliberately REMOVED in iteration 2 - see
    # module docstring's ITERATION 2 note and the IN_WORDS entry above.
]

_HAS_LATIN_LETTER = re.compile(r"[A-Za-z]")


def normalize(query: str) -> str:
    """Rewrite Romanized/code-mixed Tamil/Hindi/Telugu function words in
    `query` into their English equivalents, protecting proper nouns.
    Deterministic, offline, stdlib-only.

    Safe on native-script (Tamil/Devanagari/Telugu Unicode) input: none
    of the regexes above can match non-Latin script, so a native-script
    query is returned completely unchanged - this is a structural
    guarantee, not a special case, but callers should still only invoke
    this on language tags 'ta-en'/'hi-en'/'te-en' per Phase 9 of this
    experiment (never on 'ta'/'hi'/'te'/'en')."""
    if not query or not _HAS_LATIN_LETTER.search(query):
        return query

    protected, placeholders = _protect_proper_nouns(query)

    protected = _move_near_clauses_to_end(protected)
    for pattern, replacement in _REORDER_RULES:
        protected = pattern.sub(replacement, protected)
    for pattern, replacement in _WORD_RULES:
        protected = pattern.sub(replacement, protected)

    restored = _restore_proper_nouns(protected, placeholders)
    # Collapse any double-spacing left behind by a substitution.
    return re.sub(r"\s+", " ", restored).strip()
