#!/usr/bin/env bash
# Compatibility wrapper: forwards all arguments to generate.sh (kept for older references).
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/generate.sh" "$@"
