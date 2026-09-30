#!/usr/bin/env bash
#
# Runs the muon global pattern finder over the configured samples and keeps the
# resulting pattern files for the offline validation. Finished cases are skipped,
# so the script can be re-run after adding a sample or an implementation.
#
# Two drivers produce the same pattern file. GPF_DRIVER picks between them:
#
#   python  Examples/Scripts/Python/muon_global_pattern_finder.py, run through
#           the Sequencer. Threads, an event offset and a per algorithm timing
#           file come with it, and configuration is a command line rather than a
#           rebuild. Needs the python bindings in the build and ACTS_SOURCE_DIR
#   test    bin/ActsUnitTestGlobalPatternFinderData, a Boost test looping over
#           the events by hand. One thread, no timing, but it asserts on what it
#           finds and needs nothing but the build
#
# They should agree exactly. compare_patterns.py checks that:
#   compare_patterns.py patterns_PG0_test.root patterns_PG0_python.root
#
# Required:
#   ACTS_BUILD_DIR        build directory; for the python driver it also has to
#                         hold python/ with the bindings
#   ACTS_SOURCE_DIR       ACTS source tree            (python driver only)
#
# Optional:
#   GPF_DRIVER            python | test                    (default: python)
#   GPF_THREADS           threads of the sequencer         (default: 1)
#   GPF_PYTHON            interpreter ACTS was built against   (default: python3)
#   GPF_TAG_SUFFIX        appended to the file names, so that two runs of the
#                         same sample can be kept side by side and compared
#   GPF_DATA_DIR          n-tuples & tracking geometry     (default: <this repo>/data)
#   GPF_OUT_DIR           output directory                 (default: <this repo>/gpf_validation)
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

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
build_dir="${ACTS_BUILD_DIR:?ACTS_BUILD_DIR is not set}"
data_dir="${GPF_DATA_DIR:-${repo_root}/data}"
out_dir="${GPF_OUT_DIR:-${repo_root}/gpf_validation}"
geometry="${GPF_GEOMETRY:-${data_dir}/ActsTrackingGeometry.json}"
driver="${GPF_DRIVER:-python}"
executable="${build_dir}/bin/ActsUnitTestGlobalPatternFinderData"
finder_script="${ACTS_SOURCE_DIR:-}/Examples/Scripts/Python/muon_global_pattern_finder.py"
# the bindings are a compiled extension and import only under the interpreter
# ACTS was built against
python="${GPF_PYTHON:-python3}"

read -r -a samples <<<"${GPF_SAMPLES:-PG0 PG200}"
read -r -a implementations <<<"${GPF_IMPLEMENTATIONS:-cpu}"

case "${driver}" in
  test)
    if [[ ! -x "${executable}" ]]; then
      echo "Executable not found: ${executable}" >&2
      exit 1
    fi
    ;;
  python)
    if [[ -z "${ACTS_SOURCE_DIR:-}" ]]; then
      echo "ACTS_SOURCE_DIR is not set, needed by the python driver" >&2
      exit 1
    fi
    if [[ ! -f "${finder_script}" ]]; then
      echo "Run script not found: ${finder_script}" >&2
      exit 1
    fi
    # the bindings are an option of the build, so say so here rather than
    # letting the import fail inside the script
    if [[ ! -d "${build_dir}/python" ]]; then
      echo "No python bindings in ${build_dir}; configure ACTS with them or" >&2
      echo "use GPF_DRIVER=test" >&2
      exit 1
    fi
    ;;
  *)
    echo "GPF_DRIVER has to be python or test, not ${driver}" >&2
    exit 1
    ;;
esac
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
  local tag="${sample}_${implementation}${GPF_TAG_SUFFIX:-}"
  local output="${out_dir}/patterns_${tag}.root"
  local log="${out_dir}/logs/${tag}.log"

  if [[ -f "${output}" && "${GPF_FORCE:-0}" != "1" ]]; then
    echo "Patterns already exist, skipping: ${tag}"
    return
  fi

  echo "Running ${tag} with the ${driver} driver"
  if [[ "${driver}" == "python" ]]; then
    # the bindings live in the build, the script in the source tree
    PYTHONPATH="${build_dir}/python:${PYTHONPATH:-}" \
      "${python}" "${finder_script}" \
        --input "${ntuple}" \
        --geometry "${geometry}" \
        --output "${output}" \
        --nEvents "${GPF_MAX_EVENTS:-0}" \
        --threads "${GPF_THREADS:-1}" \
        --timingDir "${out_dir}/logs" \
        --timingFile "timing_${tag}.csv" \
      2>&1 | tee -- "${log}"
  else
    ACTS_GPF_NTUPLE="${ntuple}" \
    ACTS_GPF_GEOMETRY="${geometry}" \
    ACTS_GPF_OUTPUT="${output}" \
    ACTS_GPF_MAX_EVENTS="${GPF_MAX_EVENTS:-}" \
    ACTS_GPF_IMPLEMENTATION="${implementation}" \
      "${executable}" --log_level=message --report_level=no --color_output=no \
      2>&1 | tee -- "${log}"
  fi

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
