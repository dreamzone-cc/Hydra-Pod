#!/usr/bin/env bash
# Install the vendored opus-manager skill and the /hydra-pod command into ~/.claude,
# and link hydra-pod-connect and hydra-pod-dispatch into ~/.local/bin (never replacing an unrelated file).
# usage: install.sh [--force]
# Without --force an existing, different file is reported and left alone.
# With --force it is first moved to ~/.claude/backups/hydra-pod/<timestamp>/.
# Backups must live outside skills/ and commands/: Claude Code loads every skill
# folder there, so a backup copy would show up as a duplicate skill.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
force=${1:-}
stamp=$(date +%Y%m%d-%H%M%S)
claude=${CLAUDE_HOME:-$HOME/.claude}
backup_dir=$claude/backups/hydra-pod/$stamp

install_item() {  # src dest backup-name
  local src=$1 dst=$2 name=$3
  if [ -e "$dst" ] && diff -rq "$src" "$dst" >/dev/null 2>&1; then
    echo "same     $dst"; return
  fi
  if [ -e "$dst" ]; then
    if [ "$force" != --force ]; then echo "differs  $dst (rerun with --force to replace; a backup is kept)"; return; fi
    mkdir -p "$backup_dir"; mv "$dst" "$backup_dir/$name"; echo "backup   $backup_dir/$name"
  fi
  mkdir -p "$(dirname "$dst")"
  cp -R "$src" "$dst"; echo "install  $dst"
}

install_item "$here/skill/opus-manager" "$claude/skills/opus-manager" skill-opus-manager
install_item "$here/claude/commands/hydra-pod.md" "$claude/commands/hydra-pod.md" hydra-pod.md

# hydra-pod-connect and hydra-pod-dispatch on PATH: symlinks to this checkout, so updates need no reinstall.
bindir=${HYDRA_POD_BIN_DIR:-${OM_BIN_DIR:-$HOME/.local/bin}}  # legacy name OM_BIN_DIR
mkdir -p "$bindir"
for tool in hydra-pod-connect hydra-pod-dispatch; do
  link=$bindir/$tool
  if [ -L "$link" ] && [ "$(readlink -f "$link")" = "$here/bin/$tool" ]; then
    echo "same     $link"
  elif [ -e "$link" ] || [ -L "$link" ]; then
    echo "differs  $link exists and is not this checkout's $tool (left unchanged)"
  else
    ln -s "$here/bin/$tool" "$link"; echo "install  $link -> $here/bin/$tool"
  fi
done
case ":$PATH:" in *":$bindir:"*) ;; *) echo "note     $bindir is not on PATH";; esac
echo "done. Restart Claude Code if /hydra-pod or the skill does not appear."
