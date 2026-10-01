#!/usr/bin/env bash
#
# Runs bin/ActsUnitTestGlobalPatternFinderData over the configured samples and
# writes the pattern files for the offline validation. Finished cases are
# skipped, so the script can be re-run after adding a sample.
#
# GPF_IMPLEMENTATION labels which algorithm was run and goes into the file
# names. One run produces one implementation; scripts/compare/ puts two runs
# side by side.
#
# Optional:
#   ACTS_BUILD_DIR        build directory
#                         (default: <this repo>/../acts/build)
#   ACTS_SOURCE_DIR       ACTS source (default: <this repo>/../acts)
#   GPF_TAG_SUFFIX        appended to the file names
#   GPF_DATA_DIR          n-tuples & tracking geometry (default: <this repo>/data)
#   GPF_OUT_DIR           output directory
#                         (default: <this repo>/gpf_validation/${GPF_IMPLEMENTATION})
#   GPF_GEOMETRY          tracking geometry json
#   GPF_SAMPLES           samples                      (default: "PG0")
#   GPF_IMPLEMENTATION    label of the algorithm       (default: cpu)
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

source_dir="$(cd -- "${ACTS_SOURCE_DIR:-${repo_root}/../acts}" && pwd)"
build_dir="$(cd -- "${ACTS_BUILD_DIR:-${source_dir}/build}" && pwd)"
data_dir="${GPF_DATA_DIR:-${repo_root}/data}"
implementation="${GPF_IMPLEMENTATION:-cpu}"
out_dir="${GPF_OUT_DIR:-${repo_root}/gpf_validation/${implementation}}"
geometry="${GPF_GEOMETRY:-${data_dir}/ActsTrackingGeometry.json}"
executable="${build_dir}/bin/ActsUnitTestGlobalPatternFinderData"
max_events="${GPF_MAX_EVENTS:-500}"
export ACTS_SEQUENCER_DISABLE_FPEMON="${ACTS_SEQUENCER_DISABLE_FPEMON:-1}"

read -r -a samples <<<"${GPF_SAMPLES:-PG0}"

if [[ ! -x "${executable}" ]]; then
  echo "Executable not found: ${executable}" >&2
  exit 1
fi
if [[ ! -f "${geometry}" ]]; then
  echo "Tracking geometry not found: ${geometry}" >&2
  exit 1
fi

mkdir -p -- "${out_dir}/logs"

# @brief Runs one sample
run_case() {
  local sample="$1"
  local ntuple="$2"
  local tag="${sample}_${implementation}${GPF_TAG_SUFFIX:-}"
  local output="${out_dir}/patterns_${tag}.root"
  local log="${out_dir}/logs/${tag}.log"

  if [[ -f "${output}" && "${GPF_FORCE:-0}" != "1" ]]; then
    echo "Patterns already exist, skipping: ${tag}"
    return
  fi

  echo "Running ${tag}"
  ACTS_GPF_NTUPLE="${ntuple}" \
  ACTS_GPF_GEOMETRY="${geometry}" \
  ACTS_GPF_OUTPUT="${output}" \
  ACTS_GPF_MAX_EVENTS="${max_events}" \
  ACTS_GPF_LOG_LEVEL="${GPF_LOG_LEVEL:-INFO}" \
    "${executable}" --log_level=message --report_level=no --color_output=no \
    >"${log}" 2>&1

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
  run_case "${sample}" "${ntuple}"
done

echo
echo "Pattern files in ${out_dir}:"
ls -1 -- "${out_dir}"/patterns_*.root
