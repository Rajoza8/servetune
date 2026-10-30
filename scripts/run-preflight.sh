#!/usr/bin/env bash
# Run as an ordinary user on the GPU host. No installs, rentals, or paid calls.
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
: "${SERVETUNE_MODEL_REVISION:?Set SERVETUNE_MODEL_REVISION to the exact 40-character Glimmer Hub commit}"
: "${SERVETUNE_MAX_HOURS:?Set SERVETUNE_MAX_HOURS to your available after-hours allocation}"

run_dir="${1:?Usage: bash scripts/run-preflight.sh runs/your-fresh-run-name}"
data_dir="${SERVETUNE_DATA_DIR:-data/gsm8k}"
archive_path="${run_dir}.tar.gz"
if [[ -e "$run_dir" || -e "$archive_path" ]]; then
  echo "Choose a fresh run path; evidence will not be overwritten." >&2
  exit 2
fi

python3 -m servetune doctor
if [[ ! -e "$data_dir" ]]; then
  python3 -m servetune prepare-data --out "$data_dir"
fi

run_status=0
python3 -m servetune preflight \
  --data-dir "$data_dir" \
  --model-revision "$SERVETUNE_MODEL_REVISION" \
  --max-hours "$SERVETUNE_MAX_HOURS" \
  --out "$run_dir" || run_status=$?

if [[ -f "$run_dir/manifest.json" ]]; then
  python3 -m servetune export-run "$run_dir" --out "$archive_path"
  echo "Bring back this evidence bundle: $archive_path"
fi
echo "P3 is separate: this script makes no paid API calls. Read preflight.md for outstanding gates."
exit "$run_status"
