#!/usr/bin/env python3
"""genie test suite — stdlib only, like genie itself.
Run:  python3 tests/run_tests.py
Spins up a local mock API server and simulates every real-world failure:
rate limits, daily quotas, bad keys, busy servers, dead ollama."""

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import genie  # noqa: E402

genie.time.sleep = lambda s: None  # no real waiting in tests

OK_JSON = json.dumps({"choices": [{"message": {"content":
    '{"type":"command","cmd":"df -h","explain":"shows disk usage","danger":0}'}}]})

HIT_COUNT = {}


class MockAPI(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        route = self.path.split("?")[0]
        HIT_COUNT[route] = HIT_COUNT.get(route, 0) + 1
        n = HIT_COUNT[route]

        def send(code, body, headers=None):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body.encode())

        if route == "/ok":
            send(200, OK_JSON)
        elif route == "/auth":
            send(401, json.dumps({"error": {"message": "Invalid API Key"}}))
        elif route == "/quota429":
            send(429, json.dumps({"error": {"message":
                "Rate limit exceeded: free-models-per-day"}}))
        elif route == "/flaky429":       # fails twice, then works
            if n < 3:
                send(429, json.dumps({"error": {"message": "slow down"}}),
                     {"Retry-After": "1"})
            else:
                send(200, OK_JSON)
        elif route == "/gemini429":      # rate limit with google-style retryDelay
            send(429, json.dumps({"error": {"message": "Resource exhausted",
                 "details": [{"retryDelay": "1s"}]}}))
        elif route == "/busy503":
            send(503, json.dumps({"error": {"message": "model is overloaded"}}))
        elif route == "/gone404":
            send(404, json.dumps({"error": {"message":
                "model llama-old has been decommissioned"}}))
        else:
            send(500, "{}")


def start_server():
    srv = HTTPServer(("127.0.0.1", 0), MockAPI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}"


BASE = start_server()


def pcfg(route, key="k"):
    return {"api_key": key, "model": "test-model", "api_base": BASE + route}


class TestErrorClassification(unittest.TestCase):
    def test_bad_key_is_auth(self):
        with self.assertRaises(genie.ProviderError) as cm:
            genie.call_ai("groq", pcfg("/auth"), [{"role": "user", "content": "hi"}])
        self.assertEqual(cm.exception.kind, "auth")
        self.assertIn("Invalid API Key", cm.exception.msg)   # real detail shown

    def test_daily_quota_not_retryable(self):
        with self.assertRaises(genie.ProviderError) as cm:
            genie.call_ai("openrouter", pcfg("/quota429"), [{"role": "user", "content": "hi"}])
        self.assertEqual(cm.exception.kind, "quota")
        self.assertFalse(cm.exception.retryable)

    def test_plain_ratelimit_retryable_with_wait(self):
        HIT_COUNT.clear()
        with self.assertRaises(genie.ProviderError) as cm:
            genie.call_ai("groq", pcfg("/flaky429"), [{"role": "user", "content": "hi"}])
        self.assertEqual(cm.exception.kind, "ratelimit")
        self.assertTrue(cm.exception.retryable)
        self.assertEqual(cm.exception.wait, 1.0)             # Retry-After honored

    def test_gemini_retrydelay_parsed(self):
        with self.assertRaises(genie.ProviderError) as cm:
            genie.call_ai("groq", pcfg("/gemini429"), [{"role": "user", "content": "hi"}])
        self.assertEqual(cm.exception.wait, 1.0)

    def test_503_is_retryable_server(self):
        with self.assertRaises(genie.ProviderError) as cm:
            genie.call_ai("groq", pcfg("/busy503"), [{"role": "user", "content": "hi"}])
        self.assertEqual(cm.exception.kind, "server")
        self.assertTrue(cm.exception.retryable)

    def test_dead_model_404(self):
        with self.assertRaises(genie.ProviderError) as cm:
            genie.call_ai("groq", pcfg("/gone404"), [{"role": "user", "content": "hi"}])
        self.assertEqual(cm.exception.kind, "model")

    def test_ollama_down_is_local_not_offline(self):
        cfg = {"model": "llama3.2", "api_base": "http://127.0.0.1:9/x"}  # dead port
        with self.assertRaises(genie.ProviderError) as cm:
            genie.call_ai("ollama", cfg, [{"role": "user", "content": "hi"}])
        self.assertEqual(cm.exception.kind, "local-down")
        self.assertIn("ollama isn't running", cm.exception.msg)
        self.assertNotIn("online", cm.exception.msg)          # the old lie is gone


class TestRetryAndFailover(unittest.TestCase):
    def test_retry_recovers_from_flaky_429(self):
        HIT_COUNT.clear()
        cfg = {"provider": "groq", "providers": {"groq": pcfg("/flaky429")}}
        raw = genie.ask_ai(cfg, [{"role": "user", "content": "hi"}])
        self.assertIn("df -h", raw)
        self.assertEqual(HIT_COUNT["/flaky429"], 3)           # 2 retries, then success

    def test_failover_to_next_provider(self):
        HIT_COUNT.clear()
        cfg = {"provider": "groq",
               "providers": {"groq": pcfg("/quota429"),       # dies instantly (quota)
                             "openrouter": pcfg("/ok")}}      # picks up the wish
        raw = genie.ask_ai(cfg, [{"role": "user", "content": "hi"}])
        self.assertIn("df -h", raw)
        self.assertEqual(HIT_COUNT["/quota429"], 1)           # quota = no pointless retries

    def test_all_fail_reports_each_reason(self):
        cfg = {"provider": "groq",
               "providers": {"groq": pcfg("/auth"),
                             "openrouter": pcfg("/quota429")}}
        with self.assertRaises(genie.AllProvidersFailed) as cm:
            genie.ask_ai(cfg, [{"role": "user", "content": "hi"}])
        kinds = {name: pe.kind for name, pe in cm.exception.failures}
        self.assertEqual(kinds, {"groq": "auth", "openrouter": "quota"})

    def test_old_single_provider_config_still_works(self):
        cfg = {"provider": "groq", "api_key": "old-key", "model": "m"}
        provs = genie.get_providers(cfg)
        self.assertEqual(provs[0][0], "groq")
        self.assertEqual(provs[0][1]["api_key"], "old-key")


class FakeWhich:
    """Pretend only certain executables exist."""
    def __init__(self, *names):
        self.names = set(names)

    def __call__(self, name):
        return f"/usr/bin/{name}" if name in self.names else None


class TestMultiDistro(unittest.TestCase):
    def setUp(self):
        self._which = genie.shutil.which

    def tearDown(self):
        genie.shutil.which = self._which

    def test_arch_with_paru(self):
        genie.shutil.which = FakeWhich("paru", "pacman", "systemctl")
        cmd, _, danger = genie.offline_match("install vlc", True)
        self.assertEqual(cmd, "paru -S vlc")
        self.assertEqual(genie.offline_match("update my whole system", True)[0], "paru -Syu")

    def test_debian(self):
        genie.shutil.which = FakeWhich("apt", "systemctl")
        self.assertEqual(genie.offline_match("install vlc", True)[0], "sudo apt install vlc")
        self.assertEqual(genie.offline_match("install firefox", True)[0],
                         "sudo apt install firefox-esr")
        self.assertEqual(genie.offline_match("update everything", True)[0],
                         "sudo apt update && sudo apt upgrade")

    def test_fedora(self):
        genie.shutil.which = FakeWhich("dnf", "systemctl")
        self.assertEqual(genie.offline_match("install blender", True)[0],
                         "sudo dnf install blender")
        self.assertEqual(genie.offline_match("update my system", True)[0],
                         "sudo dnf upgrade --refresh")

    def test_alpine_no_systemd(self):
        genie.shutil.which = FakeWhich("apk")
        self.assertEqual(genie.offline_match("install htop", True)[0], "sudo apk add htop")
        self.assertEqual(genie.offline_match("shutdown", True)[0], "sudo poweroff")

    def test_arch_only_app_falls_to_ai_elsewhere(self):
        genie.shutil.which = FakeWhich("apt")
        # teams-for-linux is an AUR package — on debian let the AI decide
        self.assertIsNone(genie.offline_match("install teams", True))
        # ...and with no AI, at least hand the user a search
        self.assertEqual(genie.offline_match("install teams", False)[0],
                         "apt search 'teams'")

    def test_unknown_pm_never_guesses(self):
        genie.shutil.which = FakeWhich()
        self.assertIsNone(genie.offline_match("install vlc", True))


class TestSafety(unittest.TestCase):
    def test_hard_blocks_survive(self):
        self.assertEqual(genie.danger_of("rm -rf /"), "block")
        self.assertEqual(genie.danger_of(": ( ) { :|:& };:".replace(" ", "")), "block")

    def test_new_pms_are_level1(self):
        for cmd in ("sudo apt install vlc", "sudo dnf remove vlc",
                    "sudo zypper install vlc", "sudo apk add vlc",
                    "sudo xbps-install -S vlc", "sudo emerge vlc"):
            self.assertEqual(genie.danger_of(cmd), 1, cmd)

    def test_search_stays_level0(self):
        self.assertEqual(genie.danger_of("apt search vlc"), 0)
        self.assertEqual(genie.danger_of("dnf search vlc"), 0)

    def test_rm_rf_still_level2(self):
        self.assertEqual(genie.danger_of("rm -rf ~/old"), 2)


class WinMode:
    """Context: pretend we're on Windows with winget available."""
    def __enter__(self):
        self._which, self._win = genie.shutil.which, genie.IS_WIN
        genie.IS_WIN = True
        genie.shutil.which = FakeWhich("winget", "clip")
        return self

    def __exit__(self, *a):
        genie.shutil.which, genie.IS_WIN = self._which, self._win


class TestWindows(unittest.TestCase):
    def test_winget_install_by_id(self):
        with WinMode():
            self.assertEqual(genie.offline_match("install teams for me", True)[0],
                             "winget install Microsoft.Teams")
            self.assertEqual(genie.offline_match("install vlc", True)[0],
                             "winget install VideoLAN.VLC")

    def test_linux_only_pkg_goes_to_ai(self):
        with WinMode():
            self.assertIsNone(genie.offline_match("install htop", True))
            self.assertEqual(genie.offline_match("install htop", False)[0],
                             'winget search "htop"')

    def test_everyday_speaks_powershell(self):
        with WinMode():
            self.assertEqual(genie.offline_match("how much disk space do i have", True)[0],
                             "Get-Volume")
            self.assertEqual(genie.offline_match("update my whole system", True)[0],
                             "winget upgrade --all")
            self.assertEqual(genie.offline_match("shutdown", True)[0], "shutdown /s /t 0")

    def test_delete_goes_to_recycle_bin(self):
        with WinMode():
            cmd, explain, danger = genie.offline_match("delete the folder old-homework", True)
            self.assertIn("SendToRecycleBin", cmd)
            self.assertEqual(danger, 1)

    def test_windows_catastrophes_blocked(self):
        with WinMode():
            for cmd in ("format C:", "diskpart",
                        "Remove-Item -Recurse -Force C:\\",
                        "rd /s /q C:\\",
                        "del /f /s /q C:\\*",
                        "vssadmin delete shadows",
                        "cipher /w C"):
                self.assertEqual(genie.danger_of(cmd), "block", cmd)

    def test_windows_levels(self):
        with WinMode():
            self.assertEqual(genie.danger_of("winget install Microsoft.Teams"), 1)
            self.assertEqual(genie.danger_of("Remove-Item -Recurse ~\\old-homework"), 2)
            self.assertEqual(genie.danger_of("Get-Volume"), 0)
            self.assertEqual(genie.danger_of("netsh wlan show networks"), 0)
            self.assertEqual(genie.danger_of("netsh advfirewall set allprofiles state off"), 1)
            # a normal file delete must NOT be blocked, just level 2
            self.assertEqual(genie.danger_of("Remove-Item -Recurse -Force C:\\Users\\a\\old"), 2)

    def test_linux_rules_untouched_by_win_mode(self):
        self.assertEqual(genie.danger_of("rm -rf /"), "block")
        self.assertEqual(genie.danger_of("winget install X"), 0)  # meaningless on linux

    def test_prompt_mentions_powershell(self):
        with WinMode():
            p = genie.system_prompt(genie.detect_pkg())
            self.assertIn("PowerShell", p)
            self.assertIn("winget", p)
            self.assertIn("Recycle Bin", p)


class TestParsing(unittest.TestCase):
    def test_fenced_json(self):
        raw = '```json\n{"type":"command","cmd":"ls","explain":"lists","danger":0}\n```'
        self.assertEqual(genie.parse_reply(raw)["cmd"], "ls")

    def test_prose_wrapped_json(self):
        raw = 'Sure! {"type":"command","cmd":"ls","explain":"lists","danger":0} Hope that helps.'
        self.assertEqual(genie.parse_reply(raw)["cmd"], "ls")


if __name__ == "__main__":
    unittest.main(verbosity=2)
