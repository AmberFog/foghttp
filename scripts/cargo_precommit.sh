#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${CARGO_HOME:-}" && -x "${CARGO_HOME}/bin/cargo" ]]; then
  exec "${CARGO_HOME}/bin/cargo" "$@"
fi

for candidate in "${HOME}"/Library/Caches/*/cargo/bin/cargo; do
  if [[ -x "${candidate}" ]]; then
    cache_root="$(dirname "$(dirname "$(dirname "${candidate}")")")"
    rustup_home="${cache_root}/rustup"
    if [[ -d "${rustup_home}" ]]; then
      export CARGO_HOME="${cache_root}/cargo"
      export RUSTUP_HOME="${rustup_home}"
    fi
    exec "${candidate}" "$@"
  fi
done

if [[ -x "${HOME}/.cargo/bin/cargo" ]]; then
  exec "${HOME}/.cargo/bin/cargo" "$@"
fi

if command -v cargo >/dev/null 2>&1; then
  exec cargo "$@"
fi

echo "cargo executable not found; install Rust or add cargo to PATH" >&2
exit 127
