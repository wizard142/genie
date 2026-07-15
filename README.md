<div align="center">

```
   .-~~~-.
  (  🧞  )    g e n i e
   `-...-'
```

### Your terminal, in plain English.

Type `/genie install teams for me`. genie shows you the real command, tells you what it does, and runs it once you say yes.

Born on CachyOS, works everywhere — genie speaks pacman, apt, dnf, zypper, apk, xbps and emerge on Linux, and PowerShell + winget on Windows. It adapts to whatever machine it's on.

</div>

---

## Why

A lot of Linux beginners never touch the terminal because the commands are hard to remember. Most tools fix that by hiding the terminal. genie goes the other way: you type what you want in English, and it shows you the actual command and what it means before running anything. Use it for a while and you'll start remembering the commands yourself.

```
$ /genie install teams for me

  you said   install teams for me
  command    paru -S teams-for-linux
  meaning    installs Microsoft Teams using paru (the package manager)
  note       this will change your system

  run it? [Enter = yes · n = no · c = copy]
```

## What it does

genie only runs when you put `/genie` in front. The rest of the time your terminal works normally.

Every answer shows the real command plus a one-line explanation, so you learn as you go. Run `genie history` to see everything you've asked for.

Nothing runs until you allow it: Enter to run, `n` to cancel, `c` to copy the command instead.

It won't let you wreck your system. Commands that delete or overwrite things make you type `yes` first, and a few truly dangerous ones (`rm -rf /`, fork bombs, writing straight to a disk) are blocked no matter what the AI says.

You pick the AI: Groq, Google Gemini, and OpenRouter all have free tiers, Anthropic Claude is paid, and Ollama runs on your own machine for free. Set it up in about two minutes with `genie setup` — it tests your key on the spot, so a bad key fails in two seconds instead of at your first wish.

Free tiers are flaky, so genie doesn't trust just one. Set up more than one provider (run `genie setup` again) and genie retries busy providers briefly, then falls back to your next one automatically. You only see an error when *everything* failed — and then it tells you exactly why, per provider.

Common jobs work with no AI at all. Installing apps, updating the system, and checking disk, RAM, Wi-Fi, or battery are built in, so they work offline with no key.

It's one Python file with no dependencies. Nothing to `pip install`.

## Works on

Arch / CachyOS / EndeavourOS (pacman, paru, yay — with AUR support), Debian / Ubuntu / Mint (apt), Fedora (dnf), openSUSE (zypper), Alpine (apk), Void (xbps), and Gentoo (emerge). genie detects your package manager at runtime and both the AI and the offline built-ins use the right commands for *your* distro.

**Windows 10/11 too (new in v1.2).** genie runs natively on Windows: it generates PowerShell commands instead of bash, installs apps with winget, sends deletions to the Recycle Bin, and its safety engine blocks the Windows catastrophes (`format C:`, `diskpart`, `Remove-Item -Recurse C:\`, `vssadmin delete shadows`…). One difference: type `genie` without the slash — Windows has no filesystem root to hang `/genie` on.

```powershell
git clone https://github.com/wizard142/genie.git
cd genie
powershell -ExecutionPolicy Bypass -File install.ps1
genie setup
genie install teams for me
```

Prefer a Linux feel on Windows? genie also runs unchanged inside [WSL](https://learn.microsoft.com/windows/wsl/install) with the Linux installer.

## Install

```bash
git clone https://github.com/wizard142/genie.git
cd genie
./install.sh          # asks for sudo
genie setup           # connect a free AI provider (optional but recommended)
```

Then make a wish:

```bash
/genie update my whole system
/genie how much disk space do i have
/genie delete the folder old-homework
/genie find every photo i downloaded this month
```

## How `/genie` works

Shells run anything with a `/` in it as a file path. The installer puts a link at the root of the filesystem:

```
/genie  →  /usr/local/bin/genie
```

So `/genie install teams` just runs the file `/genie` with your words as arguments. No shell plugins or hooks, and it works the same in bash, zsh, and fish (the CachyOS default).

(Windows has no filesystem root to put a `/genie` in, so there you get a regular `genie` command on your PATH instead — same genie, no slash.)

## Safety levels

| level | example | what genie does |
|---|---|---|
| 0 · read-only | `df -h`, `ls` | shows it, asks to run |
| 1 · changes system | `paru -S vlc`, `systemctl reboot` | shows it, yellow warning, asks to run |
| 2 · destructive | `rm -rf ~/folder`, `dd`, `mkfs` | red warning, you type `yes` |
| ☠ · catastrophic | `rm -rf /`, fork bombs, writes to `/dev/sdX` | blocked, always |

The level is the stricter of two checks: the AI's own rating and genie's own scan of the command. When deleting files, genie uses `gio trash` (recoverable from the Trash) instead of `rm`.

## Providers

| provider | cost | note |
|---|---|---|
| Groq | free tier | fastest to set up |
| Google Gemini | free tier | erratic free quota — pair it with a fallback |
| OpenRouter | free models available | shared pools, often busy — pair it with a fallback |
| Anthropic Claude | paid API | best quality |
| Ollama | free | runs locally, works offline |

**Set up two or three.** Run `genie setup` once per provider — genie remembers them all, uses the most recent as primary, and falls back to the others automatically when one is rate-limited or down. `genie status` live-tests every provider you've configured.

Your keys are stored in `~/.config/genie/config.json` (chmod 600).

## Commands

```
/genie <anything in English>   make a wish
genie setup                    connect an AI provider (run again to add more)
genie status                   live-test every provider you've configured
genie history                  everything you've asked for so far
genie -n <wish>                dry run — show the command, never run it
genie help                     help screen
```

## Troubleshooting

**`zsh: no matches found: ...?`** — zsh (the CachyOS default) reads `?` and `*` as wildcards and stops before genie runs. Drop the `?`, or tell zsh to leave unmatched wildcards alone for good:

```bash
echo 'unsetopt nomatch' >> ~/.zshrc   # then reopen your terminal
```

**`✗ key rejected`**: the key is wrong, expired, or the account isn't verified. Since v1.1 `genie setup` tests the key the moment you paste it, so you find out immediately — grab a fresh key from your provider's console and run setup again.

**`✗ model unavailable`**: providers retire model names every few months. Run `genie setup` and enter a current model ID from your provider's models page. The Gemini default `gemini-flash-latest` auto-updates, so it rarely breaks.

**`✗ rate limited` / `✗ free-tier quota used up`**: genie already retried and failed over to your other providers before showing you this. Per-minute limits clear in seconds; per-day quotas reset overnight. The real fix is having 2–3 providers configured — run `genie setup` again to add one.

**`✗ ollama isn't running`**: start it with `systemctl enable --now ollama` (or run `ollama serve` in another terminal).

**`✗ model 'llama3.2' isn't downloaded`**: run `ollama pull llama3.2` — since v1.1 `genie setup` offers to do this for you.

**Slow replies**: genie turns off Gemini's "thinking" mode to keep things fast. Most perceived slowness is actually silent retries against a busy free tier — `genie status` shows each provider's real response time.

## Uninstall

```bash
./uninstall.sh        # Linux
```

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1   # Windows
```

## Roadmap

- [x] ~~Every Linux distro, not just Arch~~ (v1.1)
- [x] ~~Automatic retry + failover across providers~~ (v1.1)
- [x] ~~Native Windows support (PowerShell + winget)~~ (v1.2)
- [ ] `genie explain <command>`: paste a command you don't recognize, get it in plain English
- [ ] Multi-step wishes ("set up a python project with git")
- [ ] A Konsole profile with genie ready to go for the CachyOS beginner ISO

## License

MIT. Use it for whatever makes Linux easier for someone.
