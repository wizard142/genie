#!/usr/bin/env bash
# genie uninstaller
set -euo pipefail

echo "  removing genie..."
sudo rm -f /genie /usr/local/bin/genie
echo "  ✓ removed. (your config stays in ~/.config/genie — delete it if you want)"
