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


class TestExpandedOffline(unittest.TestCase):
    def setUp(self):
        self._which, self._win = genie.shutil.which, genie.IS_WIN
        genie.IS_WIN = False

    def tearDown(self):
        genie.shutil.which, genie.IS_WIN = self._which, self._win

    def test_package_diagnostics_across_linux_managers(self):
        managers = {
            'pacman': ('pacman -Q', 'pacman -Qu'),
            'paru': ('paru -Q', 'paru -Qu'), 'yay': ('yay -Q', 'yay -Qu'),
            'apt': ('apt list --installed', 'apt list --upgradable'),
            'dnf': ('dnf list --installed', 'dnf list --upgrades'),
            'dnf5': ('dnf5 list --installed', 'dnf5 list --upgrades'),
            'zypper': ('zypper search --installed-only', 'zypper list-updates'),
            'apk': ('apk info', "apk version -l '<'"),
            'xbps-install': ('xbps-query -l', 'xbps-install -un'),
            'emerge': ('qlist -I', 'emerge --pretend --update --deep --newuse @world'),
        }
        for manager, expected in managers.items():
            genie.shutil.which = FakeWhich(manager, 'qlist')
            for wish, cmd in zip(('list installed packages', 'check for updates'), expected):
                with self.subTest(manager=manager, wish=wish):
                    hit = genie.offline_match(wish, False)
                    self.assertEqual(hit[0], cmd)
                    self.assertEqual(hit[2], 0)

    def test_shared_wishes_across_linux_families(self):
        expected = {'uptime': 'uptime', 'show cpu info': 'cat /proc/cpuinfo',
                    'show routes': 'ip route show', 'listening ports': 'ss -lnt',
                    'who am i': 'whoami', 'git status': 'git status --short --branch',
                    'create folder Project Notes': "mkdir -p 'Project Notes'",
                    'read file README.md': 'cat README.md'}
        for manager in ('pacman', 'apt', 'dnf5', 'zypper', 'apk', 'xbps-install', 'emerge'):
            genie.shutil.which = FakeWhich(manager, 'uptime', 'cat', 'ip', 'ss', 'whoami', 'git')
            for wish, cmd in expected.items():
                with self.subTest(manager=manager, wish=wish):
                    self.assertEqual(genie.offline_match(wish, False)[0], cmd)

    def test_windows_commands(self):
        with WinMode():
            expected = {'list installed apps': 'winget list',
                        'check for updates': 'winget list --upgrade-available',
                        'show routes': 'Get-NetRoute', 'show hidden files': 'Get-ChildItem -Force',
                        'create folder Project Notes': "New-Item -ItemType Directory -Path 'Project Notes'",
                        'read file ReadMe.txt': "Get-Content -LiteralPath 'ReadMe.txt'",
                        'sha256 file ReadMe.txt': "Get-FileHash -Algorithm SHA256 -LiteralPath 'ReadMe.txt'",
                        'status of service Spooler': "Get-Service -Name 'Spooler'",
                        'restart service Spooler': "Restart-Service -Name 'Spooler'",
                        'wsl distros': 'wsl --list --verbose'}
            for wish, cmd in expected.items():
                with self.subTest(wish=wish):
                    self.assertEqual(genie.offline_match(wish, False)[0], cmd)

    def test_windows_fallback_managers(self):
        genie.IS_WIN = True
        for manager in ('choco', 'scoop'):
            genie.shutil.which = FakeWhich(manager)
            with self.subTest(manager=manager):
                self.assertEqual(genie.offline_match('install vlc', False)[0], f'{manager} install vlc')
                self.assertNotIn('Microsoft.', genie.offline_match('install teams', False)[0])
                self.assertIn('search', genie.offline_match('install teams', False)[0])

    def test_service_managers(self):
        for tool, expected in (
                ('systemctl', "sudo systemctl restart sshd"),
                ('rc-service', 'sudo rc-service sshd restart'),
                ('sv', 'sudo sv restart /var/service/sshd')):
            genie.shutil.which = FakeWhich(tool)
            with self.subTest(tool=tool):
                hit = genie.offline_match('restart service sshd', False)
                self.assertEqual(hit[0], expected)
                self.assertEqual(hit[2], 1)

    def test_minimal_machine_reports_missing_tools(self):
        genie.shutil.which = FakeWhich('apk', 'ps')
        for wish in ('listening ports', 'git status', 'docker containers', 'wifi status'):
            with self.subTest(wish=wish):
                self.assertIn('not installed', genie.offline_match(wish, False)[0])
        self.assertEqual(genie.offline_match('cpu usage', False)[0], 'ps')
        self.assertIn('No supported', genie.offline_match('restart service sshd', False)[0])

    def test_windows_missing_optional_tools(self):
        with WinMode():
            self.assertIn('not installed', genie.offline_match('docker containers', False)[0])
            self.assertIsNone(genie.offline_match('flatpak apps', False))

    def test_paths_keep_case_and_are_literal(self):
        genie.shutil.which = FakeWhich('gio')
        self.assertEqual(genie.offline_match('trash file MyNotes.TXT', False)[0], 'gio trash -- MyNotes.TXT')
        self.assertEqual(genie.offline_match('read file -n', False)[0], 'cat ./-n')
        self.assertEqual(genie.offline_match('find files -Notes*', False)[0], "find . -type f -name '-Notes*'")
        self.assertEqual(genie.offline_match('find files *?', False)[0], "find . -type f -name '*?'")
        self.assertIn("'Mixed Case'", genie.offline_match('create folder Mixed Case', False)[0])
        with WinMode():
            cmd = genie.offline_match("read file O'Brien.txt", False)[0]
            self.assertEqual(cmd, "Get-Content -LiteralPath 'O''Brien.txt'")

    def test_shell_arguments_cannot_inject_commands(self):
        import tempfile
        import pathlib
        import subprocess
        with tempfile.TemporaryDirectory() as root:
            # Real shell execution: malicious-looking filename must be printed
            # literally; neither the substitution nor the semicolon may execute.
            marker = pathlib.Path(root) / 'PWNED'
            filename = "ReadMe'; touch PWNED; echo '$(touch PWNED)"
            pathlib.Path(root, filename).write_text('literal content')
            cmd = genie.offline_match('read file ' + filename, False)[0]
            result = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'literal content')
            self.assertFalse(marker.exists())

    def test_search_terms_are_shell_data(self):
        import shlex
        genie.shutil.which = FakeWhich('apt')
        cmd = genie.offline_match("search for package x'; touch PWNED; echo '", False)[0]
        self.assertEqual(shlex.split(cmd), ['apt', 'search', "x'; touch pwned; echo '"])
        with WinMode():
            cmd = genie.offline_match('search for package $(Start-Process calc)', False)[0]
            self.assertIn("'$(start-process calc)'", cmd)

    def test_parameterized_read_only_commands_execute(self):
        import tempfile
        import pathlib
        import subprocess
        import hashlib
        # Use real executables for this integration check.
        genie.shutil.which = self._which
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / 'Case Sensitive.txt'
            path.write_text('genie\n')
            wishes = ['read file ' + str(path), 'sha256 file ' + str(path),
                      'file info ' + str(path), 'find files *.txt', 'size of ' + str(path)]
            for wish in wishes:
                cmd = genie.offline_match(wish, False)[0]
                result = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, (wish, result.stderr))
                if wish.startswith('sha256'):
                    self.assertIn(hashlib.sha256(b'genie\n').hexdigest(), result.stdout)
                elif wish.startswith('read'):
                    self.assertEqual(result.stdout, 'genie\n')
                elif wish.startswith('find'):
                    self.assertIn('Case Sensitive.txt', result.stdout)

    def test_dnf5_and_tumbleweed(self):
        from unittest.mock import patch
        genie.shutil.which = FakeWhich('dnf', 'dnf5')
        self.assertEqual(genie.detect_pkg()['name'], 'dnf5')
        self.assertEqual(genie.offline_match('update my system', False)[0], 'sudo dnf5 upgrade --refresh')
        genie.shutil.which = FakeWhich('zypper')
        with patch.object(genie, 'distro_name', return_value='openSUSE Tumbleweed'):
            self.assertEqual(genie.offline_match('update my system', False)[0], 'sudo zypper dup')
        with patch.object(genie, 'distro_name', return_value='openSUSE Leap'):
            self.assertEqual(genie.offline_match('update my system', False)[0], 'sudo zypper update')

    def test_new_actions_keep_confirmation_levels(self):
        genie.shutil.which = FakeWhich('systemctl')
        for wish in ('create folder Notes', 'start service sshd', 'enable service sshd', 'disable service sshd'):
            with self.subTest(wish=wish):
                hit = genie.offline_match(wish, False)
                self.assertGreaterEqual(genie.danger_of(hit[0], hit[2]), 1)
        self.assertEqual(genie.danger_of('dnf5 install vlc'), 1)

    def test_public_ip_is_not_confused_with_local_ip(self):
        genie.shutil.which = FakeWhich('curl')
        self.assertIn('https://api.ipify.org', genie.offline_match('public ip', False)[0])
        with WinMode():
            self.assertIn('https://api.ipify.org', genie.offline_match('my public ip', False)[0])

    def test_pacman_does_not_install_aur_only_aliases(self):
        genie.shutil.which = FakeWhich('pacman')
        self.assertIsNone(genie.offline_match('install brave', True))
        self.assertIn('search', genie.offline_match('install brave', False)[1])

    def test_read_only_service_queries_do_not_warn_about_changes(self):
        genie.shutil.which = FakeWhich('systemctl')
        hit = genie.offline_match('status of service sshd', False)
        self.assertEqual(genie.danger_of(hit[0], hit[2]), 0)
        with WinMode():
            self.assertEqual(genie.danger_of("Restart-Service -Name 'Spooler'"), 1)

    def test_unsupported_compound_requests_are_not_partially_executed(self):
        for wish in ('restart service sshd; reboot', 'ping example.com; reboot', 'uptime and reboot'):
            self.assertIsNone(genie.offline_match(wish, True), wish)


if __name__ == "__main__":
    unittest.main(verbosity=2)
