#!/usr/bin/env bash
# genie installer — any Linux with python3 (born on CachyOS/Arch)
set -euo pipefail

BIN=/usr/local/bin/genie
SRC="$(cd "$(dirname "$0")" && pwd)/genie.py"

echo
echo "  🧞 installing genie..."
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "  ✗ python3 is required but not found. install it first:"
    echo "      Arch/CachyOS:   sudo pacman -S python"
    echo "      Debian/Ubuntu:  sudo apt install python3"
    echo "      Fedora:         sudo dnf install python3"
    echo "      openSUSE:       sudo zypper install python3"
    exit 1
fi

# 1) the normal command:  genie <wish>
sudo install -m 755 "$SRC" "$BIN"
echo "  ✓ installed $BIN"

# 2) the magic: a link at the filesystem root, so typing  /genie <wish>
#    works in ANY shell (bash, zsh, fish) — the shell just runs the path /genie.
if sudo ln -sf "$BIN" /genie 2>/dev/null; then
    echo "  ✓ created /genie  →  you can now type: /genie install teams for me"
else
    echo "  ⚠ couldn't create /genie (read-only root?). Plain 'genie ...' still works."
fi

echo
echo "  next steps:"
echo "    genie setup     # connect a free AI provider (2 min)"
echo "    /genie how much disk space do i have"
echo
