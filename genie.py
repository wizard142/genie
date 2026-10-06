#!/usr/bin/env python3
"""
genie — speak English to your terminal.

Type  /genie <anything in plain English>  and genie shows you the real
command, explains what it does, and runs it when you say yes.

Born on CachyOS (Arch Linux), now at home on any Linux distribution.
Zero dependencies — Python standard library only.

MIT License.
"""

import json
import os
import platform
import re
import shutil
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

VERSION = "1.2.0"

IS_WIN = os.name == "nt"
# how the user summons genie: /genie on Linux (a real path at the filesystem
# root), plain `genie` on Windows (no filesystem root to hang a /genie on)
CALL = "genie" if IS_WIN else "/genie"

if IS_WIN:
    os.system("")  # flips the classic console into ANSI escape-code mode

if IS_WIN:
    CONFIG_DIR = os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "genie")
else:
    CONFIG_DIR = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "genie")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
HISTORY_PATH = os.path.join(CONFIG_DIR, "history.jsonl")

# --------------------------------------------------------------------------
# colors
# --------------------------------------------------------------------------

USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code):
    def wrap(text):
        return f"\033[{code}m{text}\033[0m" if USE_COLOR else str(text)
    return wrap


BOLD = _c("1")
DIM = _c("2")
CYAN = _c("96")
MAGENTA = _c("95")
GREEN = _c("92")
YELLOW = _c("93")
RED = _c("91")

LAMP = "\U0001F9DE"  # genie emoji


# --------------------------------------------------------------------------
# AI providers (all called with plain urllib — no packages needed)
# --------------------------------------------------------------------------

PROVIDERS = {
    "groq": {
        "base": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile",
        "style": "openai",
        "needs_key": True,
        "note": "free tier, fast — easiest way to start",
        "key_url": "https://console.groq.com/keys",
    },
    "anthropic": {
        "base": "https://api.anthropic.com/v1/messages",
        "model": "claude-haiku-4-5",
        "style": "anthropic",
        "needs_key": True,
        "note": "best quality answers",
        "key_url": "https://console.anthropic.com/",
    },
    "gemini": {
        "base": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "model": "gemini-flash-latest",
        "style": "gemini",
        "needs_key": True,
        "note": "free tier from Google",
        "key_url": "https://aistudio.google.com/apikey",
    },
    "openrouter": {
        "base": "https://openrouter.ai/api/v1/chat/completions",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "style": "openai",
        "needs_key": True,
        "note": "many free models in one place",
        "key_url": "https://openrouter.ai/keys",
    },
    "ollama": {
        "base": "http://localhost:11434/v1/chat/completions",
        "model": "llama3.2",
        "style": "openai",
        "needs_key": False,
        "note": "100% local and free (needs ollama installed)",
        "key_url": "https://ollama.com",
    },
}


# --------------------------------------------------------------------------
# distro / package-manager detection — genie works on any Linux
# --------------------------------------------------------------------------

def distro_name():
    if IS_WIN:
        return f"Windows {platform.release()}"
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "Linux"


def detect_pkg():
    """Figure out how packages are installed on THIS machine.
    Returns a dict of command templates ({pkg} and {term} placeholders)."""
    if IS_WIN:
        if shutil.which("winget"):
            return {"family": "windows", "name": "winget", "aur": False,
                    "install": "winget install {pkg}",
                    "remove": "winget uninstall {pkg}",
                    "update": "winget upgrade --all",
                    "search": 'winget search "{term}"', "clean": None}
        for exe, spec in (("choco", {"family": "windows", "name": "choco", "aur": False,
                                     "install": "choco install {pkg}",
                                     "remove": "choco uninstall {pkg}",
                                     "update": "choco upgrade all",
                                     "search": 'choco search "{term}"', "clean": None}),
                          ("scoop", {"family": "windows", "name": "scoop", "aur": False,
                                     "install": "scoop install {pkg}",
                                     "remove": "scoop uninstall {pkg}",
                                     "update": "scoop update *",
                                     "search": 'scoop search "{term}"', "clean": None})):
            if shutil.which(exe):
                return spec
        return {"family": "windows", "name": None, "aur": False}
    for h in ("paru", "yay"):                                   # Arch + AUR helper
        if shutil.which(h):
            return {"family": "arch", "name": h, "aur": True,
                    "install": h + " -S {pkg}", "remove": h + " -Rns {pkg}",
                    "update": h + " -Syu", "search": h + " -Ss '{term}'",
                    "clean": h + " -Sc"}
    table = [
        ("pacman", {"family": "arch", "name": "pacman", "aur": False,
                    "install": "sudo pacman -S {pkg}", "remove": "sudo pacman -Rns {pkg}",
                    "update": "sudo pacman -Syu", "search": "pacman -Ss '{term}'",
                    "clean": "sudo pacman -Sc"}),
        ("apt", {"family": "debian", "name": "apt", "aur": False,
                 "install": "sudo apt install {pkg}", "remove": "sudo apt remove {pkg}",
                 "update": "sudo apt update && sudo apt upgrade",
                 "search": "apt search '{term}'", "clean": "sudo apt clean"}),
        ("dnf5", {"family": "fedora", "name": "dnf5", "aur": False,
                  "install": "sudo dnf5 install {pkg}", "remove": "sudo dnf5 remove {pkg}",
                  "update": "sudo dnf5 upgrade --refresh", "search": "dnf5 search {term}",
                  "clean": "sudo dnf5 clean packages"}),
        ("dnf", {"family": "fedora", "name": "dnf", "aur": False,
                 "install": "sudo dnf install {pkg}", "remove": "sudo dnf remove {pkg}",
                 "update": "sudo dnf upgrade --refresh",
                 "search": "dnf search '{term}'", "clean": "sudo dnf autoremove"}),
        ("zypper", {"family": "suse", "name": "zypper", "aur": False,
                    "install": "sudo zypper install {pkg}", "remove": "sudo zypper remove {pkg}",
                    "update": "sudo zypper update",
                    "search": "zypper search '{term}'", "clean": "sudo zypper clean"}),
        ("apk", {"family": "alpine", "name": "apk", "aur": False,
                 "install": "sudo apk add {pkg}", "remove": "sudo apk del {pkg}",
                 "update": "sudo apk upgrade --update-cache",
                 "search": "apk search '{term}'", "clean": "sudo apk cache clean"}),
        ("xbps-install", {"family": "void", "name": "xbps", "aur": False,
                          "install": "sudo xbps-install -S {pkg}",
                          "remove": "sudo xbps-remove -R {pkg}",
                          "update": "sudo xbps-install -Su",
                          "search": "xbps-query -Rs '{term}'",
                          "clean": "sudo xbps-remove -O"}),
        ("emerge", {"family": "gentoo", "name": "emerge", "aur": False,
                    "install": "sudo emerge {pkg}",
                    "remove": "sudo emerge --deselect {pkg} && sudo emerge --depclean",
                    "update": "sudo emerge --sync && sudo emerge -uDN @world",
                    "search": "emerge --search '{term}'", "clean": "sudo eclean distfiles"}),
    ]
    for exe, spec in table:
        if shutil.which(exe):
            if exe == "zypper" and "tumbleweed" in distro_name().lower():
                spec = dict(spec, update="sudo zypper dup")
            return spec
    return {"family": "unknown", "name": None, "aur": False}


def system_prompt(pkg):
    cwd = os.getcwd()
    if pkg["name"]:
        pkg_line = (
            f"package manager = `{pkg['name']}`"
            + (" (official repos + the AUR)" if pkg.get("aur") else "")
            + f". Install: `{pkg['install'].format(pkg='<package>')}` · "
            f"remove: `{pkg['remove'].format(pkg='<package>')}` · "
            f"update: `{pkg['update']}` · "
            f"search: `{pkg['search'].format(term='<term>')}`"
        )
    else:
        pkg_line = "package manager = unknown (ask the user before installing anything)"

    if IS_WIN:
        lang = "PowerShell"
        env_line = f"Environment: {pkg_line}. Current directory = {cwd}."
        trash_rule = ("- To delete files/folders send them to the Recycle Bin "
                      "(Microsoft.VisualBasic FileSystem SendToRecycleBin), never plain "
                      "Remove-Item, so the user can undo it.")
        admin_rule = "- Don't require an elevated (admin) shell unless the command truly needs it."
        never_rule = ("- Never output format, diskpart, Remove-Item on a drive root, "
                      "vssadmin delete shadows, cipher /w, reg delete on HKLM, or anything similar.")
        newbie = "Windows terminal beginner"
    else:
        lang = "bash"
        shell = os.environ.get("SHELL", "/bin/bash")
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "unknown")
        env_line = (f"Environment: {pkg_line}.\n"
                    f"User shell = {shell}, desktop = {desktop}, current directory = {cwd}.")
        trash_rule = "- Prefer commands that are safe to undo. To delete files prefer `gio trash`."
        admin_rule = "- No sudo unless the command truly needs it."
        never_rule = "- Never output rm -rf /, fork bombs, dd to disks, mkfs, or anything similar."
        newbie = "Linux beginner"

    return (
        f"You translate plain English into ONE safe {lang} command for {distro_name()}.\n"
        f"{env_line}\n\n"
        "Reply with ONLY minified JSON in exactly one of these two shapes:\n"
        '{"type":"command","cmd":"<one-line ' + lang + ' command>","explain":"<one short, '
        'beginner-friendly sentence saying what it does>","danger":0}\n'
        '{"type":"question","ask":"<one short clarifying question>"}\n\n'
        "danger levels: 0 = read-only / harmless, 1 = changes the system "
        "(installs, moves, edits, settings), 2 = destructive or hard to undo.\n\n"
        "Rules:\n"
        "- Use ONLY the package-manager commands shown above for installs/removals/updates.\n"
        "- NEVER guess a package name. If unsure of the exact name, output the search "
        "command instead so the user can pick.\n"
        f"{trash_rule}\n"
        f"{admin_rule}\n"
        f"{never_rule}\n"
        "- If the request is vague or risky, reply with a question instead of guessing.\n"
        f"- The user is a {newbie}: keep `explain` simple, no jargon."
    )


def http_post_json(url, headers, payload, timeout=45):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    # some API gateways reject Python's default User-Agent — always send our own
    req.add_header("User-Agent", f"genie/{VERSION}")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class ProviderError(Exception):
    """One provider failed, in a way genie understands.
    kind: auth | model | ratelimit | quota | server | local-down | unreachable | weird
    wait: seconds the provider asked us to wait before retrying (429s)."""

    def __init__(self, kind, msg, wait=None):
        self.kind = kind
        self.msg = msg
        self.wait = wait
        super().__init__(msg)

    @property
    def retryable(self):
        return self.kind in ("ratelimit", "server")


def _err_detail(body):
    """Pull the human-readable message out of a provider's error body."""
    try:
        data = json.loads(body)
        err = data.get("error") or {}
        if isinstance(err, str):
            return err[:160]
        detail = err.get("message") or ""
        if detail:
            return str(detail)[:160]
    except (ValueError, AttributeError, TypeError):
        pass
    return re.sub(r"\s+", " ", (body or ""))[:160].strip()


def _classify_http(e, name, model, local):
    """Turn an HTTPError into a ProviderError with a truthful message."""
    body = ""
    try:
        body = e.read().decode("utf-8", "replace")[:800]
    except OSError:
        pass
    detail = _err_detail(body)
    low = body.lower()

    if e.code in (401, 403):
        return ProviderError("auth", f"key rejected — {detail or 'check you pasted the whole key'}")
    if e.code == 404 and local:
        return ProviderError("model",
                             f"model '{model}' isn't downloaded — run: ollama pull {model}")
    if e.code == 404 or ("model" in low and ("not found" in low or "no longer" in low
                                            or "not available" in low or "decommission" in low)):
        return ProviderError("model", f"model '{model}' unavailable — {detail}")
    if e.code == 429:
        # how long does the provider want us to wait?
        wait = None
        ra = e.headers.get("Retry-After") if e.headers else None
        if ra and str(ra).isdigit():
            wait = float(ra)
        m = re.search(r'"retrydelay"\s*:\s*"(\d+(?:\.\d+)?)s"', low)
        if m:
            wait = float(m.group(1))
        # daily/billing quotas won't clear in seconds — don't bother retrying
        if any(w in low for w in ("quota", "billing", "per-day", "per day", "credits")):
            return ProviderError("quota", f"free-tier quota used up — {detail}")
        return ProviderError("ratelimit", f"rate limited — {detail}", wait=wait)
    if e.code in (500, 502, 503, 529) or "overloaded" in low or "busy" in low:
        return ProviderError("server", f"service busy ({e.code}) — {detail}")
    return ProviderError("weird", f"HTTP {e.code} — {detail}")


def call_ai(name, pcfg, messages, timeout=45):
    """One attempt against one provider. Raises ProviderError on any failure.
    messages: list of {"role": "user"|"assistant", "content": str}"""
    provider = PROVIDERS[name]
    base = os.environ.get("GENIE_API_BASE") or pcfg.get("api_base") or provider["base"]
    model = pcfg.get("model") or provider["model"]
    key = pcfg.get("api_key", "")
    local = "localhost" in base or "127.0.0.1" in base
    sysmsg = system_prompt(detect_pkg())
    style = provider["style"]

    try:
        return _call_ai_raw(style, base, model, key, sysmsg, messages, timeout)
    except ProviderError:
        raise
    except urllib.error.HTTPError as e:
        raise _classify_http(e, name, model, local) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        if local:
            hint = ("open the Ollama app" if IS_WIN else
                    "start it with `ollama serve`" if shutil.which("ollama") else
                    "it isn't installed — get it at https://ollama.com/download")
            raise ProviderError("local-down",
                                f"ollama isn't running — {hint}") from None
        reason = getattr(e, "reason", e)
        raise ProviderError("unreachable",
                            f"can't reach {name} — check your internet ({reason})") from None
    except (KeyError, IndexError, ValueError) as e:
        raise ProviderError("weird", f"unexpected reply shape ({e})") from None


def _call_ai_raw(style, base, model, key, sysmsg, messages, timeout):

    if style == "openai":
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": sysmsg}]
            + [{"role": m["role"], "content": m["content"]} for m in messages],
            "temperature": 0,
            "max_tokens": 800,
        }
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        out = http_post_json(base, headers, payload, timeout)
        return out["choices"][0]["message"]["content"]

    if style == "anthropic":
        payload = {
            "model": model,
            "max_tokens": 800,
            "system": sysmsg,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        }
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        out = http_post_json(base, headers, payload, timeout)
        return out["content"][0]["text"]

    if style == "gemini":
        url = base.format(model=model) + f"?key={key}"
        contents = [
            {"role": "user" if m["role"] == "user" else "model",
             "parts": [{"text": m["content"]}]}
            for m in messages
        ]
        payload = {
            "system_instruction": {"parts": [{"text": sysmsg}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 2048,
                # turn OFF "thinking" — this is a quick structured task, not a
                # reasoning problem. Thinking made flash models slow and often
                # ran out of tokens before writing the answer.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        out = http_post_json(url, {}, payload, timeout)
        cand = (out.get("candidates") or [{}])[0]
        parts = cand.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if "text" in p)
        if not text.strip():
            reason = cand.get("finishReason", "unknown")
            # empty replies from Gemini are transient — mark retryable
            raise ProviderError("server", f"empty reply (finishReason={reason})")
        return text

    raise ProviderError("weird", f"unknown provider style: {style}")


# --------------------------------------------------------------------------
# retry + failover — the difference between "flaky free tier" and "it works"
# --------------------------------------------------------------------------

MAX_RETRIES = 2        # extra attempts per provider on retryable errors
MAX_WAIT = 8           # never sit around longer than this per retry (seconds)


class AllProvidersFailed(Exception):
    def __init__(self, failures):
        self.failures = failures      # list of (provider_name, ProviderError)
        super().__init__("all providers failed")


def get_providers(cfg):
    """All configured providers, primary first.
    Understands both the new {"providers": {...}} layout and the old
    single-provider config (migrated transparently)."""
    provs = dict(cfg.get("providers") or {})
    primary = cfg.get("provider")
    if primary and primary not in provs and primary in PROVIDERS:
        old = {}
        if cfg.get("api_key"):
            old["api_key"] = cfg["api_key"]
        if cfg.get("model"):
            old["model"] = cfg["model"]
        provs[primary] = old
    ordered = [(n, provs[n]) for n in provs if n == primary and n in PROVIDERS]
    ordered += [(n, provs[n]) for n in provs if n != primary and n in PROVIDERS]
    return ordered


def ask_ai(cfg, messages):
    """Ask the primary provider; retry briefly when it's busy; fail over to the
    other configured providers before ever bothering the user with an error."""
    order = get_providers(cfg)
    failures = []
    for pos, (name, pcfg) in enumerate(order):
        attempt = 0
        while True:
            try:
                return call_ai(name, pcfg, messages)
            except ProviderError as pe:
                wait = pe.wait if pe.wait is not None else 2.0 * (attempt + 1)
                if pe.retryable and attempt < MAX_RETRIES and wait <= MAX_WAIT:
                    attempt += 1
                    print(DIM(f"  {name} is busy — retrying in {int(wait)}s..."), flush=True)
                    time.sleep(wait)
                    continue
                failures.append((name, pe))
                if pos + 1 < len(order):
                    print(DIM(f"  {name}: {pe.kind} — switching to {order[pos + 1][0]}..."),
                          flush=True)
                break
    raise AllProvidersFailed(failures)


def parse_reply(raw):
    """Model must return JSON — tolerate code fences and stray prose around it."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if data.get("type") == "command" and data.get("cmd"):
        data.setdefault("explain", "runs the command shown above")
        data["danger"] = int(data.get("danger", 1) or 0)
        return data
    if data.get("type") == "question" and data.get("ask"):
        return data
    return None


# --------------------------------------------------------------------------
# offline fallback — common tasks work with no API key and no internet
# --------------------------------------------------------------------------

# app name → package name. A plain string works on every distro family;
# a dict maps family → package ("*" = everyone else, missing = let the AI decide,
# since the package needs an extra repo or a different name there).
APP_ALIASES = {
    "teams": {"arch": "teams-for-linux", "windows": "Microsoft.Teams"},
    "microsoft teams": {"arch": "teams-for-linux", "windows": "Microsoft.Teams"},
    "chrome": {"arch": "google-chrome", "windows": "Google.Chrome"},
    "google chrome": {"arch": "google-chrome", "windows": "Google.Chrome"},
    "vscode": {"arch": "visual-studio-code-bin", "windows": "Microsoft.VisualStudioCode"},
    "vs code": {"arch": "visual-studio-code-bin", "windows": "Microsoft.VisualStudioCode"},
    "visual studio code": {"arch": "visual-studio-code-bin",
                           "windows": "Microsoft.VisualStudioCode"},
    "spotify": {"arch": "spotify", "windows": "Spotify.Spotify"},
    "discord": {"arch": "discord", "fedora": "discord", "windows": "Discord.Discord"},
    "steam": {"arch": "steam", "windows": "Valve.Steam"},
    "vlc": {"windows": "VideoLAN.VLC", "*": "vlc"},
    "gimp": {"windows": "GIMP.GIMP", "*": "gimp"},
    "firefox": {"debian": "firefox-esr", "windows": "Mozilla.Firefox", "*": "firefox"},
    "brave": {"arch": "brave-bin", "windows": "Brave.Brave"},
    "telegram": {"windows": "Telegram.TelegramDesktop", "*": "telegram-desktop"},
    "whatsapp": {"arch": "zapzap"},
    "zoom": {"arch": "zoom", "windows": "Zoom.Zoom"},
    "obs": {"arch": "obs-studio", "debian": "obs-studio", "suse": "obs-studio",
            "windows": "OBSProject.OBSStudio"},
    "docker": {"arch": "docker", "debian": "docker.io", "alpine": "docker",
               "windows": "Docker.DockerDesktop"},
    "git": {"windows": "Git.Git", "*": "git"},
    "htop": "htop",
    "btop": "btop",
    "libreoffice": {"arch": "libreoffice-fresh",
                    "windows": "TheDocumentFoundation.LibreOffice", "*": "libreoffice"},
    "node": {"arch": "nodejs npm", "debian": "nodejs npm",
             "windows": "OpenJS.NodeJS", "*": "nodejs"},
    "nodejs": {"arch": "nodejs npm", "debian": "nodejs npm",
               "windows": "OpenJS.NodeJS", "*": "nodejs"},
    "krita": {"windows": "KDE.Krita", "*": "krita"},
    "blender": {"windows": "BlenderFoundation.Blender", "*": "blender"},
}


def alias_pkg(app, family):
    v = APP_ALIASES.get(app)
    if family == "windows":
        # winget IDs must be explicit — Linux package names don't transfer
        return v.get("windows") if isinstance(v, dict) else None
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get(family) or v.get("*")
    return None


def _clean(text):
    t = re.sub(r"\s+", " ", text.strip().lower()).rstrip("?.! ")
    t = re.sub(r"^(please |pls |can you |could you |hey |yo )+", "", t)
    t = re.sub(r"( for me| please| pls| right now| now)+$", "", t)
    return t


def _app_name(raw):
    a = re.sub(r"^(the |an |a )", "", raw.strip())
    a = re.sub(r"( app| application| for linux| browser)$", "", a)
    return a.strip()


# The parser treats user arguments as data, never as shell syntax. New rules
# match complete requests, so unrelated/compound wishes still go to the AI.
def _clean_preserving_case(text):
    t = text.strip()
    t = re.sub(r"^(please |pls |can you |could you |hey |yo )+", "", t, flags=re.I)
    return re.sub(r"( for me| please| pls| right now| now)+$", "", t, flags=re.I)


def _quote(value):
    return "'" + value.replace("'", "''") + "'" if IS_WIN else shlex.quote(value)


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _path(value):
    value = _unquote(value)
    if not IS_WIN:
        value = os.path.expanduser(value)
        if value.startswith('-'):
            value = './' + value
    return value


def _quote_path(value):
    return _quote(_path(value))


def _tool_command(tool, cmd):
    if shutil.which(tool):
        return cmd
    # Keep a recognized wish offline on minimal installations. Never silently
    # install prerequisites or emit a command that will fail mysteriously.
    return 'echo ' + _quote(f"{tool} is not installed; install it to use this wish.")


def _manager_alias(app, pkg):
    if IS_WIN and pkg['name'] != 'winget':
        # WinGet publisher IDs are not Chocolatey/Scoop package names.
        names = {'git': 'git', 'vlc': 'vlc', 'firefox': 'firefox',
                 '7zip': '7zip', 'python': 'python', 'node': 'nodejs',
                 'nodejs': 'nodejs'}
        return names.get(app)
    value = alias_pkg(app, pkg['family'])
    if pkg['family'] == 'arch' and not pkg['aur'] and value in ('google-chrome', 'teams-for-linux', 'visual-studio-code-bin', 'spotify', 'brave-bin', 'zapzap', 'zoom'):
        return None  # These aliases require an AUR helper.
    return value


def _package_search(pkg, term):
    # Existing templates contain quotes: replace the complete quoted slot.
    if re.fullmatch(r'[a-zA-Z0-9_. -]+', term):
        return pkg['search'].format(term=term)
    template = pkg['search'].replace("'{term}'", '{term}').replace('"{term}"', '{term}')
    return template.format(term=_quote(term))


# phrase alternatives, Linux command, PowerShell command, explanation, Linux
# prerequisite. These requests are read-only; availability varies by machine.
OFFLINE_INFO = [
    ('uptime|how long has (?:my |the )?(?:pc|computer|system) been running', 'uptime',
     "(Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime", 'shows time since the last boot', 'uptime'),
    ('hostname|(?:show |what is )?(?:my |the )?computer name', 'hostname', '$env:COMPUTERNAME', 'shows this computer’s name', 'hostname'),
    ('(?:show |what is )?(?:my |the )?kernel version', 'uname -r', '[System.Environment]::OSVersion.Version', 'shows the OS kernel version', 'uname'),
    ('(?:show |what is )?(?:my |the )?(?:os|operating system) version', 'cat /etc/os-release',
     'Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber', 'shows the installed operating system', 'cat'),
    ('(?:show |list )?(?:my )?cpu(?: info| information| model)?', 'cat /proc/cpuinfo',
     'Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors', 'shows processor details', 'cat'),
    ('(?:show |list )?(?:my )?(?:disks|drives|partitions)', 'lsblk',
     'Get-Disk | Select-Object Number, FriendlyName, Size, OperationalStatus', 'lists physical disks and partitions', 'lsblk'),
    ('(?:show |list )?(?:my )?usb devices', 'lsusb', 'Get-PnpDevice -PresentOnly | Where-Object InstanceId -Like \'USB*\'', 'lists USB devices', 'lsusb'),
    ('(?:show |list )?(?:my )?(?:gpu|graphics card)(?: info)?', 'lspci',
     'Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion', 'shows graphics hardware (Linux lists all PCI devices)', 'lspci'),
    ('(?:show |list )?(?:my )?environment variables', 'printenv', 'Get-ChildItem Env:', 'shows environment variables; output may contain secrets', 'printenv'),
    ('who am i|current user|(?:show )?my username', 'whoami', 'whoami', 'shows your current username', 'whoami'),
    ('(?:show |list )?(?:my )?groups', 'id', 'whoami /groups', 'shows your user and group membership', 'id'),
    ('(?:show |list )?(?:logged in users|logins)', 'who', 'quser', 'shows logged-in user sessions', 'who'),
    ('(?:show |list )?(?:network adapters|network interfaces)', 'ip link show', 'Get-NetAdapter', 'lists network adapters', 'ip'),
    ('(?:show |list )?(?:routes|routing table)', 'ip route show', 'Get-NetRoute', 'shows network routes', 'ip'),
    ('(?:show |list )?(?:dns servers|dns settings)', 'cat /etc/resolv.conf', 'Get-DnsClientServerAddress', 'shows DNS resolver configuration', 'cat'),
    ('(?:show |list )?(?:listening ports|open ports)', 'ss -lnt',
     'Get-NetTCPConnection -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess', 'shows listening TCP ports', 'ss'),
    ('(?:show |list )?(?:network connections|tcp connections)', 'ss -nt', 'Get-NetTCPConnection', 'shows TCP connections', 'ss'),
    ('(?:show |list )?(?:arp table|neighbors|neighbours)', 'ip neigh show', 'Get-NetNeighbor', 'shows neighboring network devices', 'ip'),
    ('(?:show |list )?(?:hidden files)', 'ls -la', 'Get-ChildItem -Force', 'lists files including hidden entries', 'ls'),
    ('(?:show |list )?(?:services|running services)', None, 'Get-Service', 'lists services', None),
    ('(?:show |list )?(?:failed services)', None, "Get-Service | Where-Object Status -EQ 'Stopped'", 'lists failed units on Linux or stopped services on Windows', None),
    ('(?:show |list )?(?:boot logs)', None, None, 'shows logs from the current boot', None),
    ('(?:show |list )?(?:system errors|recent errors)', None,
     "Get-WinEvent -FilterHashtable @{LogName='System'; Level=2} -MaxEvents 20", 'shows recent system errors', None),
    ('(?:show |list )?(?:scheduled tasks|cron jobs)', 'crontab -l', 'Get-ScheduledTask', 'lists your scheduled jobs', 'crontab'),
    ('(?:show |list )?(?:firewall status|firewall rules)', None, 'Get-NetFirewallProfile', 'shows firewall configuration', None),
    ('(?:show |list )?(?:wifi status|wi-fi status)', 'nmcli device status', 'netsh wlan show interfaces', 'shows network connection status', 'nmcli'),
    ('(?:show |list )?(?:wifi profiles|saved wifi networks)', 'nmcli connection show', 'netsh wlan show profiles', 'lists saved network profiles without passwords', 'nmcli'),
    ('(?:show |list )?(?:command history)', 'echo "Shell history belongs to your interactive shell; run history there."', 'Get-History', 'shows history available to the current shell', 'echo'),
    ('(?:show |list )?(?:time zone|timezone)', 'date +%Z', 'Get-TimeZone', 'shows the current time zone', 'date'),
    ('(?:show |list )?(?:cpu usage|top cpu processes)', 'ps -eo pid,comm,pcpu --sort=-pcpu | head -n 16',
     'Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 Name, Id, CPU', 'shows processes ranked by CPU time (Windows uses cumulative time)', 'ps'),
    ('(?:show |list )?(?:swap usage|swap space)', 'cat /proc/swaps',
     'Get-CimInstance Win32_PageFileUsage', 'shows configured swap/page files', 'cat'),
    ('(?:show |list )?(?:mounted filesystems|mounts)', 'mount', 'Get-PSDrive -PSProvider FileSystem', 'lists mounted filesystems', 'mount'),
    ('(?:show |list )?(?:disk usage by folder|folder sizes)', 'du -h -d 1 .',
     'Get-ChildItem -Directory | ForEach-Object { $s = Get-ChildItem -LiteralPath $_.FullName -Recurse -File | Measure-Object Length -Sum; [pscustomobject]@{Folder=$_.Name; Bytes=$s.Sum} }', 'shows space used by folders in the current directory', 'du'),
    ('(?:show |list )?(?:largest files)', 'find . -type f -exec du -k {} \\; | sort -nr | head -n 20',
     'Get-ChildItem -LiteralPath . -Recurse -File | Sort-Object Length -Descending | Select-Object -First 20 FullName, Length', 'shows the largest files under this directory', 'find'),
    ('(?:show |list )?(?:python version)', 'python3 --version', 'python --version', 'shows the Python version', 'python3'),
    ('(?:show |list )?(?:git version)', 'git --version', 'git --version', 'shows the Git version', 'git'),
    ('(?:show |list )?(?:git status|repository status)', 'git status --short --branch', 'git status --short --branch', 'shows branch and changed files', 'git'),
    ('(?:show |list )?(?:git changes|git diff)', 'git diff --stat', 'git diff --stat', 'summarizes unstaged changes in this repository', 'git'),
    ('(?:show |list )?(?:git branches)', 'git branch --all', 'git branch --all', 'lists Git branches', 'git'),
    ('(?:show |list )?(?:git log|recent commits)', 'git log -n 10 --oneline', 'git log -n 10 --oneline', 'shows the ten latest commits', 'git'),
    ('(?:show |list )?(?:git remotes)', 'git remote -v', 'git remote -v', 'shows configured Git remotes; URLs may include credentials', 'git'),
    ('(?:show |list )?(?:docker containers|containers)', 'docker ps', 'docker ps', 'lists running Docker containers; requires a Docker daemon', 'docker'),
    ('(?:show |list )?(?:all docker containers)', 'docker ps -a', 'docker ps -a', 'lists all Docker containers', 'docker'),
    ('(?:show |list )?(?:docker images)', 'docker images', 'docker images', 'lists locally stored Docker images', 'docker'),
    ('(?:show |list )?(?:docker disk usage)', 'docker system df', 'docker system df', 'shows Docker disk usage without deleting anything', 'docker'),
    ('(?:show |list )?(?:flatpak apps|flatpak applications)', 'flatpak list --app', None, 'lists installed Flatpak applications', 'flatpak'),
    ('(?:show |list )?(?:flatpak remotes)', 'flatpak remotes', None, 'lists configured Flatpak repositories', 'flatpak'),
    ('(?:show |list )?(?:snap apps|snap packages)', 'snap list', None, 'lists installed Snap packages', 'snap'),
    ('(?:show |list )?(?:wsl distros|wsl distributions)', None, 'wsl --list --verbose', 'lists installed WSL distributions', None),
    ('(?:show |list )?(?:power plans)', None, 'powercfg /list', 'lists Windows power plans', None),
    ('(?:show |list )?(?:windows version)', None, 'Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber', 'shows Windows edition and build', None),
    ('(?:show |list )?(?:installed windows updates)', None, 'Get-HotFix', 'lists installed Windows hotfixes (not every update type)', None),
    ('(?:show |list )?(?:windows features)', None, 'Get-WindowsOptionalFeature -Online', 'lists optional Windows features; may require elevation', None),
    ('(?:show |list )?(?:computer serial number)', 'cat /sys/class/dmi/id/product_serial',
     'Get-CimInstance Win32_BIOS | Select-Object SerialNumber', 'shows firmware serial number; Linux may require privileges', 'cat'),
]


def _expanded_offline(raw, t, pkg):
    # Package diagnostics are independent of app aliases.
    name = pkg['name']
    lists = {
        'pacman': ('pacman -Q', 'pacman -Qu'), 'paru': ('paru -Q', 'paru -Qu'),
        'yay': ('yay -Q', 'yay -Qu'), 'apt': ('apt list --installed', 'apt list --upgradable'),
        'dnf': ('dnf list --installed', 'dnf list --upgrades'),
        'dnf5': ('dnf5 list --installed', 'dnf5 list --upgrades'),
        'zypper': ('zypper search --installed-only', 'zypper list-updates'),
        'apk': ('apk info', "apk version -l '<'"),
        'xbps': ('xbps-query -l', 'xbps-install -un'),
        'emerge': ('qlist -I', 'emerge --pretend --update --deep --newuse @world'),
        'winget': ('winget list', 'winget list --upgrade-available'),
        'choco': ('choco list', 'choco outdated'), 'scoop': ('scoop list', 'scoop status'),
    }
    if name in lists:
        if re.fullmatch(r'(?:show|list)(?: my| all)? installed (?:apps|packages|programs)', t):
            cmd = lists[name][0]
            return (_tool_command('qlist', cmd) if name == 'emerge' else cmd, 'lists installed packages', 0)
        if re.fullmatch(r'(?:show|list|check)(?: for)?(?: available)? (?:updates|outdated packages|upgradable packages)', t):
            cmd = lists[name][1]
            if name == 'apk': cmd = 'apk version -l ' + _quote('<')
            return (cmd, 'lists available package updates using existing repository metadata', 0)

    for pattern, linux, win, explain, tool in OFFLINE_INFO:
        if not re.fullmatch(pattern, t):
            continue
        if IS_WIN:
            if win and tool in ('git', 'docker', 'python3'):
                win = _tool_command('python' if tool == 'python3' else tool, win)
            return (win, explain, 0) if win else None
        cmd = linux
        if pkg['family'] == 'alpine' and tool == 'ps':
            cmd, explain = 'ps', 'lists processes (minimal BusyBox ps does not rank CPU usage)'
        if t.endswith('services'):
            if shutil.which('systemctl'):
                cmd = 'systemctl --failed --no-pager' if 'failed' in t else 'systemctl list-units --type=service --no-pager'
            elif shutil.which('rc-status'):
                cmd = 'rc-status --all'
            elif shutil.which('sv'):
                cmd = 'sv status /var/service/*'
        elif 'logs' in t or 'errors' in t:
            if shutil.which('journalctl'):
                cmd = 'journalctl -b --no-pager -n 100' if 'boot' in t else 'journalctl -p err --no-pager -n 20'
        elif 'firewall' in t:
            for exe, command in [('ufw', 'sudo ufw status'), ('firewall-cmd', 'firewall-cmd --list-all'), ('nft', 'sudo nft list ruleset')]:
                if shutil.which(exe):
                    return (command, explain + ' (may require administrator privileges)', 0)
        if not cmd:
            return ('echo ' + _quote('No supported tool for this wish was detected on this machine.'), explain, 0)
        return (_tool_command(tool, cmd) if tool else cmd, explain, 0)

    # Match the original case-preserving request, not the normalized text.
    m = re.fullmatch(r'(?:create|make)(?: a| the)? (?:folder|directory) (.+)', raw, re.I)
    if m:
        path = _quote_path(m[1])
        cmd = f'New-Item -ItemType Directory -Path {path}' if IS_WIN else f'mkdir -p {path}'
        return (cmd, 'creates a directory; existing Linux directories are kept', 1)
    m = re.fullmatch(r'(?:read|show|view)(?: the)? file (.+)', raw, re.I)
    if m:
        path = _quote_path(m[1])
        return (f'Get-Content -LiteralPath {path}' if IS_WIN else f'cat {path}', 'shows the file contents', 0)
    m = re.fullmatch(r'(?:file info|file information|file details|permissions for)(?: the)? (.+)', raw, re.I)
    if m:
        path = _quote_path(m[1])
        return (f'Get-Item -LiteralPath {path} | Format-List *' if IS_WIN else f'ls -ld {path}', 'shows file information and attributes', 0)
    m = re.fullmatch(r'(?:hash|checksum|sha256)(?: the)?(?: file)? (.+)', raw, re.I)
    if m:
        path = _quote_path(m[1])
        cmd = f'Get-FileHash -Algorithm SHA256 -LiteralPath {path}' if IS_WIN else _tool_command('sha256sum', f'sha256sum {path}')
        return (cmd, 'computes a SHA-256 fingerprint of the file', 0)
    m = re.fullmatch(r'(?:find|search for)(?: a| the)? (?:file|files) (.+)', raw, re.I)
    if m:
        pattern = _quote(_unquote(m[1]))
        cmd = f'Get-ChildItem -LiteralPath . -Recurse -File -Filter {pattern}' if IS_WIN else f'find . -type f -name {pattern}'
        return (cmd, 'finds matching filenames below the current directory; supports * wildcards', 0)
    m = re.fullmatch(r'(?:size of|folder size)(?: the)?(?: folder| directory| file)? (.+)', raw, re.I)
    if m:
        path = _quote_path(m[1])
        cmd = (f'Get-ChildItem -LiteralPath {path} -Recurse -File | Measure-Object -Property Length -Sum'
               if IS_WIN else f'du -sh {path}')
        return (cmd, 'totals folder/file size (Windows reports bytes)', 0)
    m = re.fullmatch(r'(?:ping|test connection to|resolve|dns lookup|lookup dns for) ([a-z0-9][a-z0-9.:-]*)', raw, re.I)
    if m:
        host = _quote(m[1])
        lookup = t.startswith(('resolve', 'dns', 'lookup'))
        if IS_WIN:
            cmd = f'Resolve-DnsName -Name {host}' if lookup else f'Test-Connection -ComputerName {host} -Count 4'
        else:
            tool = 'nslookup' if lookup else 'ping'
            cmd = _tool_command(tool, f'nslookup {host}' if lookup else f'ping -c 4 {host}')
        return (cmd, 'looks up DNS records' if lookup else 'sends four probes; requires connectivity to the target', 0)
    m = re.fullmatch(r'(status of|start|stop|restart|enable|disable)(?: the)? service ([a-z0-9][a-z0-9_.@-]*)', raw, re.I)
    if m:
        action, service = m[1].lower(), _quote(m[2])
        level = 0 if action == 'status of' else 1
        if IS_WIN:
            verbs = {'status of': 'Get', 'start': 'Start', 'stop': 'Stop', 'restart': 'Restart'}
            if action in verbs: cmd = f'{verbs[action]}-Service -Name {service}'
            else: cmd = f'Set-Service -Name {service} -StartupType ' + ('Automatic' if action == 'enable' else 'Disabled')
        elif shutil.which('systemctl'):
            cmd = ('systemctl status --no-pager ' if not level else f'sudo systemctl {action} ') + service
        elif shutil.which('rc-service') and action in ('status of', 'start', 'stop', 'restart'):
            cmd = f"{'sudo ' if level else ''}rc-service {service} {'status' if not level else action}"
        elif shutil.which('sv') and action in ('status of', 'start', 'stop', 'restart'):
            verb = {'status of': 'status', 'start': 'up', 'stop': 'down', 'restart': 'restart'}[action]
            cmd = f"{'sudo ' if level else ''}sv {verb} /var/service/{m[2]}"
        else:
            return ('echo ' + _quote('No supported service manager for this action was detected.'), 'service action unavailable', 0)
        return (cmd, f'{action} service {m[2]} (administrator privileges may be required)', level)
    return None


def offline_match(text, ai_available):
    """Return (cmd, explain, danger) or None. Covers the everyday stuff."""
    pkg = detect_pkg()
    t = _clean(text)
    raw = _clean_preserving_case(text)
    expanded = _expanded_offline(raw, t, pkg)
    if expanded:
        return expanded

    # easter egg (xkcd 149)
    if t in ("make me a sandwich", "sudo make me a sandwich"):
        word = "Okay." if t.startswith("sudo") else "What? Make it yourself."
        return (f"echo '{word}'", "an old Linux joke — look up xkcd 149", 0)

    # trash a file/folder (checked before package removal on purpose)
    m = re.match(r"^(?:delete|remove|trash)(?: the)? (?:file|folder|directory) (.+)$", raw, re.I)
    if m:
        target = _path(m.group(1))
        if IS_WIN:
            return (_recycle_cmd(target),
                    f"moves '{target}' to the Recycle Bin — you can restore it from there", 1)
        return (_tool_command("gio", "gio trash -- " + _quote_path(target)),
                f"moves '{target}' to the Trash — you can restore it from Dolphin", 1)

    # install
    m = re.match(r"^(?:install|get|download)(?: the)? (.+)$", t)
    if m and pkg["name"]:
        app = _app_name(m.group(1))
        p = _manager_alias(app, pkg)
        if p:
            return (pkg["install"].format(pkg=p),
                    f"installs {app} using {pkg['name']} (the package manager)", 1)
        if not ai_available:
            return (_package_search(pkg, app),
                    f"searches the repositories for '{app}' so you can pick the exact package", 0)
        return None  # let the AI resolve the real package name

    # remove a known app
    m = re.match(r"^(?:uninstall|remove)(?: the)? (.+)$", t)
    if m and pkg["name"]:
        app = _app_name(m.group(1))
        p = _manager_alias(app, pkg)
        if p:
            return (pkg["remove"].format(pkg=p.split()[0]),
                    f"removes {app} using {pkg['name']}", 1)
        return None

    # update the system
    if re.match(r"^(?:update|upgrade)(?: my| the)?(?: whole)?"
                r"(?: system| everything| all| pc| computer| packages| os)?$", t) and pkg["name"]:
        return (pkg["update"],
                "updates every package on your system to the latest version", 1)

    if re.search(r"^(?:search|look)(?: for)? (?:a |an )?(?:package|app) (.+)$", t) and pkg["name"]:
        term = re.search(r"(?:package|app) (.+)$", t).group(1)
        return (_package_search(pkg, term), f"searches the repositories for '{term}'", 0)

    # everyday questions
    if IS_WIN:
        return _everyday_win(t)
    return _everyday_linux(t, pkg)


def _recycle_cmd(target):
    """PowerShell one-liner: send a file OR folder to the Recycle Bin."""
    p = target.replace("'", "''")
    return ("$p='" + p + "'; Add-Type -AssemblyName Microsoft.VisualBasic; "
            "if(Test-Path -LiteralPath $p -PathType Container)"
            "{[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory("
            "$p,'OnlyErrorDialogs','SendToRecycleBin')}"
            "else{[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
            "$p,'OnlyErrorDialogs','SendToRecycleBin')}")


def _everyday_win(t):
    if re.search(r"(list|show)( me)?( all)?( the)? files", t):
        return ("Get-ChildItem", "lists every file in this folder, with sizes and dates", 0)
    if re.search(r"(disk|storage)( space| usage)?$|how much (disk|storage|space)", t):
        return ("Get-Volume", "shows each drive and how much space is free", 0)
    if re.search(r"(memory|ram)( usage)?$|how much (memory|ram)", t):
        return ("Get-CimInstance Win32_OperatingSystem | Format-List "
                "@{n='free RAM (GB)';e={[math]::Round($_.FreePhysicalMemory/1MB,1)}},"
                "@{n='total RAM (GB)';e={[math]::Round($_.TotalVisibleMemorySize/1MB,1)}}",
                "shows how much RAM is used and how much is free", 0)
    if re.fullmatch(r"(what('| i)?s )?(my )?(local )?ip( address)?", t):
        return ("ipconfig", "shows your network adapters and their IP addresses", 0)
    if re.search(r"public ip", t):
        return ("curl.exe -fsS https://api.ipify.org", "asks the internet what your public IP is", 0)
    if re.search(r"(show|list|scan)( me)?( the| all| available| nearby)? ?wi-?fi( networks)?", t):
        return ("netsh wlan show networks", "lists the Wi-Fi networks around you", 0)
    if re.search(r"(show|list)( me)?( the)?( running)? processes", t):
        return ("Get-Process | Sort-Object WS -Descending | Select-Object -First 15",
                "shows the 15 programs using the most memory right now", 0)
    if re.search(r"battery( level| status| percentage)?$", t):
        return ("(Get-CimInstance Win32_Battery).EstimatedChargeRemaining",
                "shows your battery percentage", 0)
    if re.search(r"(system info|specs|about (my|this) (pc|computer|system))", t):
        return ("systeminfo", "shows a summary of your computer and OS", 0)
    if t in ("where am i", "current folder", "what folder is this"):
        return ("Get-Location", "prints the folder you are standing in right now", 0)
    if t in ("what time is it", "date", "time", "what day is it"):
        return ("Get-Date", "shows the current date and time", 0)
    if re.match(r"^(shut ?down|turn off)( my| the)?( pc| computer| system)?$", t):
        return ("shutdown /s /t 0", "turns the computer off", 1)
    if re.match(r"^(restart|reboot)( my| the)?( pc| computer| system)?$", t):
        return ("shutdown /r /t 0", "restarts the computer", 1)
    return None


def _everyday_linux(t, pkg):
    if re.search(r"(list|show)( me)?( all)?( the)? files", t):
        return ("ls -lah", "lists every file here, with sizes and dates", 0)
    if re.search(r"(disk|storage)( space| usage)?$|how much (disk|storage|space)", t):
        return ("df -h", "shows how full each disk is, in human-readable sizes", 0)
    if re.search(r"what('| i)?s (taking|using|eating)( up)? (my )?(space|storage|disk)", t):
        return ("du -h -d 1 ~",
                "shows space used by folders in your home", 0)
    if re.search(r"(memory|ram)( usage)?$|how much (memory|ram)", t):
        return ("free -h", "shows how much RAM is used and how much is free", 0)
    if re.fullmatch(r"(what('| i)?s )?(my )?(local )?ip( address)?", t):
        return ("ip -brief address", "shows your network devices and their IP addresses", 0)
    if re.search(r"public ip", t):
        return (_tool_command("curl", "curl -fsS https://api.ipify.org && echo"), "asks the internet what your public IP is", 0)
    if re.search(r"(show|list|scan)( me)?( the| all| available| nearby)? ?wi-?fi( networks)?", t):
        return ("nmcli device wifi list", "lists the Wi-Fi networks around you", 0)
    if re.search(r"(show|list)( me)?( the)?( running)? processes", t):
        return ("ps" if pkg["family"] == "alpine" else "ps aux --sort=-%mem | head -n 15",
                "lists processes (ranked by memory when procps is available)", 0)
    if re.search(r"battery( level| status| percentage)?$", t):
        return ("cat /sys/class/power_supply/BAT*/capacity",
                "shows your battery percentage", 0)
    if re.search(r"(system info|specs|about (my|this) (pc|computer|system))", t):
        for tool in ("fastfetch", "neofetch"):
            if shutil.which(tool):
                return (tool, "shows a summary of your computer and OS", 0)
        return ("hostnamectl || uname -a", "shows a summary of your computer and OS", 0)
    if re.search(r"clean( up)?( my)? (system|cache|package cache)|free up space", t) and pkg.get("clean"):
        return (pkg["clean"], "clears old downloaded packages to free disk space", 1)
    if t in ("where am i", "current folder", "what folder is this"):
        return ("pwd", "prints the folder you are standing in right now", 0)
    if t in ("what time is it", "date", "time", "what day is it"):
        return ("date", "shows the current date and time", 0)
    has_systemd = bool(shutil.which("systemctl"))
    if re.match(r"^(shut ?down|turn off)( my| the)?( pc| computer| system)?$", t):
        return ("systemctl poweroff" if has_systemd else "sudo poweroff",
                "turns the computer off", 1)
    if re.match(r"^(restart|reboot)( my| the)?( pc| computer| system)?$", t):
        return ("systemctl reboot" if has_systemd else "sudo reboot",
                "restarts the computer", 1)

    return None


# --------------------------------------------------------------------------
# safety
# --------------------------------------------------------------------------

HARD_BLOCK = [
    r"\brm\s+(-\S+\s+)*/\s*(\*|$)",            # rm on / itself
    r"--no-preserve-root",
    r":\s*\(\s*\)\s*\{",                        # fork bomb
    r"\bdd\b.*\bof=/dev/(sd|nvme|vd|hd|mmcblk)",
    r">\s*/dev/(sd|nvme|vd|hd|mmcblk)",
    r"\bmkfs(\.\w+)?\b.*/dev/",
    r"\bchmod\s+(-\w+\s+)*777\s+/\s*$",
    r"\bchown\b.*\s/\s*$",
    r"\bshred\b.*/dev/",
]

LEVEL2 = [
    r"\brm\s+(-\S*[rf]\S*\s+)",   # any recursive/forced rm
    r"\brm\b.*\*",                # rm with wildcards
    r"\bdd\b",
    r"\bmkfs",
    r"\b(fdisk|parted|wipefs|sgdisk)\b",
    r"\buserdel\b",
]

LEVEL1 = [
    r"^\s*sudo\b",
    r"\b(pacman|paru|yay)\b.*\s-(S|R|Syu)",
    r"\bapt(-get)?\s+(install|remove|purge|upgrade|full-upgrade|dist-upgrade|autoremove)\b",
    r"\bdnf5?\s+(install|remove|upgrade|update|autoremove|swap)\b",
    r"\bzypper\s+(install|in|remove|rm|update|up|dup)\b",
    r"\bapk\s+(add|del|upgrade)\b",
    r"\bxbps-(install|remove)\b",
    r"\bemerge\b(?!.*--search)",
    r"\bsystemctl\s+(start|stop|restart|reload|enable|disable|mask|unmask|reboot|poweroff|suspend|hibernate)\b",
    r"\b(kill|pkill|killall)\b",
    r"\bnpm\s+i(nstall)?\s+-g",
    r"\bpip\d?\s+install",
]


# the same three tiers, in Windows dialect
WIN_HARD_BLOCK = [
    r"(?i)\bformat(\.com)?\b\s+[a-z]:",                       # format C:
    r"(?i)\bformat-volume\b.*-driveletter\s+c\b",
    r"(?i)\b(rd|rmdir)\b\s+/s(\s+/q)?\s+[a-z]:\\?\s*$",       # rd /s /q C:\
    r"(?i)\bdel\b\s+(/\w+\s+)*[a-z]:\\\*",                    # del /f /s /q C:\*
    r"(?i)remove-item\b(?=.*-recurse).*['\" ][a-z]:[\\/]?['\"]?(\s+-\w+)*\s*$",
    r"(?i)\bdiskpart\b",
    r"(?i)vssadmin\s+delete\s+shadows",
    r"(?i)\bcipher\s+/w",
    r"(?i)\breg\s+delete\s+hk(lm|ey_local_machine)\b\s*(/f\s*)?$",
]

WIN_LEVEL2 = [
    r"(?i)remove-item\b.*(-recurse|-force)",
    r"(?i)remove-item\b.*\*",
    r"(?i)\bdel\b.*\s/s\b",
    r"(?i)\b(rd|rmdir)\b\s+/s",
    r"(?i)\bformat-volume\b",
    r"(?i)\breg\s+delete\b",
    r"(?i)\bbcdedit\b",
]

WIN_LEVEL1 = [
    r"(?i)\bwinget\s+(install|uninstall|upgrade)\b",
    r"(?i)\b(choco|scoop)\s+(install|uninstall|update|upgrade)\b",
    r"(?i)\bshutdown\b",
    r"(?i)\bnetsh\b(?!\s+wlan\s+show)",
    r"(?i)\breg\s+add\b",
    r"(?i)\bset-itemproperty\b",
    r"(?i)\b(start|restart|set)-service\b",
    r"(?i)\bnew-item\b",
    r"(?i)\bstop-(process|service|computer)\b",
    r"(?i)\brestart-computer\b",
    r"(?i)\bschtasks\b",
]


def danger_of(cmd, ai_danger=0):
    hard, lv2, lv1 = ((WIN_HARD_BLOCK, WIN_LEVEL2, WIN_LEVEL1) if IS_WIN
                      else (HARD_BLOCK, LEVEL2, LEVEL1))
    for pat in hard:
        if re.search(pat, cmd):
            return "block"
    level = int(ai_danger or 0)
    if any(re.search(p, cmd) for p in lv2):
        level = max(level, 2)
    elif any(re.search(p, cmd) for p in lv1):
        level = max(level, 1)
    return min(level, 2)


# --------------------------------------------------------------------------
# config + history
# --------------------------------------------------------------------------

def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_PATH, 0o600)


def log_history(request, cmd, ran):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "said": request, "cmd": cmd, "ran": ran,
            }) + "\n")
    except OSError:
        pass


def show_history():
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
    except OSError:
        lines = []
    if not lines:
        print(DIM("  no history yet — go ask genie something!"))
        return
    print(BOLD(f"\n  {LAMP} commands you've learned so far\n"))
    for item in lines[-15:]:
        mark = GREEN("✓") if item["ran"] else DIM("·")
        print(f"  {mark} {DIM(item['said'])}")
        print(f"     {CYAN(item['cmd'])}\n")


# --------------------------------------------------------------------------
# the main flow
# --------------------------------------------------------------------------

def copy_to_clipboard(text):
    tools = ((["clip"],) if IS_WIN
             else (["wl-copy"], ["xclip", "-selection", "clipboard"]))
    for tool in tools:
        if shutil.which(tool[0]):
            try:
                subprocess.run(tool, input=text.encode(), check=True)
                return True
            except (OSError, subprocess.CalledProcessError):
                pass
    return False


def present(request, cmd, explain, danger, dry=False):
    print()
    print(f"  {DIM('you said')}   {request}")
    print(f"  {BOLD('command')}    {GREEN(cmd)}")
    print(f"  {BOLD('meaning')}    {explain}")

    if danger == "block":
        print(f"\n  {RED('✗ blocked.')} that command could destroy your system, "
              "and no wish is worth that.\n")
        log_history(request, cmd, False)
        return

    if dry:
        print(DIM("\n  (dry run — nothing executed)\n"))
        log_history(request, cmd, False)
        return

    if danger == 2:
        print(f"\n  {RED('⚠ careful:')} this can permanently delete or change things.")
        try:
            ans = input(f"  type {BOLD('yes')} to run it, anything else cancels: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        ok = ans == "yes"
    else:
        if danger == 1:
            print(f"  {YELLOW('note')}       this will change your system")
        try:
            ans = input(f"\n  run it? {DIM('[Enter = yes · n = no · c = copy]')} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans == "c":
            if copy_to_clipboard(cmd):
                print(GREEN("  copied to clipboard ✓\n"))
            else:
                print(DIM("  (no clipboard tool found — select it manually)\n"))
            log_history(request, cmd, False)
            return
        ok = ans in ("", "y", "yes")

    if not ok:
        print(DIM("  cancelled — your wish is safe with me.\n"))
        log_history(request, cmd, False)
        return

    print(DIM("  " + "─" * 48))
    if IS_WIN:
        code = subprocess.call(["powershell", "-NoProfile", "-Command", cmd])
    else:
        code = subprocess.call(cmd, shell=True, executable="/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh")
    print(DIM("  " + "─" * 48))
    if code == 0:
        print(GREEN(f"  ✓ done  {DIM('— now you know:')} {cmd}\n"))
    else:
        print(YELLOW(f"  finished with exit code {code}\n"))
    log_history(request, cmd, code == 0)


HINTS = {
    "auth": "get a fresh key and run `genie setup`",
    "model": "run `genie setup` and enter a current model name",
    "ratelimit": "wait a minute, or add another free provider with `genie setup`",
    "quota": "free tiers reset daily — or add another free provider with `genie setup`",
    "server": "the provider is having a moment — try again shortly",
    "local-down": "then just re-run your wish",
    "unreachable": "check your connection",
    "weird": "run `genie status` to test your providers",
}


def grant_wish(request, dry=False):
    cfg = load_config()
    providers = get_providers(cfg)
    ai_ready = any(
        not PROVIDERS[n].get("needs_key", True) or p.get("api_key")
        for n, p in providers
    )

    # a wish that isn't a wish — any pile of greetings, e.g. "hi hello genie"
    if re.fullmatch(r"(hi|hello|hey|yo|sup)([ ,!]+(hi|hello|hey|yo|sup|there|genie))*",
                    _clean(request)):
        print(f"\n  {MAGENTA(LAMP)} hello! i grant terminal wishes. try:")
        print(f"    {CYAN(CALL + ' install teams for me')}")
        print(f"    {CYAN(CALL + ' how much disk space do i have')}\n")
        return

    hit = offline_match(request, ai_ready)
    if hit:
        cmd, explain, danger = hit
        present(request, cmd, explain, danger_of(cmd, danger), dry)
        return

    if not ai_ready:
        print(f"\n  {LAMP} {BOLD('genie needs a brain for that one.')}")
        print(f"  run {CYAN('genie setup')} to connect a free AI provider (2 minutes).")
        print(DIM("  meanwhile, i can already do things like:"))
        print(DIM(f"    {CALL} install teams for me"))
        print(DIM(f"    {CALL} update my whole system"))
        print(DIM(f"    {CALL} how much disk space do i have\n"))
        return

    print(DIM(f"\n  {LAMP} rubbing the lamp..."), flush=True)
    messages = [{"role": "user", "content": request}]
    bad_parses = 0

    for _ in range(5):
        try:
            raw = ask_ai(cfg, messages)
        except AllProvidersFailed as e:
            if len(e.failures) == 1:
                name, pe = e.failures[0]
                print(f"  {RED('✗')} {BOLD(name)}: {pe.msg}")
                print(f"    {DIM('→ ' + HINTS.get(pe.kind, ''))}\n")
            else:
                print(f"  {RED('✗')} every configured provider failed:")
                for name, pe in e.failures:
                    print(f"    {BOLD(name):<24} {pe.msg}")
                print(f"    {DIM('→ genie status  tests them all · genie setup  adds another')}\n")
            print(DIM("  offline basics still work: install apps, updates, disk space...\n"))
            return

        data = parse_reply(raw)
        if not data:
            # one silent retry — nudge the model back to strict JSON
            bad_parses += 1
            if bad_parses == 1:
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content":
                    "Reply again with ONLY the minified JSON object, nothing else."})
                continue
            print(f"  {RED('✗')} the AI gave a confusing answer — try rephrasing your wish.")
            print(DIM(f"    (it replied: {raw.strip()[:120]})\n"))
            return

        if data["type"] == "question":
            print(f"\n  {MAGENTA(LAMP + ' genie asks:')} {data['ask']}")
            try:
                answer = input("  › ").strip()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if not answer:
                print(DIM("  cancelled.\n"))
                return
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": answer})
            continue

        present(request, data["cmd"], data["explain"],
                danger_of(data["cmd"], data["danger"]), dry)
        return

    print(f"  {RED('✗')} too many follow-up questions — try being more specific.\n")


# --------------------------------------------------------------------------
# setup wizard
# --------------------------------------------------------------------------

def _ping_provider(name, pcfg):
    """One tiny live request to prove the key/model/server work.
    Returns None on success, a ProviderError on failure."""
    try:
        call_ai(name, pcfg, [{"role": "user", "content": "ping"}], timeout=20)
        return None
    except ProviderError as pe:
        return pe


def _ollama_precheck(model):
    """Make sure ollama is installed, running, and has the model pulled.
    Returns True when wishes will actually work."""
    if not shutil.which("ollama"):
        print(f"\n  {RED('✗')} ollama isn't installed on this machine.")
        print(f"    install it first: {CYAN('https://ollama.com/download')}")
        if IS_WIN:
            print(DIM("    (or: winget install Ollama.Ollama)\n"))
        else:
            print(DIM("    (or from your package manager, e.g. `sudo pacman -S ollama`)\n"))
        return False
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            tags = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        print(f"\n  {RED('✗')} ollama is installed but the server isn't running.")
        if IS_WIN:
            print(f"    start the {CYAN('Ollama')} app from the Start menu, "
                  f"then run setup again\n")
        else:
            print(f"    start it with: {CYAN('systemctl enable --now ollama')}"
                  + DIM("   (or just: ollama serve)") + "\n")
        return False
    have = set()
    for m in tags.get("models", []):
        n = m.get("name", "")
        have.add(n)
        have.add(n.split(":")[0])
    if model not in have and model.split(":")[0] not in have:
        print(f"\n  the model {BOLD(model)} isn't downloaded yet.")
        try:
            ans = input(f"  download it now with `ollama pull {model}`? "
                        f"{DIM('[Enter = yes · n = no]')} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans in ("", "y", "yes"):
            code = subprocess.call(["ollama", "pull", model])
            return code == 0
        print(DIM(f"    run `ollama pull {model}` later, then genie will work.\n"))
        return False
    return True


def setup():
    print(banner())
    print(BOLD("  let's connect genie's brain — pick an AI provider:\n"))
    names = list(PROVIDERS)
    for i, name in enumerate(names, 1):
        p = PROVIDERS[name]
        print(f"   {CYAN(str(i))}. {BOLD(name):<22} {DIM(p['note'])}")
    print()
    try:
        choice = input(f"  choice {DIM('[1-' + str(len(names)) + ', Enter = 1]')} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    idx = int(choice) - 1 if choice.isdigit() and 0 < int(choice) <= len(names) else 0
    name = names[idx]
    p = PROVIDERS[name]

    cfg = load_config()
    pcfg = dict((cfg.get("providers") or {}).get(name) or {})

    if p["needs_key"]:
        print(f"\n  get a key here: {CYAN(p['key_url'])}")
        try:
            key = input("  paste your API key: ").strip().strip("'\"")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not key:
            print(RED("  no key entered — setup cancelled.\n"))
            return
        pcfg["api_key"] = key

    try:
        model = input(f"  model {DIM('[Enter = ' + p['model'] + ']')} ").strip()
    except (EOFError, KeyboardInterrupt):
        model = ""
    pcfg["model"] = model or p["model"]

    if name == "ollama" and not _ollama_precheck(pcfg["model"]):
        print(DIM("  (saving the config anyway — fix the above and you're set)\n"))

    # prove it works NOW, not at your first wish
    print(DIM("\n  rubbing the lamp — testing the connection..."), flush=True)
    pe = _ping_provider(name, pcfg)
    if pe is None:
        print(GREEN("  ✓ connected — the lamp glows.\n"))
    else:
        print(f"  {RED('✗')} {pe.msg}")
        print(f"    {DIM('→ ' + HINTS.get(pe.kind, ''))}")
        try:
            ans = input(f"  save this config anyway? {DIM('[y/N]')} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans not in ("y", "yes"):
            print(DIM("  nothing saved — run genie setup again when ready.\n"))
            return

    # store under providers{} — genie remembers every provider you set up
    provs = dict(get_providers(cfg))
    provs[name] = pcfg
    cfg["providers"] = provs
    cfg["provider"] = name          # the one you just set up becomes primary
    cfg.pop("api_key", None)        # retire the old single-provider fields
    cfg.pop("model", None)
    save_config(cfg)

    others = [n for n in provs if n != name]
    print(GREEN("  ✓ genie is ready.") + " try these:\n")
    print(f"    {CYAN(CALL + ' install teams for me')}")
    print(f"    {CYAN(CALL + ' my wifi feels slow, check it')}")
    print(f"    {CYAN(CALL + ' find every photo i downloaded this month')}\n")
    if others:
        print(DIM(f"  if {name} is busy, genie falls back to: {', '.join(others)}"))
        print(DIM("  check them all anytime with: genie status\n"))


def show_status():
    """genie status — test every configured provider, right now."""
    cfg = load_config()
    provs = get_providers(cfg)
    print(banner())
    if not provs:
        print(f"  no providers configured yet — run {CYAN('genie setup')}\n")
        return
    print(BOLD("  your providers") + DIM("   ★ = primary (tried first)") + "\n")
    working = 0
    for name, pcfg in provs:
        star = "★" if name == cfg.get("provider") else "·"
        model = pcfg.get("model") or PROVIDERS[name]["model"]
        print(f"  {star} {BOLD(name)}  {DIM(model)}", flush=True)
        t0 = time.time()
        pe = _ping_provider(name, pcfg)
        dt = time.time() - t0
        if pe is None:
            print(f"      {GREEN(f'✓ working ({dt:.1f}s)')}\n")
            working += 1
        else:
            print(f"      {RED('✗ ' + pe.msg)}")
            print(f"      {DIM('→ ' + HINTS.get(pe.kind, ''))}\n")
    if not working:
        print(f"  {YELLOW('no provider is answering right now')} — "
              f"add another with {CYAN('genie setup')}\n")


# --------------------------------------------------------------------------
# banner / help
# --------------------------------------------------------------------------

def banner():
    return f"""
   {MAGENTA('.-~~~-.')}
  {MAGENTA('(  ' + LAMP + '  )')}   {BOLD('genie')} {DIM('v' + VERSION)}
   {MAGENTA("`-...-'")}   {DIM('your terminal, in plain English')}
"""


def show_offline_wishes():
    print(banner())
    print("  Offline wishes — no AI key needed to translate these requests.\n")
    print("  Package changes and network probes still need network access;")
    print("  optional tools, permissions, and services depend on your machine.\n")
    examples = [
        "list installed packages", "check for updates", "install vlc", "search for package editor",
        "update my system", "show cpu info", "uptime", "computer name", "kernel version",
        "os version", "show disks", "show usb devices", "show graphics card", "who am i",
        "show groups", "logged in users", "show network interfaces", "routing table",
        "dns servers", "listening ports", "network connections", "arp table", "show hidden files",
        "show services", "failed services", "boot logs", "system errors", "scheduled tasks",
        "firewall status", "wifi status", "saved wifi networks", "time zone", "cpu usage",
        "swap usage", "mounts", "folder sizes", "largest files", "python version", "git version",
        "git status", "git diff", "git branches", "recent commits", "git remotes",
        "docker containers", "all docker containers", "docker images", "docker disk usage",
        "create folder Project Notes", "read file README.md", "file info README.md",
        "sha256 file README.md", "find files *.py", "size of Project Notes",
        "ping example.com", "resolve example.com", "status of service sshd",
        "start service sshd", "stop service sshd", "restart service sshd",
        "enable service sshd", "disable service sshd", "how much disk space do i have",
    ]
    print("\n".join("    " + example for example in examples))
    print("\n  Linux extras: flatpak apps, flatpak remotes, snap packages")
    print("  Windows extras: wsl distros, power plans, windows version, installed windows updates, windows features\n")


def show_help():
    print(banner())
    print(f"""  {BOLD('usage')}
    {CALL} <anything in plain English>

  {BOLD('examples')}
    {CALL} install teams for me
    {CALL} update my whole system
    {CALL} how much disk space do i have
    {CALL} delete the folder old-homework

  {BOLD('what happens')}
    genie shows you the {GREEN('real command')} + what it {BOLD('means')},
    so you learn the terminal while using it. nothing runs
    until you press Enter.

  {BOLD('other commands')}
    genie setup      connect an AI provider (free options available)
                     run it again to add more — genie falls back
                     automatically when one is busy
    genie wishes     browse built-in offline wishes
    genie status     test all your providers right now
    genie history    the commands you've learned so far
    genie -n <wish>  dry run — show the command but never run it
    genie help       this screen
""")


def main():
    args = sys.argv[1:]
    dry = False
    if args and args[0] in ("-n", "--dry", "--dry-run"):
        dry = True
        args = args[1:]

    if not args or args[0] in ("help", "-h", "--help"):
        show_help()
    elif args[0] in ("-v", "--version", "version"):
        print(f"genie {VERSION}")
    elif args[0] == "setup":
        setup()
    elif args[0] in ("wishes", "offline"):
        show_offline_wishes()
    elif args[0] in ("status", "doctor"):
        show_status()
    elif args[0] == "history":
        show_history()
    else:
        grant_wish(" ".join(args), dry)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(DIM("\n  poof.\n"))
        sys.exit(130)
