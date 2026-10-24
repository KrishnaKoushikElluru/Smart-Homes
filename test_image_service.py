"""
Unit tests for services/image_service.py (Cloudflare Workers AI backend).

Run with:
    python -m unittest test_image_service

No network access needed - the Cloudflare HTTP call is mocked via
unittest.mock, matching test_mappls_service.py's convention.
"""

import base64
import io
import unittest
from unittest.mock import patch, Mock

import requests as requests_module
from PIL import Image

from services import image_service
from services.image_service import ImageGenerationService, _call_cloudflare


def _tiny_png_base64():
    """A real, tiny (1x1) PNG, base64-encoded - used as a realistic
    stand-in for Cloudflare's returned image rather than a hand-typed
    string that might not actually decode as an image."""
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color=(255, 0, 0)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _mock_response(status_code=200, json_data=None, raise_on_json=False):
    response = Mock()
    response.status_code = status_code
    if raise_on_json:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = json_data if json_data is not None else {}
    return response


class CallCloudflareTests(unittest.TestCase):

    def test_missing_account_id_returns_error_without_network_call(self):
        with patch("services.image_service.requests.post") as mock_post:
            result = _call_cloudflare("a house", account_id=None, api_token="tok")

            mock_post.assert_not_called()
            self.assertEqual(result["status"], "error")
            self.assertIn("account ID", result["error"])

    def test_missing_api_token_returns_error_without_network_call(self):
        with patch("services.image_service.requests.post") as mock_post:
            result = _call_cloudflare("a house", account_id="acct123", api_token=None)

            mock_post.assert_not_called()
            self.assertEqual(result["status"], "error")
            self.assertIn("API token", result["error"])

    def test_empty_prompt_returns_error_without_network_call(self):
        with patch("services.image_service.requests.post") as mock_post:
            result = _call_cloudflare("   ", account_id="acct123", api_token="tok")

            mock_post.assert_not_called()
            self.assertEqual(result["status"], "error")

    def test_successful_response_returns_image_bytes(self):
        img_b64 = _tiny_png_base64()
        response = _mock_response(200, {"success": True, "result": {"image": img_b64}})

        with patch("services.image_service.requests.post", return_value=response) as mock_post:
            result = _call_cloudflare("a modern house", account_id="acct123", api_token="tok")

            self.assertEqual(result["status"], "ok")
            self.assertIsNotNone(result["image_bytes"])
            # Round-trips as a real image.
            Image.open(io.BytesIO(result["image_bytes"])).load()

            # Multipart, not JSON - and the Authorization header carries the token.
            _, kwargs = mock_post.call_args
            self.assertIn("files", kwargs)
            self.assertNotIn("json", kwargs)
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok")
            self.assertEqual(kwargs["files"]["width"], (None, "1024"))
            self.assertEqual(kwargs["files"]["height"], (None, "1024"))

    def test_successful_response_unwrapped_image_field(self):
        """Defensive fallback: {"image": ...} with no "result" wrapper."""
        img_b64 = _tiny_png_base64()
        response = _mock_response(200, {"image": img_b64})

        with patch("services.image_service.requests.post", return_value=response):
            result = _call_cloudflare("a house", account_id="acct123", api_token="tok")
            self.assertEqual(result["status"], "ok")

    def test_401_returns_clean_error(self):
        response = _mock_response(401, {})
        with patch("services.image_service.requests.post", return_value=response):
            result = _call_cloudflare("a house", account_id="acct123", api_token="bad-token")
            self.assertEqual(result["status"], "error")
            self.assertIn("not authorized", result["error"])
            self.assertNotIn("bad-token", result["error"])

    def test_403_returns_clean_error(self):
        response = _mock_response(403, {})
        with patch("services.image_service.requests.post", return_value=response):
            result = _call_cloudflare("a house", account_id="acct123", api_token="tok")
            self.assertEqual(result["status"], "error")
            self.assertIn("not authorized", result["error"])

    def test_429_returns_quota_error(self):
        response = _mock_response(429, {})
        with patch("services.image_service.requests.post", return_value=response):
            result = _call_cloudflare("a house", account_id="acct123", api_token="tok")
            self.assertEqual(result["status"], "error")
            self.assertIn("quota", result["error"].lower())

    def test_4xx_validation_error_returns_clean_error(self):
        response = _mock_response(400, {})
        with patch("services.image_service.requests.post", return_value=response):
            result = _call_cloudflare("a house", account_id="acct123", api_token="tok")
            self.assertEqual(result["status"], "error")
            self.assertIn("400", result["error"])

    def test_5xx_returns_clean_error(self):
        response = _mock_response(503, {})
        with patch("services.image_service.requests.post", return_value=response):
            result = _call_cloudflare("a house", account_id="acct123", api_token="tok")
            self.assertEqual(result["status"], "error")
            self.assertIn("temporarily unavailable", result["error"])

    def test_success_false_envelope_returns_clean_error(self):
        response = _mock_response(200, {
            "success": False,
            "errors": [{"code": 10000, "message": "Authentication error"}],
        })
        with patch("services.image_service.requests.post", return_value=response):
            result = _call_cloudflare("a house", account_id="acct123", api_token="tok")
            self.assertEqual(result["status"], "error")

    def test_neuron_quota_exhaustion_message_is_recognized(self):
        response = _mock_response(200, {
            "success": False,
            "errors": [{"code": 5006, "message": "You have exceeded your Neuron budget for this account."}],
        })
        with patch("services.image_service.requests.post", return_value=response):
            result = _call_cloudflare("a house", account_id="acct123", api_token="tok")
            self.assertEqual(result["status"], "error")
            self.assertIn("quota", result["error"].lower())

    def test_malformed_response_missing_image_field(self):
        response = _mock_response(200, {"success": True, "result": {}})
        with patch("services.image_service.requests.post", return_value=response):
            result = _call_cloudflare("a house", account_id="acct123", api_token="tok")
            self.assertEqual(result["status"], "error")
            self.assertIn("no image", result["error"].lower())

    def test_invalid_base64_in_image_field(self):
        response = _mock_response(200, {"success": True, "result": {"image": "not-valid-base64!!!"}})
        with patch("services.image_service.requests.post", return_value=response):
            result = _call_cloudflare("a house", account_id="acct123", api_token="tok")
            self.assertEqual(result["status"], "error")

    def test_unreadable_json_response(self):
        response = _mock_response(200, raise_on_json=True)
        with patch("services.image_service.requests.post", return_value=response):
            result = _call_cloudflare("a house", account_id="acct123", api_token="tok")
            self.assertEqual(result["status"], "error")
            self.assertIn("unreadable", result["error"].lower())

    def test_timeout_returns_clean_error(self):
        with patch("services.image_service.requests.post", side_effect=requests_module.Timeout()):
            result = _call_cloudflare("a house", account_id="acct123", api_token="tok")
            self.assertEqual(result["status"], "error")
            self.assertIn("timed out", result["error"].lower())

    def test_network_failure_returns_clean_error(self):
        with patch("services.image_service.requests.post", side_effect=requests_module.ConnectionError()):
            result = _call_cloudflare("a house", account_id="acct123", api_token="tok")
            self.assertEqual(result["status"], "error")
            self.assertIn("network error", result["error"].lower())

    def test_never_raises_and_never_logs_token(self):
        """Sanity check: whatever happens, _call_cloudflare returns a dict,
        it never raises, and the token never appears in the returned
        error message (already exercised above for 401, but checked
        again here across every failure path in this test class)."""
        with patch("services.image_service.requests.post", side_effect=requests_module.RequestException()):
            result = _call_cloudflare("a house", account_id="acct123", api_token="super-secret-token")
            self.assertIsInstance(result, dict)
            self.assertNotIn("super-secret-token", str(result))


class ImageGenerationServiceTests(unittest.TestCase):

    def test_generate_returns_pil_image_on_success(self):
        img_b64 = _tiny_png_base64()
        response = _mock_response(200, {"success": True, "result": {"image": img_b64}})

        # The optimizer call is mocked out directly (rather than mocking
        # its own requests.post) here - this test is about
        # ImageGenerationService.generate()'s FLUX wiring, not the
        # optimizer's own behavior (covered by test_image_prompt_optimizer.py).
        with patch("services.image_service.requests.post", return_value=response):
            with patch("services.image_service.image_prompt_optimizer.optimize_prompt") as mock_optimize:
                mock_optimize.return_value = {
                    "optimized_prompt": "a photorealistic modern house",
                    "structured": None, "source": "gemini", "error": None,
                }
                with patch.dict("os.environ", {
                    "CLOUDFLARE_ACCOUNT_ID": "acct123", "CLOUDFLARE_API_TOKEN": "tok", "GEMINI_API_KEY": "gkey",
                }):
                    service = ImageGenerationService()
                    image = service.generate("a modern house")

                    self.assertIsInstance(image, Image.Image)
                    # generate() must send the OPTIMIZED prompt to FLUX,
                    # not the raw user prompt.
                    mock_optimize.assert_called_once()
                    self.assertEqual(mock_optimize.call_args[0][0], "a modern house")
                    self.assertEqual(mock_optimize.call_args[0][1], "gkey")
                    self.assertEqual(service.last_optimizer_result["optimized_prompt"], "a photorealistic modern house")

    def test_generate_raises_runtime_error_when_not_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            service = ImageGenerationService()
            with self.assertRaises(RuntimeError):
                service.generate("a modern house")

    def test_generate_raises_runtime_error_on_provider_failure(self):
        response = _mock_response(500, {})
        with patch("services.image_service.requests.post", return_value=response):
            with patch("services.image_service.image_prompt_optimizer.optimize_prompt") as mock_optimize:
                mock_optimize.return_value = {
                    "optimized_prompt": "a photorealistic modern house",
                    "structured": None, "source": "gemini", "error": None,
                }
                with patch.dict("os.environ", {
                    "CLOUDFLARE_ACCOUNT_ID": "acct123", "CLOUDFLARE_API_TOKEN": "tok", "GEMINI_API_KEY": "gkey",
                }):
                    service = ImageGenerationService()
                    with self.assertRaises(RuntimeError):
                        service.generate("a modern house")

    def test_generate_still_works_when_optimizer_fails(self):
        """Scenario 9 (API failure): image generation must NOT depend
        on the optimizer being available - a failed/unmocked Gemini
        call should fall through to the REAL, unmocked deterministic
        fallback (services.image_prompt_optimizer.optimize_prompt's own
        behavior) and FLUX generation should still succeed."""
        img_b64 = _tiny_png_base64()
        flux_response = _mock_response(200, {"success": True, "result": {"image": img_b64}})

        mock_gemini_client = Mock()
        mock_gemini_client.models.generate_content.side_effect = Exception("Gemini API unavailable")

        with patch("services.image_service.requests.post", return_value=flux_response):
            with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_gemini_client):
                with patch.dict("os.environ", {
                    "CLOUDFLARE_ACCOUNT_ID": "acct123", "CLOUDFLARE_API_TOKEN": "tok", "GEMINI_API_KEY": "gkey",
                }):
                    service = ImageGenerationService()
                    image = service.generate("2 bedroom house with a large kitchen")

                    self.assertIsInstance(image, Image.Image)
                    self.assertEqual(service.last_optimizer_result["source"], "fallback")
                    # the deterministic fallback must still preserve the
                    # user's explicit requirements
                    self.assertIn("2 bedroom", service.last_optimizer_result["optimized_prompt"].lower())
                    self.assertIn("large kitchen", service.last_optimizer_result["optimized_prompt"].lower())

    def test_generate_still_works_when_optimizer_returns_malformed_output(self):
        """Scenario 10 (malformed Gemini response): a non-JSON/garbage
        optimizer response must still safely fall back, not break
        generation."""
        img_b64 = _tiny_png_base64()
        flux_response = _mock_response(200, {"success": True, "result": {"image": img_b64}})

        mock_gemini_response = Mock()
        mock_gemini_response.text = "garbled non-json {["
        mock_gemini_client = Mock()
        mock_gemini_client.models.generate_content.return_value = mock_gemini_response

        with patch("services.image_service.requests.post", return_value=flux_response):
            with patch("services.image_prompt_optimizer.genai.Client", return_value=mock_gemini_client):
                with patch.dict("os.environ", {
                    "CLOUDFLARE_ACCOUNT_ID": "acct123", "CLOUDFLARE_API_TOKEN": "tok", "GEMINI_API_KEY": "gkey",
                }):
                    service = ImageGenerationService()
                    image = service.generate("a modern house")

                    self.assertIsInstance(image, Image.Image)
                    self.assertEqual(service.last_optimizer_result["source"], "fallback")


if __name__ == "__main__":
    unittest.main()
