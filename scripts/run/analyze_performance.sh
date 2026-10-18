#!/usr/bin/env bash
#
# The analysis of the performance of a run: the summary, the table of every event
# and the figure. It never runs the finder. run_finder.sh calls it at its end; run
# it alone to redo the analysis of the files that are already there.
#
#   analyze_performance.sh --name cpu_pg0_all
#   analyze_performance.sh --config configs/cpu_pg0.conf
#
# Reads  results/<name>/performance/repetitions/: timing_r*.csv, and process_r*.txt
#        and gpu_r*.csv where they were recorded
# Writes results/<name>/performance/summary.csv, events.csv and event_times.png
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
performance_dir="${run_dir}/performance"

if ! compgen -G "${performance_dir}/repetitions/timing_r*.csv" >/dev/null; then
  echo "No timing files in ${performance_dir}/repetitions" >&2
  echo "Run scripts/run/run_finder.sh first." >&2
  exit 1
fi

"${python}" "${script_dir}/aggregate_performance.py" \
  "${performance_dir}/repetitions" --name "${name}" \
  --output-dir "${performance_dir}" --logs "${run_dir}/logs"
"${python}" "${script_dir}/plot_performance.py" \
  "${performance_dir}/events.csv" --output "${performance_dir}/event_times.png"
