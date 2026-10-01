#!/usr/bin/env bash
#
# Times the muon global pattern finder. Nothing here reads or writes the
# validation outputs: no pattern ROOT file is produced, and finder logging is
# kept at WARNING so I/O does not enter the measurement.
#
# GPF_DRIVER selects the runner (default cpp):
#   cpp     data test, one row per event (totalTime_us, occupancy, nPatterns)
#   python  Sequencer, one total per component for the whole run
#
# GPF_IMPLEMENTATIONS is which algorithm is timed (cpu now, later cpu cuda).
# The two drivers write different csv shapes on purpose; the matching plotter
# is chosen below. A GPU comparison should use cpp, so the cost is a
# distribution over events rather than one Sequencer number.
#
# Optional:
#   ACTS_SOURCE_DIR   ACTS source tree             (default: <this repo>/../acts)
#   ACTS_BUILD_DIR    build directory              (default: ${ACTS_SOURCE_DIR}/build)
#   GPF_DRIVER        cpp | python                 (default: cpp)
#   GPF_DATA_DIR      n-tuples & tracking geometry (default: <this repo>/data)
#   GPF_OUT_DIR       output directory
#                     (default: <this repo>/gpf_timing/cpp or .../python)
#   GPF_GEOMETRY      tracking geometry json
#   GPF_SAMPLES       samples                      (default: "PG0")
#   GPF_IMPLEMENTATIONS  algorithms                (default: "cpu")
#   GPF_EVENTS        events per run               (default: 500)
#   GPF_REPETITIONS   runs per case                (default: 3)
#   GPF_THREADS       Sequencer threads, python only (default: 1)
#   GPF_<SAMPLE>_NTUPLE  n-tuple of that sample
#   GPF_PYTHON        interpreter of the ACTS bindings (default: python3)
#   GPF_FORCE         1 to redo cases that already have a timing file
#
# @note One thread is the default on the python driver so the per-algorithm
#       time is the cost of the algorithm, not the throughput of the machine.
# @note ACTS_SEQUENCER_DISABLE_FPEMON=1 is exported so an FPE elsewhere in the
#       job cannot abort a python timing run.

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
# shellcheck source=../gpf_common.sh
source "${script_dir}/../gpf_common.sh"

driver="$(gpf_driver)"
source_dir="$(cd -- "${ACTS_SOURCE_DIR:-${repo_root}/../acts}" && pwd)"
build_dir="$(cd -- "${ACTS_BUILD_DIR:-${source_dir}/build}" && pwd)"
data_dir="${GPF_DATA_DIR:-${repo_root}/data}"
out_dir="${GPF_OUT_DIR:-${repo_root}/gpf_timing/${driver}}"
geometry="${GPF_GEOMETRY:-${data_dir}/ActsTrackingGeometry.json}"
executable="${build_dir}/bin/ActsUnitTestGlobalPatternFinderData"
finder_script="${source_dir}/Examples/Scripts/Python/muon_global_pattern_finder.py"
python="${GPF_PYTHON:-python3}"
export ACTS_SEQUENCER_DISABLE_FPEMON="${ACTS_SEQUENCER_DISABLE_FPEMON:-1}"

events="${GPF_EVENTS:-500}"
repetitions="${GPF_REPETITIONS:-3}"
threads="${GPF_THREADS:-1}"
read -r -a samples <<<"${GPF_SAMPLES:-PG0}"
read -r -a implementations <<<"${GPF_IMPLEMENTATIONS:-cpu}"

if [[ ! "${repetitions}" =~ ^[1-9][0-9]*$ ]]; then
  echo "GPF_REPETITIONS has to be a positive integer, not ${repetitions}" >&2
  exit 1
fi
if [[ ! -f "${geometry}" ]]; then
  echo "Tracking geometry not found: ${geometry}" >&2
  exit 1
fi
if [[ "${driver}" == "cpp" && ! -x "${executable}" ]]; then
  echo "Executable not found: ${executable}" >&2
  exit 1
fi
if [[ "${driver}" == "python" ]]; then
  if [[ ! -f "${finder_script}" ]]; then
    echo "Run script not found: ${finder_script}" >&2
    exit 1
  fi
  if [[ ! -d "${build_dir}/python" ]]; then
    echo "No python bindings in ${build_dir}; configure ACTS with them" >&2
    exit 1
  fi
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
  ACTS_GPF_IMPLEMENTATION="${implementation}" \
    "${executable}" --log_level=error --report_level=no --color_output=no \
    >"${log}" 2>&1
  if [[ ! -f "${timing}" ]]; then
    echo "No timing file was written for ${tag}, see ${log}" >&2
    exit 1
  fi
}

run_python() {
  local sample="$1"
  local implementation="$2"
  local ntuple="$3"
  local repetition="$4"
  local tag="${sample}_${implementation}_e${events}_t${threads}_r$(printf '%02d' "${repetition}")"
  local timing="${out_dir}/repetitions/timing_${tag}.csv"
  local log="${out_dir}/logs/${tag}.log"

  if [[ -f "${timing}" && "${GPF_FORCE:-0}" != "1" ]]; then
    echo "Timing already there, skipping: ${tag}"
    return
  fi
  echo "Timing ${tag} (python)"
  # no --output: writing patterns would put the writer into the Sequencer total
  PYTHONPATH="${build_dir}/python:${PYTHONPATH:-}" \
    "${python}" "${finder_script}" \
      --input "${ntuple}" \
      --geometry "${geometry}" \
      --nEvents "${events}" \
      --threads "${threads}" \
      --logLevel WARNING \
      --timingDir "${out_dir}/repetitions" \
      --timingFile "timing_${tag}.csv" \
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
  for implementation in "${implementations[@]}"; do
    for repetition in $(seq 1 "${repetitions}"); do
      if [[ "${driver}" == "cpp" ]]; then
        run_cpp "${sample}" "${implementation}" "${ntuple}" "${repetition}"
      else
        run_python "${sample}" "${implementation}" "${ntuple}" "${repetition}"
      fi
    done
  done
done

echo
echo "Collecting"
if [[ "${driver}" == "cpp" ]]; then
  "${python}" "${script_dir}/aggregate_event_timing.py" "${out_dir}/repetitions" \
    --output-dir "${out_dir}"
  "${python}" "${script_dir}/plot_event_timing.py" \
    "${out_dir}/event_timings.csv" --output "${out_dir}/plots/event_timing.png"
  echo
  echo "Output:  ${out_dir}"
  echo "Raw:     ${out_dir}/repetitions"
  echo "Summary: ${out_dir}/event_summary.csv"
  echo "Figure:  ${out_dir}/plots/event_timing.png"
else
  "${python}" "${script_dir}/collect_timing.py" "${out_dir}/repetitions" \
    --output "${out_dir}/timings.csv"
  "${python}" "${script_dir}/plot_timing.py" "${out_dir}/timings.csv" \
    --output "${out_dir}/plots/timing.png"
  echo
  echo "Output:  ${out_dir}"
  echo "Raw:     ${out_dir}/repetitions"
  echo "Table:   ${out_dir}/timings.csv"
  echo "Figure:  ${out_dir}/plots/timing.png"
fi
