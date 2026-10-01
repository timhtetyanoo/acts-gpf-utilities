#!/usr/bin/env bash
#
# Times the muon global pattern finder. Nothing here reads or writes the
# validation outputs: no pattern ROOT file is produced, and finder logging is
# kept at WARNING so I/O does not enter the measurement.
#
# Runs bin/ActsUnitTestGlobalPatternFinderData, which times each call of the
# finder on its own and writes one row per event.
#
# GPF_IMPLEMENTATION labels which algorithm was timed and goes into the file
# names. One run times one implementation; scripts/compare/ puts two runs side
# by side.
#
# Optional:
#   ACTS_SOURCE_DIR   ACTS source tree             (default: <this repo>/../acts)
#   ACTS_BUILD_DIR    build directory              (default: ${ACTS_SOURCE_DIR}/build)
#   GPF_DATA_DIR      n-tuples & tracking geometry (default: <this repo>/data)
#   GPF_OUT_DIR       output directory
#                     (default: <this repo>/gpf_timing/${GPF_IMPLEMENTATION})
#   GPF_GEOMETRY      tracking geometry json
#   GPF_SAMPLES       samples                      (default: "PG0")
#   GPF_IMPLEMENTATION   label of the algorithm    (default: cpu)
#   GPF_EVENTS        events per run               (default: 500)
#   GPF_REPETITIONS   runs per case                (default: 3)
#   GPF_<SAMPLE>_NTUPLE  n-tuple of that sample
#   GPF_FORCE         1 to redo cases that already have a timing file
#   PYTHON            interpreter for the analysis (default: <this repo>/.venv/bin/python)

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
# shellcheck source=../gpf_common.sh
source "${script_dir}/../gpf_common.sh"

source_dir="$(cd -- "${ACTS_SOURCE_DIR:-${repo_root}/../acts}" && pwd)"
build_dir="$(cd -- "${ACTS_BUILD_DIR:-${source_dir}/build}" && pwd)"
data_dir="${GPF_DATA_DIR:-${repo_root}/data}"
implementation="${GPF_IMPLEMENTATION:-cpu}"
out_dir="${GPF_OUT_DIR:-${repo_root}/gpf_timing/${implementation}}"
geometry="${GPF_GEOMETRY:-${data_dir}/ActsTrackingGeometry.json}"
python="${PYTHON:-${repo_root}/.venv/bin/python}"
command -v "${python}" >/dev/null 2>&1 || python="python3"
executable="${build_dir}/bin/ActsUnitTestGlobalPatternFinderData"

events="${GPF_EVENTS:-500}"
repetitions="${GPF_REPETITIONS:-3}"
read -r -a samples <<<"${GPF_SAMPLES:-PG0}"

if [[ ! "${repetitions}" =~ ^[1-9][0-9]*$ ]]; then
  echo "GPF_REPETITIONS has to be a positive integer, not ${repetitions}" >&2
  exit 1
fi
if [[ ! -f "${geometry}" ]]; then
  echo "Tracking geometry not found: ${geometry}" >&2
  exit 1
fi
if [[ ! -x "${executable}" ]]; then
  echo "Executable not found: ${executable}" >&2
  exit 1
fi

mkdir -p -- "${out_dir}/repetitions" "${out_dir}/logs" "${out_dir}/plots"

run_cpp() {
  local sample="$1"
  local implementation="$2"
  local ntuple="$3"
  local repetition="$4"
  local tag="${sample}_${implementation}_r$(printf '%02d' "${repetition}")"
  local timing="${out_dir}/repetitions/timing_${tag}.csv"
  local log="${out_dir}/logs/${tag}.log"

  if [[ -f "${timing}" && "${GPF_FORCE:-0}" != "1" ]]; then
    echo "Timing already there, skipping: ${tag}"
    return
  fi
  echo "Timing ${tag} (cpp)"
  ACTS_GPF_NTUPLE="${ntuple}" \
  ACTS_GPF_GEOMETRY="${geometry}" \
  ACTS_GPF_MAX_EVENTS="${events}" \
  ACTS_GPF_TIMING="${timing}" \
  ACTS_GPF_LOG_LEVEL=WARNING \
    "${executable}" --log_level=error --report_level=no --color_output=no \
    >"${log}" 2>&1
  if [[ ! -f "${timing}" ]]; then
    echo "No timing file was written for ${tag}, see ${log}" >&2
    exit 1
  fi
}

for sample in "${samples[@]}"; do
  ntuple="$(gpf_ntuple_for "${data_dir}" "${sample}")"
  if [[ ! -f "${ntuple}" ]]; then
    echo "Missing n-tuple for ${sample}: ${ntuple}" >&2
    exit 1
  fi
  for repetition in $(seq 1 "${repetitions}"); do
    run_cpp "${sample}" "${implementation}" "${ntuple}" "${repetition}"
  done
done

echo
echo "Collecting"
"${python}" "${script_dir}/aggregate_event_timing.py" "${out_dir}/repetitions" \
  --output-dir "${out_dir}"
"${python}" "${script_dir}/plot_event_timing.py" \
  "${out_dir}/event_timings.csv" --output "${out_dir}/plots/event_timing.png"
echo
echo "Output:  ${out_dir}"
echo "Raw:     ${out_dir}/repetitions"
echo "Summary: ${out_dir}/event_summary.csv"
echo "Figure:  ${out_dir}/plots/event_timing.png"

