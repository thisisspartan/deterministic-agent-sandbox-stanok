#!/usr/bin/env bash
# gen_stacks.sh — generate the STACK REGISTRY from the per-stack TOML
# manifests in scripts/stacks/ (one manifest per stack).
#
#   bash scripts/gen_stacks.sh          — (re)generate:
#     scripts/stacks.generated.sh          the STACKS='...' assignment
#   bash scripts/gen_stacks.sh --check  — regenerate into a temp dir and
#     exit 0 iff the committed artifact is byte-identical (1 = drift,
#     printing which file drifted).
#
# Stacks are emitted in manifest filename sort order. The manifests use
# only strings; they are parsed with a small fixed sed parser (no TOML
# library).
#
# CC-155: the former domains.json/runtime.list outputs were dropped — nothing
# consumed them (only a test asserted their own generator's output), so they
# implied a manifest-governs-everything source of truth that did not exist.
# The registry is the ONE generated artifact with a consumer (run.sh:65).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACKS_DIR="$SCRIPT_DIR/stacks"
OUT_SH="$SCRIPT_DIR/stacks.generated.sh"

# --- tiny fixed TOML parser (strings, one per line) ---
# TOML basic strings: the only escape used by the manifests is `\\` (a
# literal backslash); unescape it so the emitted registry line is
# byte-identical to the value the manifest denotes.
toml_unescape() { sed 's/\\\\/\\/g'; }

toml_str() {  # $1=file $2=key -> the string value
  sed -n "s/^${2} = \"\\(.*\\)\"$/\\1/p" "$1" | toml_unescape
}

# --- collect manifests in filename sort order ---
manifests=()
for f in "$STACKS_DIR"/*.toml; do
  [ -e "$f" ] && manifests+=("$f")
done
[ "${#manifests[@]}" -gt 0 ] || {
  echo "gen_stacks.sh: no manifests in $STACKS_DIR" >&2
  exit 2
}
mapfile -t manifests < <(printf '%s\n' "${manifests[@]}" | sort)

generate() {  # $1=out .sh path
  local out_sh="$1"
  local lines=()
  local m ext glob nre trun srun pre i
  for m in "${manifests[@]}"; do
    ext="$(toml_str "$m" ext)"
    glob="$(toml_str "$m" test_glob)"
    nre="$(toml_str "$m" name_regex)"
    trun="$(toml_str "$m" test_runner)"
    srun="$(toml_str "$m" smoke_runner)"
    pre="$(toml_str "$m" preflight)"
    { [ -n "$ext" ] && [ -n "$glob" ] && [ -n "$nre" ] &&
      [ -n "$trun" ] && [ -n "$srun" ] && [ -n "$pre" ]; } || {
      echo "gen_stacks.sh: manifest $m is missing a required key" >&2
      exit 2
    }
    lines+=("${ext}|${glob}|${nre}|${trun}|${srun}|${pre}")
  done
  # STACKS='...' — the ONLY content of the generated .sh file
  {
    printf "STACKS='"
    for i in "${!lines[@]}"; do
      [ "$i" -gt 0 ] && printf '\n'
      printf '%s' "${lines[$i]}"
    done
    printf "'\n"
  } > "$out_sh"
}

case "${1:-}" in
  "")
    generate "$OUT_SH"
    ;;
  --check)
    tmp="$(mktemp -d "${TMPDIR:-/tmp}/gen_stacks.XXXXXX")"
    trap 'rm -rf "$tmp"' EXIT
    generate "$tmp/stacks.generated.sh"
    if ! cmp -s "$tmp/stacks.generated.sh" "$OUT_SH"; then
      echo "gen_stacks.sh: drift: stacks.generated.sh" >&2
      exit 1
    fi
    exit 0
    ;;
  *)
    echo "usage: gen_stacks.sh [--check]" >&2
    exit 2
    ;;
esac
