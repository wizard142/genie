# Offline wishes and command references

Run `genie wishes` to browse the built-in examples, or `genie -n <wish>` to preview a command.

The expansion adds 54 fixed diagnostic wishes plus parameterized file, DNS,
connectivity, service, and package diagnostic wishes. Phrase variants are matched
without an AI key. Offline describes translation: package downloads, DNS, and
pings still need network access. Optional tools and administrative privileges may
be needed. Missing optional tools produce a prerequisite message, not an automatic
installation. Application package availability remains dependent on configured repositories.

## Examples

| Area | Wishes |
| --- | --- |
| Packages | list installed packages; check for updates; search for package editor |
| Files | create folder Project Notes; read file README.md; sha256 file README.md; find files *.py; size of Project Notes |
| Hardware | show cpu info; show disks; show usb devices; swap usage; uptime |
| Networking | routing table; dns servers; listening ports; wifi status; resolve example.com; ping example.com |
| Services | show services; status of service sshd; restart service sshd; system errors |
| Development | git status; git branches; recent commits; docker containers; docker disk usage |
| Linux extras | flatpak apps; flatpak remotes; snap packages |
| Windows extras | wsl distros; power plans; installed windows updates; windows features |

## Platform details

Package diagnostic commands cover pacman, paru, yay, APT, DNF, DNF5, Zypper,
APK, XBPS, Portage, WinGet, Chocolatey, and Scoop. DNF5 is preferred over DNF
when present. openSUSE Tumbleweed uses `zypper dup`; Leap retains `zypper update`.
Service actions detect systemd, OpenRC, or runit. Minimal Alpine uses a plain
BusyBox-compatible process listing. Gentoo's installed-package listing requires
`qlist` (portage-utils); it is reported as missing if unavailable.

User-supplied file paths keep their capitalization and are quoted as shell data.
PowerShell file operations use literal paths. WinGet IDs are never reused as
Chocolatey/Scoop identifiers: unsupported aliases fall back to a package search.
Changes still require confirmation. No automatic yes flags were introduced.

This covers the existing distro families and their derivatives, not every Linux
OS or immutable/NixOS package workflow. Diagnostics are bounded to installed
tools and service managers. Windows commands target Windows PowerShell 5.1;
Windows behavior is tested with platform simulations, not a native Windows host.

## Documentation reviewed

Retrieved current official source documentation on 2026-10-06. Public wiki
sites were blocked by this environment's network policy, so official GitHub
source documentation was used instead. Arch's wiki and pacman upstream could
not be fetched: existing pacman command forms were retained, with simulated
regression tests, and are not claimed as freshly wiki-verified. No distro-wide
update or package installation was executed to test destructive operations.

| Official source | SHA-256 of retrieved document |
| --- | --- |
| [APT](https://github.com/Debian/apt/blob/main/doc/apt.8.xml) | `47c9efbf7dac9f208590575532bd23295c9429a3e35e0240820edfed3867521c` |
| [DNF5](https://github.com/rpm-software-management/dnf5/blob/main/doc/commands/upgrade.8.rst) | `f2e594dfb497e8a59d09f4f363027c16ba9ed0134561669d9af6a3ef6f4b7008` |
| [Zypper](https://github.com/openSUSE/zypper/blob/master/doc/zypper.8.txt) | `3e89cc7094706742678572d3f5489fb0c372c60fb33bb306a2de5597d85d5d53` |
| [APK](https://github.com/alpinelinux/apk-tools/blob/master/doc/apk-info.8.scd) | `f3e9e9a61c5d8ed3877045559d51e01ae62d50ccb052d2865ed59d8317511ce7` |
| [Void handbook](https://github.com/void-linux/void-docs/blob/master/src/xbps/index.md) | `61105ccc315e1c5350a5d3bc73aec98553a154e3f32cb08d66b0b33376218905` |
| [XBPS dry-run](https://github.com/void-linux/xbps/blob/master/bin/xbps-install/xbps-install.1) | `cedf87af3b82b6f31d6785b1f51c09626eb2b6c866016ed5dfff8664c62c716b` |
| [Portage](https://github.com/gentoo/portage/blob/master/man/emerge.1) | `6508275a4525593ee84cf54204fcab55b943b82d7948a8f2a05aa871ba0a5651` |
| [systemctl](https://github.com/systemd/systemd/blob/main/man/systemctl.xml) | `caca7b87ae3bc8730b070a38d814c698acf82c596df9cb47a58fc7510c7b765c` |
| [nmcli](https://github.com/NetworkManager/NetworkManager/blob/main/man/nmcli.xml) | `d64c3443d026cdaf953c5b873cfeb2e698086247e13ffa8d39d0942587d5be5e` |
| [WinGet list](https://github.com/MicrosoftDocs/windows-dev-docs/blob/docs/hub/package-manager/winget/list.md) | `414c3139fdf27edd5d92dc3890c10f19b8dca73f1232a31eb0a428a85a7f6cf2` |
| [WinGet upgrade](https://github.com/MicrosoftDocs/windows-dev-docs/blob/docs/hub/package-manager/winget/upgrade.md) | `03aded1eb0044233085ec7c110822155b8b0eecf7cafbd02e987bf1238aa449c` |
| [PowerShell 5.1 files](https://github.com/MicrosoftDocs/PowerShell-Docs/blob/main/reference/5.1/Microsoft.PowerShell.Management/Get-ChildItem.md) | `b3c21ccb7033bca8ecd3b12a28dee18068433796e10d56776f1ba20b8eb61702` |

## Validation

`python3 tests/run_tests.py` runs 48 tests, with subcases spanning Linux managers,
Windows fallbacks, service managers, missing tools, and argument quoting. Actual
Linux shell checks exercise file reads, hashes, file information, filename searches,
and folder sizes. API retry/failover tests continue to use a local mock server.
Native Windows and native installations of other distros remain untested.
