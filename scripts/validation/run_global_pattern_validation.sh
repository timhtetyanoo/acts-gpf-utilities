#!/usr/bin/env bash
#
# Runs the muon global pattern finder over the configured samples and keeps the
# resulting pattern files for the offline validation. Finished cases are skipped,
# so the script can be re-run after adding a sample or an implementation.
#
# Required:
#   ACTS_BUILD_DIR        build directory holding bin/ActsUnitTestGlobalPatternFinderData
#   GPF_DATA_DIR          directory holding the n-tuples & the tracking geometry
#
# Optional:
#   GPF_OUT_DIR           output directory                 (default: ${GPF_DATA_DIR}/gpf_validation)
#   GPF_GEOMETRY          tracking geometry json           (default: ${GPF_DATA_DIR}/ActsTrackingGeometry.json)
#   GPF_SAMPLES           samples to process               (default: "PG0 PG200")
#   GPF_IMPLEMENTATIONS   implementations to run           (default: "cpu")
#   GPF_MAX_EVENTS        events per case                  (default: all)
#   GPF_<SAMPLE>_NTUPLE   n-tuple of that sample           (default: ${GPF_DATA_DIR}/ParticleGun_MU<pile-up>.root)
#   GPF_FORCE             set to 1 to rerun finished cases
#
# @note Development tooling for the local validation of the example. It is not
#       meant to be part of an upstream pull request.

set -Eeuo pipefail

build_dir="${ACTS_BUILD_DIR:?ACTS_BUILD_DIR is not set}"
data_dir="${GPF_DATA_DIR:?GPF_DATA_DIR is not set}"
out_dir="${GPF_OUT_DIR:-${data_dir}/gpf_validation}"
geometry="${GPF_GEOMETRY:-${data_dir}/ActsTrackingGeometry.json}"
executable="${build_dir}/bin/ActsUnitTestGlobalPatternFinderData"

read -r -a samples <<<"${GPF_SAMPLES:-PG0 PG200}"
read -r -a implementations <<<"${GPF_IMPLEMENTATIONS:-cpu}"

if [[ ! -x "${executable}" ]]; then
  echo "Executable not found: ${executable}" >&2
  exit 1
fi
if [[ ! -f "${geometry}" ]]; then
  echo "Tracking geometry not found: ${geometry}" >&2
  exit 1
fi

mkdir -p -- "${out_dir}/logs"

# @brief Returns the n-tuple of the sample, honouring a GPF_<SAMPLE>_NTUPLE override
ntuple_for() {
  local sample="$1"
  local override="GPF_${sample}_NTUPLE"
  local fallback
  case "${sample}" in
    PG0) fallback="${data_dir}/ParticleGun_MU0.root" ;;
    PG200) fallback="${data_dir}/ParticleGun_MU200.root" ;;
    *) fallback="${data_dir}/${sample}.root" ;;
  esac
  printf '%s' "${!override:-${fallback}}"
}

# @brief Runs one sample with one implementation
run_case() {
  local sample="$1"
  local implementation="$2"
  local ntuple="$3"
  local tag="${sample}_${implementation}"
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
  ACTS_GPF_MAX_EVENTS="${GPF_MAX_EVENTS:-}" \
  ACTS_GPF_IMPLEMENTATION="${implementation}" \
    "${executable}" --log_level=message --report_level=no --color_output=no \
    2>&1 | tee -- "${log}"

  if [[ ! -f "${output}" ]]; then
    echo "No pattern file was written for ${tag}, see ${log}" >&2
    exit 1
  fi
}

for sample in "${samples[@]}"; do
  ntuple="$(ntuple_for "${sample}")"
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
