#!/usr/bin/env bash
# gen_stacks.sh — generate the STACK REGISTRY artifacts from the per-stack
# TOML manifests in scripts/stacks/ (one manifest per stack).
#
#   bash scripts/gen_stacks.sh          — (re)generate:
#     scripts/stacks.generated.sh          the STACKS='...' assignment
#     scripts/stacks.generated/domains.json  sorted union of all domains
#     scripts/stacks.generated/runtime.list  runtime lines, manifest order
#   bash scripts/gen_stacks.sh --check  — regenerate into a temp dir and
#     exit 0 iff the committed artifacts are byte-identical (1 = drift,
#     printing which file drifted).
#
# Stacks are emitted in manifest filename sort order. The manifests use
# only strings and arrays of strings; they are parsed with a small fixed
# sed parser (no TOML library).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACKS_DIR="$SCRIPT_DIR/stacks"
OUT_SH="$SCRIPT_DIR/stacks.generated.sh"
OUT_DIR="$SCRIPT_DIR/stacks.generated"

# --- tiny fixed TOML parser (strings + arrays of strings, one line each) ---
# TOML basic strings: the only escape used by the manifests is `\\` (a
# literal backslash); unescape it so the emitted registry line is
# byte-identical to the value the manifest denotes.
toml_unescape() { sed 's/\\\\/\\/g'; }

toml_str() {  # $1=file $2=key -> the string value
  sed -n "s/^${2} = \"\\(.*\\)\"$/\\1/p" "$1" | toml_unescape
}

toml_arr() {  # $1=file $2=key -> one element per line
  local inner
  inner="$(sed -n "s/^${2} = \\[\\(.*\\)\\]$/\\1/p" "$1")"
  [ -n "$inner" ] || return 0
  printf '%s\n' "$inner" | sed 's/", "/\n/g' | sed 's/^"//; s/"$//' | toml_unescape
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

generate() {  # $1=out .sh path  $2=out dir
  local out_sh="$1" out_dir="$2"
  mkdir -p "$out_dir"
  local lines=() doms=() runtimes=()
  local m ext glob nre trun srun pre d r i j
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
    while IFS= read -r d; do
      [ -n "$d" ] && doms+=("$d")
    done < <(toml_arr "$m" domains)
    while IFS= read -r r; do
      [ -n "$r" ] && runtimes+=("$r")
    done < <(toml_arr "$m" runtime)
  done
  # 1) STACKS='...' — the ONLY content of the generated .sh file
  {
    printf "STACKS='"
    for i in "${!lines[@]}"; do
      [ "$i" -gt 0 ] && printf '\n'
      printf '%s' "${lines[$i]}"
    done
    printf "'\n"
  } > "$out_sh"
  # 2) domains.json — sorted union
  local sorted=()
  if [ "${#doms[@]}" -gt 0 ]; then
    mapfile -t sorted < <(printf '%s\n' "${doms[@]}" | sort -u)
  fi
  {
    if [ "${#sorted[@]}" -eq 0 ]; then
      printf '[]\n'
    else
      printf '[\n'
      for j in "${!sorted[@]}"; do
        [ "$j" -gt 0 ] && printf ',\n'
        printf '  "%s"' "${sorted[$j]}"
      done
      printf '\n]\n'
    fi
  } > "$out_dir/domains.json"
  # 3) runtime.list — manifest order, one per line
  if [ "${#runtimes[@]}" -gt 0 ]; then
    printf '%s\n' "${runtimes[@]}" > "$out_dir/runtime.list"
  else
    : > "$out_dir/runtime.list"
  fi
}

case "${1:-}" in
  "")
    generate "$OUT_SH" "$OUT_DIR"
    ;;
  --check)
    tmp="$(mktemp -d "${TMPDIR:-/tmp}/gen_stacks.XXXXXX")"
    trap 'rm -rf "$tmp"' EXIT
    generate "$tmp/stacks.generated.sh" "$tmp/stacks.generated"
    rc=0
    for rel in "stacks.generated.sh" "stacks.generated/domains.json" \
               "stacks.generated/runtime.list"; do
      if ! cmp -s "$tmp/$rel" "$SCRIPT_DIR/$rel"; then
        echo "gen_stacks.sh: drift: $rel" >&2
        rc=1
      fi
    done
    exit "$rc"
    ;;
  *)
    echo "usage: gen_stacks.sh [--check]" >&2
    exit 2
    ;;
esac
