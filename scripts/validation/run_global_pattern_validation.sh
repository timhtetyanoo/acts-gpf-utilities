#!/usr/bin/env bash
#
# Runs the muon global pattern finder over the configured samples and writes
# the pattern files for the offline validation. Finished cases are skipped, so
# the script can be re-run after adding a sample or an implementation.
#
# GPF_DRIVER selects the runner (default cpp):
#   cpp     bin/ActsUnitTestGlobalPatternFinderData
#   python  Examples/Scripts/Python/muon_global_pattern_finder.py (Sequencer)
#
# GPF_IMPLEMENTATIONS is which algorithm is run (cpu now, later cpu cuda), not
# which runner. Timing belongs in scripts/benchmark/, not here.
#
# Optional:
#   ACTS_BUILD_DIR        build directory
#                         (default: <this repo>/../acts/build)
#   ACTS_SOURCE_DIR       ACTS source, python driver only
#                         (default: <this repo>/../acts)
#   GPF_DRIVER            cpp | python                 (default: cpp)
#   GPF_TAG_SUFFIX        appended to the file names
#   GPF_DATA_DIR          n-tuples & tracking geometry (default: <this repo>/data)
#   GPF_OUT_DIR           output directory             (default: <this repo>/gpf_validation)
#   GPF_GEOMETRY          tracking geometry json
#   GPF_SAMPLES           samples                      (default: "PG0")
#   GPF_IMPLEMENTATIONS   algorithms                   (default: "cpu")
#   GPF_MAX_EVENTS        events per case              (default: 500)
#   GPF_<SAMPLE>_NTUPLE   n-tuple of that sample
#   GPF_FORCE             1 to rerun finished cases
#
# @note Development tooling for the local validation of the example. It is not
#       meant to be part of an upstream pull request.

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
# shellcheck source=../gpf_common.sh
source "${script_dir}/../gpf_common.sh"

driver="$(gpf_driver)"
source_dir="$(cd -- "${ACTS_SOURCE_DIR:-${repo_root}/../acts}" && pwd)"
build_dir="$(cd -- "${ACTS_BUILD_DIR:-${source_dir}/build}" && pwd)"
data_dir="${GPF_DATA_DIR:-${repo_root}/data}"
out_dir="${GPF_OUT_DIR:-${repo_root}/gpf_validation}"
geometry="${GPF_GEOMETRY:-${data_dir}/ActsTrackingGeometry.json}"
executable="${build_dir}/bin/ActsUnitTestGlobalPatternFinderData"
finder_script="${source_dir}/Examples/Scripts/Python/muon_global_pattern_finder.py"
finder_python="${GPF_PYTHON:-python3}"
max_events="${GPF_MAX_EVENTS:-500}"
export ACTS_SEQUENCER_DISABLE_FPEMON="${ACTS_SEQUENCER_DISABLE_FPEMON:-1}"

read -r -a samples <<<"${GPF_SAMPLES:-PG0}"
read -r -a implementations <<<"${GPF_IMPLEMENTATIONS:-cpu}"

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
if [[ ! -f "${geometry}" ]]; then
  echo "Tracking geometry not found: ${geometry}" >&2
  exit 1
fi

mkdir -p -- "${out_dir}/logs"

# @brief Runs one sample with one implementation
run_case() {
  local sample="$1"
  local implementation="$2"
  local ntuple="$3"
  local tag="${sample}_${implementation}${GPF_TAG_SUFFIX:-}"
  local output="${out_dir}/patterns_${tag}.root"
  local log="${out_dir}/logs/${tag}.log"

  if [[ -f "${output}" && "${GPF_FORCE:-0}" != "1" ]]; then
    echo "Patterns already exist, skipping: ${tag}"
    return
  fi

  echo "Running ${tag} (${driver})"
  if [[ "${driver}" == "cpp" ]]; then
    ACTS_GPF_NTUPLE="${ntuple}" \
    ACTS_GPF_GEOMETRY="${geometry}" \
    ACTS_GPF_OUTPUT="${output}" \
    ACTS_GPF_MAX_EVENTS="${max_events}" \
    ACTS_GPF_LOG_LEVEL="${GPF_LOG_LEVEL:-INFO}" \
    ACTS_GPF_IMPLEMENTATION="${implementation}" \
      "${executable}" --log_level=message --report_level=no --color_output=no \
      >"${log}" 2>&1
  else
    PYTHONPATH="${build_dir}/python:${PYTHONPATH:-}" \
      "${finder_python}" "${finder_script}" \
        --input "${ntuple}" \
        --geometry "${geometry}" \
        --output "${output}" \
        --nEvents "${max_events}" \
        --threads 1 \
        --logLevel "${GPF_LOG_LEVEL:-INFO}" \
      >"${log}" 2>&1
  fi

  if [[ ! -f "${output}" ]]; then
    echo "No pattern file was written for ${tag}, see ${log}" >&2
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
    run_case "${sample}" "${implementation}" "${ntuple}"
  done
done

echo
echo "Pattern files in ${out_dir}:"
ls -1 -- "${out_dir}"/patterns_*.root
