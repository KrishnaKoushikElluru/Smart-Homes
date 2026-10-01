"""
Unit tests for services/image_prompt_optimizer.py (Gemini 3.5 Flash-Lite
semantic-understanding layer + deterministic prompt builder).

Run with:
    python -m unittest test_image_prompt_optimizer

No network access needed - the Gemini client is mocked via
unittest.mock (patching services.image_prompt_optimizer.genai.Client),
matching this project's existing mocking convention
(test_mappls_service.py / test_image_service.py). NONE of these tests
make a live Gemini API call.

Three layers are tested:
  1. _validate_structure / build_final_prompt - pure functions, no
     mocking needed, the most important logic to get right since this
     is where avoid_misinterpretations gets deterministically woven
     into the FLUX-facing prompt (see services/image_prompt_optimizer.py's
     own docstring for why this - not Gemini's own wording - is the
     real guarantee).
  2. _call_gemini / optimize_prompt - given a MOCKED Gemini client,
     does this module correctly parse, validate, and fall back?
  3. Scenario tests (the 17 required by this phase's task) - realistic
     structured dicts standing in for what Gemini demonstrably produces
     (grounded in the 25-prompt live benchmark, not invented), run
     through the REAL, unmodified build_final_prompt().
"""

import unittest
from unittest.mock import patch, Mock

from google.genai import errors as genai_errors

from services import image_prompt_optimizer
from services.image_prompt_optimizer import (
    optimize_prompt,
    build_final_prompt,
    _deterministic_fallback,
    _call_gemini,
    _validate_structure,
    _coerce_str_list,
    _redact,
)


def _structured(
    intent="a residential house",
    visual_subject="A residential house.",
    functional_requirements=None,
    context=None,
    economic_level="practical, modest",
    style_requirements=None,
    avoid_misinterpretations=None,
):
    return {
        "intent": intent,
        "visual_subject": visual_subject,
        "functional_requirements": functional_requirements or [],
        "context": context or [],
        "economic_level": economic_level,
        "style_requirements": style_requirements or [],
        "avoid_misinterpretations": avoid_misinterpretations or [],
    }


def _mock_gemini_client(response_text=None, raise_exception=None):
    mock_client = Mock()
    if raise_exception is not None:
        mock_client.models.generate_content.side_effect = raise_exception
    else:
        mock_response = Mock()
        mock_response.text = response_text
        mock_client.models.generate_content.return_value = mock_response
    return mock_client


def _json_response(structured_dict):
    import json
    return json.dumps(structured_dict)


class ValidateStructureTests(unittest.TestCase):

    def test_valid_structure_normalizes_cleanly(self):
        raw = {
            "intent": " wants a house ",
            "visual_subject": " a house ",
            "functional_requirements": ["spacious hall", 1, None, "  "],
            "context": ["home tuition"],
            "economic_level": " modest ",
            "style_requirements": [],
            "avoid_misinterpretations": ["classroom"],
        }
        result = _validate_structure(raw)
        self.assertEqual(result["intent"], "wants a house")
        self.assertEqual(result["visual_subject"], "a house")
        self.assertEqual(result["functional_requirements"], ["spacious hall", "1"])
        self.assertEqual(result["avoid_misinterpretations"], ["classroom"])

    def test_missing_required_field_returns_none(self):
        raw = {"visual_subject": "a house", "economic_level": "modest"}
        self.assertIsNone(_validate_structure(raw))

    def test_empty_required_string_returns_none(self):
        raw = {"intent": "", "visual_subject": "a house", "economic_level": "modest"}
        self.assertIsNone(_validate_structure(raw))

    def test_non_dict_returns_none(self):
        self.assertIsNone(_validate_structure(["not", "a", "dict"]))
        self.assertIsNone(_validate_structure("just a string"))
        self.assertIsNone(_validate_structure(None))

    def test_missing_list_fields_default_to_empty(self):
        raw = {"intent": "x", "visual_subject": "y", "economic_level": "z"}
        result = _validate_structure(raw)
        self.assertEqual(result["functional_requirements"], [])
        self.assertEqual(result["context"], [])

    def test_extra_unexpected_fields_are_ignored_not_fatal(self):
        raw = {
            "intent": "x", "visual_subject": "y", "economic_level": "z",
            "final_image_prompt": "should be ignored - the builder makes this, not Gemini",
            "some_unexpected_field": 123,
        }
        result = _validate_structure(raw)
        self.assertIsNotNone(result)
        self.assertNotIn("final_image_prompt", result)
        self.assertNotIn("some_unexpected_field", result)


class RedactTests(unittest.TestCase):

    def test_redacts_key_from_text(self):
        text = "error calling https://api?key=super-secret-123 failed"
        self.assertNotIn("super-secret-123", _redact(text, "super-secret-123"))

    def test_no_key_present_returns_text_unchanged(self):
        text = "generic error"
        self.assertEqual(_redact(text, "some-key"), text)

    def test_handles_none_key(self):
        self.assertEqual(_redact("generic error", None), "generic error")


class BuildFinalPromptTests(unittest.TestCase):
    """The most important tests in this file: does the DETERMINISTIC
    builder correctly weave avoid_misinterpretations into the FLUX-facing
    text, and never invent anything beyond the structured input?"""

    def test_avoid_misinterpretations_reaches_final_prompt_explicitly(self):
        structured = _structured(
            visual_subject="A residential house with a spacious, ventilated hall.",
            functional_requirements=["hall capacity for about 20 people"],
            context=["occasional home tuition"],
            avoid_misinterpretations=[
                "not a classroom", "not a school", "not a tuition center", "no rows of desks", "no blackboard",
            ],
        )
        prompt = build_final_prompt(structured).lower()
        self.assertIn("private residence", prompt)  # the hardcoded residential safety clause
        self.assertIn("classroom", prompt)
        self.assertIn("school", prompt)
        self.assertIn("tuition center", prompt)
        self.assertIn("rows of desks", prompt)
        self.assertIn("blackboard", prompt)

    def test_no_avoid_misinterpretations_produces_no_empty_avoid_clause(self):
        structured = _structured(visual_subject="A residential kitchen.")
        prompt = build_final_prompt(structured)
        self.assertNotIn("Specifically avoid: .", prompt)
        self.assertNotIn("Avoid:  .", prompt)

    def test_never_invents_features_not_in_structured_input(self):
        structured = _structured(visual_subject="A plain, simple residential house.")
        prompt = build_final_prompt(structured).lower()
        for forbidden in ("pool", "swimming", "balcony", "garden", "marble", "smart home", "terrace", "basement"):
            self.assertNotIn(forbidden, prompt)

    def test_functional_requirements_and_context_both_included(self):
        structured = _structured(
            functional_requirements=["quiet home workspace"],
            context=["works from home most days"],
        )
        prompt = build_final_prompt(structured)
        self.assertIn("quiet home workspace", prompt)
        self.assertIn("works from home most days", prompt)

    def test_economic_level_included(self):
        structured = _structured(economic_level="low budget, cost-conscious, not damaged or unfinished")
        prompt = build_final_prompt(structured)
        self.assertIn("low budget, cost-conscious, not damaged or unfinished", prompt)

    def test_hard_word_cap_enforced(self):
        structured = _structured(
            functional_requirements=["word " * 50],
            context=["word " * 50],
            avoid_misinterpretations=["word " * 50],
        )
        prompt = build_final_prompt(structured)
        self.assertLessEqual(len(prompt.split()), image_prompt_optimizer.HARD_WORD_CAP + 1)

    def test_baseline_quality_phrase_never_truncated(self):
        """Regression test for a real bug: word-capping the WHOLE
        assembled string (body + baseline phrase together) could cut
        the fixed BASELINE_QUALITY_PHRASE off mid-sentence when the
        variable body was already long. The baseline phrase must always
        survive intact, appended whole after the body is capped."""
        structured = _structured(
            functional_requirements=["word " * 60],
            context=["word " * 60],
            avoid_misinterpretations=["word " * 60],
        )
        prompt = build_final_prompt(structured)
        self.assertTrue(
            prompt.endswith(image_prompt_optimizer.BASELINE_QUALITY_PHRASE),
            f"baseline quality phrase was truncated: prompt ends with ...{prompt[-80:]!r}",
        )


class CallGeminiTests(unittest.TestCase):

    def test_missing_api_key_returns_error_without_network_call(self):
        with patch("services.image_prompt_optimizer.genai.Client") as mock_client_cls:
            result = _call_gemini("a house", api_key=None)
            mock_client_cls.assert_not_called()
            self.assertEqual(result["status"], "error")
            self.assertIn("Gemini API key", result["error"])

    def test_successful_valid_json_response(self):
        mock_client = _mock_gemini_client(_json_response(_structured()))
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            result = _call_gemini("a house", api_key="fake-key")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["visual_subject"], "A residential house.")

    def test_uses_configured_model_and_schema(self):
        mock_client = _mock_gemini_client(_json_response(_structured()))
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            _call_gemini("a house", api_key="fake-key")
            _, kwargs = mock_client.models.generate_content.call_args
            self.assertEqual(kwargs["model"], image_prompt_optimizer.GEMINI_MODEL)
            self.assertEqual(kwargs["config"].response_mime_type, "application/json")
            self.assertIsNotNone(kwargs["config"].response_schema)

    def test_malformed_json_returns_error(self):
        mock_client = _mock_gemini_client("this is not { valid json")
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            result = _call_gemini("a house", api_key="fake-key")
            self.assertEqual(result["status"], "error")

    def test_missing_required_field_returns_error(self):
        import json
        mock_client = _mock_gemini_client(json.dumps({"visual_subject": "a house"}))
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            result = _call_gemini("a house", api_key="fake-key")
            self.assertEqual(result["status"], "error")

    def test_unexpected_extra_field_does_not_fail(self):
        import json
        raw = _structured()
        raw["unexpected_field"] = "surprise"
        mock_client = _mock_gemini_client(json.dumps(raw))
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            result = _call_gemini("a house", api_key="fake-key")
            self.assertEqual(result["status"], "ok")

    def test_empty_response_text_returns_error(self):
        mock_client = _mock_gemini_client("")
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            result = _call_gemini("a house", api_key="fake-key")
            self.assertEqual(result["status"], "error")

    def test_client_error_returns_clean_error_without_key(self):
        exc = genai_errors.ClientError(404, {"error": {"message": "model not found with key fake-key-123"}})
        mock_client = _mock_gemini_client(raise_exception=exc)
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            result = _call_gemini("a house", api_key="fake-key-123")
            self.assertEqual(result["status"], "error")
            self.assertNotIn("fake-key-123", result["error"])

    def test_server_error_returns_clean_error(self):
        exc = genai_errors.ServerError(503, {"error": {"message": "unavailable"}})
        mock_client = _mock_gemini_client(raise_exception=exc)
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            result = _call_gemini("a house", api_key="fake-key")
            self.assertEqual(result["status"], "error")

    def test_generic_exception_timeout_does_not_raise(self):
        mock_client = _mock_gemini_client(raise_exception=TimeoutError("timed out"))
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            result = _call_gemini("a house", api_key="fake-key")
            self.assertEqual(result["status"], "error")

    def test_api_key_never_appears_in_logged_error(self):
        exc = Exception("request failed for key=super-secret-abc123")
        mock_client = _mock_gemini_client(raise_exception=exc)
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            with self.assertLogs("services.image_prompt_optimizer", level="WARNING") as cm:
                result = _call_gemini("a house", api_key="super-secret-abc123")
                self.assertEqual(result["status"], "error")
                self.assertNotIn("super-secret-abc123", result["error"])
                for log_line in cm.output:
                    self.assertNotIn("super-secret-abc123", log_line)


class OptimizePromptTests(unittest.TestCase):

    def test_empty_prompt_uses_fallback_without_network_call(self):
        with patch("services.image_prompt_optimizer.genai.Client") as mock_client_cls:
            result = optimize_prompt("   ", api_key="fake-key")
            mock_client_cls.assert_not_called()
            self.assertEqual(result["source"], "fallback")

    def test_successful_response_uses_deterministic_builder_not_gemini_wording(self):
        structured = _structured(
            visual_subject="A residential house with a spacious hall.",
            avoid_misinterpretations=["not a classroom"],
        )
        mock_client = _mock_gemini_client(_json_response(structured))
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            result = optimize_prompt("some house prompt", api_key="fake-key")
            self.assertEqual(result["source"], "gemini")
            self.assertIn("classroom", result["optimized_prompt"].lower())
            self.assertEqual(result["structured"]["visual_subject"], "A residential house with a spacious hall.")

    def test_gemini_failure_falls_back_and_preserves_user_prompt(self):
        mock_client = _mock_gemini_client(raise_exception=Exception("boom"))
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            result = optimize_prompt("2 bedroom house with a large kitchen", api_key="fake-key")
            self.assertEqual(result["source"], "fallback")
            self.assertIsNotNone(result["error"])
            self.assertIn("2 bedroom house with a large kitchen", result["optimized_prompt"])

    def test_never_raises_across_every_failure_mode(self):
        scenarios = [
            Exception("generic"),
            genai_errors.ClientError(400, {"error": {"message": "bad request"}}),
            genai_errors.ServerError(500, {"error": {"message": "down"}}),
            TimeoutError("timeout"),
        ]
        for exc in scenarios:
            mock_client = _mock_gemini_client(raise_exception=exc)
            with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
                result = optimize_prompt("a house", api_key="fake-key")
                self.assertIsInstance(result, dict)
                self.assertTrue(result["optimized_prompt"])
                self.assertEqual(result["source"], "fallback")


class RequiredScenarioTests(unittest.TestCase):
    """The 17 scenarios required by this phase's task, run through the
    REAL build_final_prompt() against realistic structured extractions
    (grounded in the 25-prompt live benchmark's actual Gemini outputs,
    not invented)."""

    def test_1_tuition_original_difficult_prompt(self):
        structured = _structured(
            visual_subject="A modest, middle-class residential house with a spacious, well-ventilated main hall.",
            functional_requirements=["spacious main hall", "good ventilation", "capacity for about 20 people occasionally"],
            context=["occasional home tuition"],
            economic_level="middle class, low budget, practical, cost-conscious",
            avoid_misinterpretations=[
                "not a commercial school, tuition center, or institutional building",
                "no rows of desks or a blackboard", "not luxurious",
            ],
        )
        prompt = build_final_prompt(structured).lower()
        self.assertIn("residen", prompt)
        self.assertIn("spacious", prompt)
        self.assertIn("ventilat", prompt)
        self.assertIn("20 people", prompt)
        self.assertIn("middle class", prompt)
        self.assertIn("tuition center", prompt)
        self.assertIn("blackboard", prompt)

    def test_2_work_from_home(self):
        structured = _structured(
            functional_requirements=["quiet home workspace"],
            context=["works from home most days"],
            avoid_misinterpretations=["not a corporate office", "not a commercial workspace"],
        )
        prompt = build_final_prompt(structured).lower()
        self.assertIn("workspace", prompt)
        self.assertIn("office", prompt)

    def test_3_children_studying(self):
        structured = _structured(
            functional_requirements=["well-lit study area"],
            context=["children study here in the evenings"],
            avoid_misinterpretations=["not a classroom", "no blackboards", "not a school"],
        )
        prompt = build_final_prompt(structured).lower()
        self.assertIn("study", prompt)
        self.assertIn("classroom", prompt)

    def test_4_elderly_parents(self):
        structured = _structured(
            functional_requirements=["ground-floor accessibility", "minimal stairs"],
            context=["elderly parents live with the family"],
            avoid_misinterpretations=["not a hospital or care facility"],
        )
        prompt = build_final_prompt(structured).lower()
        self.assertIn("accessib", prompt)
        self.assertIn("hospital", prompt)

    def test_5_large_family(self):
        structured = _structured(
            functional_requirements=["enough rooms for a family of 7"],
            context=["large family household"],
            avoid_misinterpretations=["not a dormitory or hotel"],
        )
        prompt = build_final_prompt(structured).lower()
        self.assertIn("7", prompt)
        self.assertIn("dormitory", prompt)

    def test_6_large_guests(self):
        structured = _structured(
            functional_requirements=["spacious living area for 15-20 guests occasionally"],
            context=["relatives visit during festivals"],
            avoid_misinterpretations=["not a banquet hall or hotel", "no crowd of people shown"],
        )
        prompt = build_final_prompt(structured).lower()
        self.assertIn("15-20", prompt)
        self.assertIn("banquet hall", prompt)

    def test_7_low_budget(self):
        structured = _structured(economic_level="low budget, cost-conscious, clean and well-kept, not damaged or unfinished")
        prompt = build_final_prompt(structured).lower()
        self.assertIn("low budget", prompt)
        self.assertIn("well-kept", prompt)
        # build_final_prompt must never independently ADD a negative-
        # quality claim of its own beyond what's in the structured input.
        self.assertNotIn("run-down", prompt)
        self.assertNotIn("abandoned", prompt)

    def test_8_middle_class(self):
        structured = _structured(economic_level="middle class, practical, modest, nothing fancy")
        prompt = build_final_prompt(structured).lower()
        self.assertIn("middle class", prompt)

    def test_9_not_luxurious(self):
        structured = _structured(
            economic_level="practical, not luxurious",
            avoid_misinterpretations=["avoid luxurious or extravagant appearance"],
        )
        prompt = build_final_prompt(structured).lower()
        self.assertIn("luxurious", prompt)

    def test_10_modern_but_affordable(self):
        structured = _structured(
            style_requirements=["modern architectural lines"],
            economic_level="cost-conscious, affordable materials",
        )
        prompt = build_final_prompt(structured).lower()
        self.assertIn("modern", prompt)
        self.assertIn("afford", prompt)

    def test_11_traditional_not_stereotyped(self):
        structured = _structured(
            style_requirements=["traditional house feel"],
            avoid_misinterpretations=["not a stereotypical postcard-style village house"],
        )
        prompt = build_final_prompt(structured).lower()
        self.assertIn("traditional", prompt)
        self.assertIn("postcard", prompt)

    def test_12_kitchen_only_request(self):
        structured = _structured(
            visual_subject="A residential home with a slightly larger kitchen.",
            functional_requirements=["bigger kitchen for cooking for a large family"],
            avoid_misinterpretations=["not a commercial restaurant kitchen"],
        )
        prompt = build_final_prompt(structured).lower()
        self.assertIn("kitchen", prompt)
        self.assertIn("commercial", prompt)

    def test_13_parking_request(self):
        structured = _structured(functional_requirements=["parking space for two cars and a scooter"])
        prompt = build_final_prompt(structured).lower()
        self.assertIn("two cars", prompt)
        self.assertIn("scooter", prompt)

    def test_14_storage_request(self):
        structured = _structured(functional_requirements=["ample built-in storage and cupboards"])
        prompt = build_final_prompt(structured).lower()
        self.assertIn("storage", prompt)
        self.assertIn("cupboards", prompt)

    def test_15_do_not_add_anything_extra(self):
        structured = _structured(visual_subject="A plain, simple residential house with no added features.")
        prompt = build_final_prompt(structured).lower()
        for forbidden in ("pool", "balcony", "garden", "marble", "extra floor"):
            self.assertNotIn(forbidden, prompt)

    def test_16_multiple_requirements_all_preserved(self):
        structured = _structured(
            functional_requirements=["3 bedrooms", "attached bathroom", "big hall", "small garden", "parking for 1 car"],
            economic_level="normal budget, nothing extra",
        )
        prompt = build_final_prompt(structured)
        for requirement in ("3 bedrooms", "attached bathroom", "big hall", "small garden", "parking for 1 car"):
            self.assertIn(requirement, prompt)

    def test_17_negative_requirements_retained(self):
        structured = _structured(
            avoid_misinterpretations=["no swimming pool", "no huge garden", "nothing over the top"],
        )
        prompt = build_final_prompt(structured).lower()
        self.assertIn("no swimming pool", prompt)
        self.assertIn("no huge garden", prompt)


class KitchenRegressionTests(unittest.TestCase):
    """The specific regression this task calls out: a kitchen-only
    prompt must NEVER inherit tuition/20-people/classroom/school
    language from an unrelated example."""

    def test_kitchen_only_prompt_never_mentions_tuition_or_classroom(self):
        structured = _structured(
            intent="wants a larger, well-ventilated kitchen",
            visual_subject="A residential home with a larger, well-ventilated kitchen.",
            functional_requirements=["larger kitchen", "good ventilation"],
            context=[],
            avoid_misinterpretations=["not a commercial kitchen"],
        )
        prompt = build_final_prompt(structured).lower()
        for forbidden in ("tuition", "20 people", "classroom", "school"):
            self.assertNotIn(forbidden, prompt)

    def test_gemini_mocked_end_to_end_kitchen_prompt_stays_clean(self):
        structured = {
            "intent": "wants a larger, well-ventilated kitchen",
            "visual_subject": "A residential home with a larger, well-ventilated kitchen.",
            "functional_requirements": ["larger kitchen", "good ventilation"],
            "context": [],
            "economic_level": "practical",
            "style_requirements": [],
            "avoid_misinterpretations": ["not a commercial kitchen"],
        }
        mock_client = _mock_gemini_client(_json_response(structured))
        with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_client):
            result = optimize_prompt("I want a larger practical kitchen with good ventilation.", api_key="fake-key")
            prompt = result["optimized_prompt"].lower()
            for forbidden in ("tuition", "20 people", "classroom", "school"):
                self.assertNotIn(forbidden, prompt)


if __name__ == "__main__":
    unittest.main()
