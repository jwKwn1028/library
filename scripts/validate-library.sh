#!/usr/bin/env bash

set -euo pipefail

validation_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
library_root=$(cd -- "$validation_script_dir/.." && pwd)

cd -- "$library_root"
exec python3 -m paperlib.validation --root "$library_root" "$@"
