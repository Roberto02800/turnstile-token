"""Offline tests for turnstile-token.

Nothing here touches the network: transport calls are replaced with fakes so
the suite runs without an API key and without internet access.
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import turnstile_token as ts


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def patch_urlopen(handler):
    """Return a context manager stand-in for urllib.request.urlopen."""
    return mock.patch.object(ts, "urlopen", side_effect=handler)


class SitekeyScannerTests(unittest.TestCase):
    def setUp(self):
        self.scanner = ts.SitekeyScanner()

    def test_finds_data_sitekey_attribute(self):
        html = '<div class="cf-turnstile" data-sitekey="0x4AAAAAAAabc123"></div>'
        hits = self.scanner.scan(html)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].value, "0x4AAAAAAAabc123")
        self.assertEqual(hits[0].source, "attr")

    def test_finds_js_sitekey_assignment(self):
        html = "turnstile.render(el, { sitekey: '0x4AAAAAAAzzz999' });"
        hits = self.scanner.scan(html)
        self.assertEqual(hits[0].value, "0x4AAAAAAAzzz999")
        self.assertEqual(hits[0].source, "js")

    def test_finds_sitekey_in_query_string(self):
        html = '<iframe src="/cdn-cgi/challenge-platform/...?k=0x4AAAAAAAqqq111"></iframe>'
        hits = self.scanner.scan(html)
        self.assertEqual(hits[0].value, "0x4AAAAAAAqqq111")
        self.assertEqual(hits[0].source, "qs")

    def test_returns_empty_when_absent(self):
        self.assertEqual(self.scanner.scan("<html><body>nothing here</body></html>"), [])

    def test_deduplicates_preserving_order(self):
        html = 'data-sitekey="AAA" then sitekey: "BBB" then data-sitekey="AAA"'
        values = self.scanner.values(html)
        self.assertEqual(values, ["AAA", "BBB"])

    def test_confidence_ranks_attr_above_js_above_qs(self):
        html = 'k=0xQS111111111111 sitekey: "0xJS222222222222" data-sitekey="0xAT333333333333"'
        hits = self.scanner.scan(html)
        self.assertEqual(hits[0].value, "0xAT333333333333")
        self.assertEqual(hits[1].value, "0xJS222222222222")
        self.assertEqual(hits[2].value, "0xQS111111111111")
        self.assertGreater(hits[0].confidence, hits[1].confidence)
        self.assertGreater(hits[1].confidence, hits[2].confidence)

    def test_context_snippet_is_captured(self):
        html = '<div class="cf-turnstile" data-sitekey="0x4AAAAAAAabc123" data-action="login">'
        hit = self.scanner.best(html)
        self.assertIn("cf-turnstile", hit.context)

    def test_best_returns_none_when_empty(self):
        self.assertIsNone(self.scanner.best(""))

    def test_module_helpers_delegate(self):
        html = '<div data-sitekey="0xHELPER"></div>'
        self.assertEqual(ts.discover_sitekey(html), "0xHELPER")
        self.assertEqual(ts.discover_sitekeys(html), ["0xHELPER"])


class TokenVerificationTests(unittest.TestCase):
    def test_valid_token_is_plausible(self):
        token = "0.mF74dQpX2rC8vT1kLzB6hN3sYwA9eJgUiO5"
        report = ts.verify_token(token)
        self.assertTrue(report.plausible)
        self.assertEqual(report.length, len(token))
        self.assertEqual(report.segments, 2)

    def test_empty_token_is_rejected(self):
        report = ts.verify_token("")
        self.assertFalse(report.plausible)
        self.assertEqual(report.reasons, ["empty"])

    def test_short_token_is_rejected(self):
        report = ts.verify_token("0.abc")
        self.assertFalse(report.plausible)
        self.assertTrue(any("short" in r for r in report.reasons))

    def test_token_without_dots_is_rejected(self):
        report = ts.verify_token("a" * 50)
        self.assertFalse(report.plausible)
        self.assertTrue(any("dot" in r for r in report.reasons))

    def test_token_with_whitespace_is_flagged(self):
        report = ts.verify_token("0." + "a" * 30 + " " + "b" * 10)
        self.assertTrue(any("whitespace" in r for r in report.reasons))

    def test_token_with_illegal_chars_is_flagged(self):
        report = ts.verify_token("0." + "a" * 30 + "!!!")
        self.assertFalse(report.plausible)
        self.assertTrue(any("alphabet" in r for r in report.reasons))

    def test_valid_token_reason_says_correct(self):
        report = ts.verify_token("0.mF74dQpX2rC8vT1kLzB6hN3sYwA9eJgUiO5")
        self.assertIn("shape looks correct", report.reasons)


class TaskBuildingTests(unittest.TestCase):
    def test_task_requires_sitekey(self):
        with self.assertRaises(ts.TurnstileError) as ctx:
            ts._build_task("https://example.com/login", "")
        self.assertEqual(ctx.exception.code, "ERROR_INVALID_TASK_DATA")
        self.assertFalse(ctx.exception.retryable)

    def test_task_shape(self):
        task = ts._build_task(
            "https://example.com/login",
            "0x4AAAAAAAabc",
            action="login",
        )
        self.assertEqual(task["type"], "AntiTurnstileTask")
        self.assertEqual(task["websiteKey"], "0x4AAAAAAAabc")
        self.assertEqual(task["metadata"], {"action": "login"})
        self.assertNotIn("proxy", task)

    def test_proxy_shorthand_is_normalised(self):
        task = ts._build_task("https://example.com/", "0xKEY", proxy="1.2.3.4:8080:user:pass")
        self.assertEqual(task["proxy"], "http://user:pass@1.2.3.4:8080")

    def test_proxy_url_is_left_alone(self):
        task = ts._build_task("https://example.com/", "0xKEY", proxy="http://u:p@1.2.3.4:8080")
        self.assertEqual(task["proxy"], "http://u:p@1.2.3.4:8080")

    def test_no_action_field_when_absent(self):
        task = ts._build_task("https://example.com/", "0xKEY")
        self.assertNotIn("metadata", task)


class ErrorTests(unittest.TestCase):
    def test_retryable_codes(self):
        for code in ("ERROR_CAPTCHA_UNSOLVABLE", "ERROR_SERVICE_UNAVAILABLE", "ERROR_NO_SLOT_AVAILABLE"):
            self.assertTrue(ts.TurnstileError(code).retryable, code)

    def test_non_retryable_codes(self):
        for code in (
            "ERROR_KEY_DOES_NOT_EXIST",
            "ERROR_INVALID_TASK_DATA",
            "ERROR_TASK_NOT_SUPPORTED",
            "ERROR_TASKID_INVALID",
        ):
            self.assertFalse(ts.TurnstileError(code).retryable, code)

    def test_message_includes_code_and_description(self):
        err = ts.TurnstileError("ERROR_NO_SLOT_AVAILABLE", "full", http_status=503, retry_after=2.0)
        self.assertEqual(str(err), "ERROR_NO_SLOT_AVAILABLE: full")
        self.assertEqual(err.retry_after, 2.0)
        self.assertEqual(err.http_status, 503)


class ReplayBundleTests(unittest.TestCase):
    def test_identity_block(self):
        bundle = ts.ReplayBundle(
            token="0.abc",
            user_agent="Mozilla/5.0",
            profile_id="brave151-windows",
            emulation={"alpn": ["h2"]},
        )
        self.assertEqual(bundle.identity["userAgent"], "Mozilla/5.0")
        self.assertEqual(bundle.identity["profileId"], "brave151-windows")
        self.assertEqual(bundle.identity["emulation"]["alpn"], ["h2"])

    def test_replay_headers_overrides_user_agent(self):
        bundle = ts.ReplayBundle(token="0.abc", user_agent="Mozilla/5.0", headers={"accept": "text/html"})
        headers = bundle.replay_headers()
        self.assertEqual(headers["User-Agent"], "Mozilla/5.0")
        self.assertEqual(headers["accept"], "text/html")

    def test_form_fields_include_both_names(self):
        bundle = ts.ReplayBundle(token="0.abc")
        fields = bundle.form_fields()
        self.assertEqual(fields["cf-turnstile-response"], "0.abc")
        self.assertEqual(fields["g-recaptcha-response"], "0.abc")

    def test_as_dict_is_json_ready(self):
        bundle = ts.ReplayBundle(token="0.abc", sitekey="0xKEY", url="https://x/", elapsed=0.451)
        data = bundle.as_dict()
        json.dumps(data)
        self.assertEqual(data["token"], "0.abc")
        self.assertEqual(data["sitekey"], "0xKEY")
        self.assertEqual(data["elapsed"], 0.451)


class ClientTests(unittest.TestCase):
    def make_client(self, **kwargs):
        return ts.TurnstileClient("test-key", attempts=2, poll_grace=0.0, poll_interval=0.0, **kwargs)

    def test_from_env_reads_key(self):
        with mock.patch.dict(os.environ, {ts.ENV_API_KEY: "abc123"}):
            client = ts.TurnstileClient.from_env()
        self.assertEqual(client.api_key, "abc123")

    def test_from_env_without_key_raises(self):
        env = {k: v for k, v in os.environ.items() if k != ts.ENV_API_KEY}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ts.TurnstileError) as ctx:
                ts.TurnstileClient.from_env()
        self.assertEqual(ctx.exception.code, "ERROR_KEY_DOES_NOT_EXIST")
        self.assertEqual(ctx.exception.http_status, 401)

    def test_bundle_carries_replay_identity(self):
        payload = {
            "taskId": "t-1",
            "status": "ready",
            "solution": {
                "token": "0.abc",
                "type": "turnstile",
                "userAgent": "Mozilla/5.0",
                "profileId": "brave151-windows",
                "cookies": {"cf_clearance": "0.abc"},
                "headers": {"user-agent": "Mozilla/5.0"},
                "emulation": {"alpn": ["h2"], "key_shares": ["X25519MLKEM768"]},
            },
        }
        bundle = ts._bundle(payload, task_id="t-1", elapsed=0.451)
        self.assertEqual(bundle.token, "0.abc")
        self.assertEqual(bundle.identity["profileId"], "brave151-windows")
        self.assertEqual(bundle.identity["emulation"]["key_shares"], ["X25519MLKEM768"])
        self.assertEqual(bundle.as_dict()["sitekey"], "")

    def test_poll_returns_when_ready(self):
        client = self.make_client()
        states = [{"status": "processing"}, {"status": "ready", "solution": {"token": "tok"}}]
        with mock.patch.object(client, "result", side_effect=states):
            bundle = client.poll("t-1")
        self.assertEqual(bundle.token, "tok")

    def test_poll_raises_on_failed_status(self):
        client = self.make_client()
        state = {
            "status": "failed",
            "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
            "errorDescription": "no token produced",
        }
        with mock.patch.object(client, "result", return_value=state):
            with self.assertRaises(ts.TurnstileError) as ctx:
                client.poll("t-1")
        self.assertEqual(ctx.exception.code, "ERROR_CAPTCHA_UNSOLVABLE")
        self.assertTrue(ctx.exception.retryable)

    def test_retry_stops_on_non_retryable_error(self):
        client = self.make_client()
        error = ts.TurnstileError("ERROR_INVALID_TASK_DATA", "bad request")
        with mock.patch.object(ts, "create_task", side_effect=error) as fake:
            with self.assertRaises(ts.TurnstileError):
                client.create({"type": "AntiTurnstileTask", "websiteURL": "https://x/"})
        self.assertEqual(fake.call_count, 1)

    def test_retry_honours_retry_after(self):
        client = self.make_client()
        errors = [
            ts.TurnstileError("ERROR_NO_SLOT_AVAILABLE", "full", http_status=503, retry_after=0),
            "t-ok",
        ]
        with mock.patch.object(ts, "create_task", side_effect=errors) as fake:
            with mock.patch.object(ts.time, "sleep") as sleeper:
                task_id = client.create({"type": "AntiTurnstileTask", "websiteURL": "https://x/"})
        self.assertEqual(task_id, "t-ok")
        self.assertEqual(fake.call_count, 2)
        sleeper.assert_called_once_with(0)

    def test_solve_builds_the_right_task(self):
        client = self.make_client()
        seen = {}

        def fake_create(api_key, task, timeout, proxy=None):
            seen.update(task)
            return "t-42"

        with mock.patch.object(ts, "create_task", side_effect=fake_create):
            with mock.patch.object(client, "poll") as poll:
                client.solve("https://example.com/login", sitekey="0xKEY", action="login")
        self.assertEqual(seen["type"], "AntiTurnstileTask")
        self.assertEqual(seen["websiteKey"], "0xKEY")
        self.assertEqual(seen["metadata"], {"action": "login"})
        poll.assert_called_once_with("t-42")

    def test_solve_discovers_sitekey_when_omitted(self):
        client = self.make_client()
        html = '<div data-sitekey="0xAUTO"></div>'
        seen = {}

        def fake_create(api_key, task, timeout, proxy=None):
            seen.update(task)
            return "t-1"

        with mock.patch.object(ts, "read_page", return_value=html):
            with mock.patch.object(ts, "create_task", side_effect=fake_create):
                with mock.patch.object(client, "poll", return_value=ts.ReplayBundle(token="0.t")):
                    bundle = client.solve("https://example.com/login")
        self.assertEqual(seen["websiteKey"], "0xAUTO")
        self.assertEqual(bundle.sitekey, "0xAUTO")
        self.assertEqual(bundle.url, "https://example.com/login")

    def test_solve_raises_when_no_sitekey_found(self):
        client = self.make_client()
        with mock.patch.object(ts, "read_page", return_value="<html>no widget</html>"):
            with self.assertRaises(ts.TurnstileError) as ctx:
                client.solve("https://example.com/login")
        self.assertEqual(ctx.exception.code, "ERROR_INVALID_TASK_DATA")

    def test_balance_parses_float(self):
        client = self.make_client()
        with mock.patch.object(ts, "get_balance", return_value=303.43519):
            self.assertAlmostEqual(client.balance(), 303.43519)


class TransportTests(unittest.TestCase):
    def test_protocol_error_in_body_raises(self):
        payload = {
            "errorId": 1,
            "errorCode": "ERROR_TASKID_INVALID",
            "errorDescription": "expired",
        }
        with patch_urlopen(lambda req, timeout=0: FakeResponse(payload)):
            with self.assertRaises(ts.TurnstileError) as ctx:
                ts._post("/getTaskResult", {"taskId": "x"}, "key", 5.0)
        self.assertEqual(ctx.exception.code, "ERROR_TASKID_INVALID")
        self.assertFalse(ctx.exception.retryable)

    def test_success_body_is_returned(self):
        payload = {"errorId": 0, "balance": 12.5, "packages": []}
        with patch_urlopen(lambda req, timeout=0: FakeResponse(payload)):
            self.assertAlmostEqual(ts.get_balance("key"), 12.5)

    def test_missing_key_is_caught_before_the_network(self):
        with self.assertRaises(ts.TurnstileError) as ctx:
            ts.create_task("", {"type": "AntiTurnstileTask"})
        self.assertEqual(ctx.exception.code, "ERROR_KEY_DOES_NOT_EXIST")
        self.assertEqual(ctx.exception.http_status, 401)


class StatusTests(unittest.TestCase):
    def test_status_needs_no_key(self):
        payload = {"errorId": 0, "status": "ok"}
        with patch_urlopen(lambda req, timeout=0: FakeResponse(payload)):
            data = ts.get_status()
        self.assertEqual(data["status"], "ok")


class CliTests(unittest.TestCase):
    def test_discover_prints_sitekeys(self):
        html = '<div data-sitekey="0x4AAAAAAAabc"></div>'
        with mock.patch.object(ts, "read_page", return_value=html):
            with mock.patch("sys.stdout", new_callable=lambda: __import__("io").StringIO()) as out:
                code = ts.main(["discover", "--page", "https://example.com/"])
        self.assertEqual(code, 0)
        self.assertIn("0x4AAAAAAAabc", out.getvalue())

    def test_discover_without_keys_returns_2(self):
        with mock.patch.object(ts, "read_page", return_value="<html></html>"):
            with mock.patch("sys.stderr", new_callable=lambda: __import__("io").StringIO()):
                code = ts.main(["discover", "--page", "https://example.com/"])
        self.assertEqual(code, 2)

    def test_verify_prints_report(self):
        with mock.patch("sys.stdout", new_callable=lambda: __import__("io").StringIO()) as out:
            code = ts.main(["verify", "--token", "0.mF74dQpX2rC8vT1kLzB6hN3sYwA9eJgUiO5"])
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertTrue(data["plausible"])

    def test_verify_rejects_bad_token(self):
        with mock.patch("sys.stdout", new_callable=lambda: __import__("io").StringIO()) as out:
            code = ts.main(["verify", "--token", "bad"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out.getvalue())["plausible"])

    def test_missing_command_prints_help(self):
        with mock.patch("sys.stdout", new_callable=lambda: __import__("io").StringIO()) as out:
            code = ts.main([])
        self.assertEqual(code, 0)
        self.assertIn("usage", out.getvalue().lower())

    def test_balance_without_key_returns_2(self):
        env = {k: v for k, v in os.environ.items() if k != ts.ENV_API_KEY}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("sys.stderr", new_callable=lambda: __import__("io").StringIO()):
                code = ts.main(["--api-key", "", "balance"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
