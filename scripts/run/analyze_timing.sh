#!/usr/bin/env bash
#
# The analysis of the timing of a run: the summary, the table of every event and
# the figure. It never runs the finder. run_finder.sh calls it at its end; run it
# alone to redo the analysis of the timing files that are already there.
#
#   analyze_timing.sh --name cpu_pg0_all
#   analyze_timing.sh --config configs/cpu_pg0_all.conf
#
# Reads  results/<name>/timing/repetitions/timing_r*.csv
# Writes results/<name>/timing/summary.csv, events.csv and event_timing.png
#
# Settings (flags are listed in scripts/gpf_common.sh):
#   GPF_NAME          name of the run                  (required)
#   GPF_RESULTS_DIR   where the runs are kept          (default: <this repo>/results)
#   PYTHON            interpreter for the analysis     (default: python3 of the shell)

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
# shellcheck source=../gpf_common.sh
source "${script_dir}/../gpf_common.sh"
gpf_parse_args "$@"

name="${GPF_NAME:-}"
run_dir="$(gpf_run_dir "${repo_root}")"
python="$(gpf_python)"
timing_dir="${run_dir}/timing"

if ! compgen -G "${timing_dir}/repetitions/timing_r*.csv" >/dev/null; then
  echo "No timing files in ${timing_dir}/repetitions" >&2
  echo "Run scripts/run/run_finder.sh first." >&2
  exit 1
fi

"${python}" "${script_dir}/aggregate_event_timing.py" \
  "${timing_dir}/repetitions" --name "${name}" --output-dir "${timing_dir}"
"${python}" "${script_dir}/plot_event_timing.py" \
  "${timing_dir}/events.csv" --output "${timing_dir}/event_timing.png"
