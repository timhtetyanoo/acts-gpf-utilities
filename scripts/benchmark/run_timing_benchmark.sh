#!/usr/bin/env bash
#
# Times the muon global pattern finder through the Sequencer, following the
# pattern of Examples/Scripts/Benchmarking in ACTS: loop over the conditions,
# let the Sequencer write its timing file for each one, and collect the rows
# into a single csv that a plotter reads.
#
# This is the python half of the benchmarking. It measures the algorithm as the
# framework sees it, one number per component per run, and it is deliberately
# separate from the validation chain, which uses the C++ test and measures
# differently. Nothing here reads or writes the validation outputs.
#
# Required:
#   ACTS_BUILD_DIR    build directory holding python/ with the bindings
#   ACTS_SOURCE_DIR   ACTS source tree holding the run script
#
# Optional:
#   GPF_DATA_DIR      n-tuples & tracking geometry   (default: <this repo>/data)
#   GPF_OUT_DIR       output directory               (default: <this repo>/gpf_timing)
#   GPF_GEOMETRY      tracking geometry json         (default: ${GPF_DATA_DIR}/ActsTrackingGeometry.json)
#   GPF_SAMPLES       samples to time                (default: "PG0 PG200")
#   GPF_EVENTS        events per run                 (default: 1000)
#   GPF_REPETITIONS   runs per case                  (default: 3)
#   GPF_THREADS       sequencer threads              (default: 1)
#   GPF_<SAMPLE>_NTUPLE  n-tuple of that sample
#   GPF_PYTHON        interpreter ACTS was built against   (default: python3)
#   GPF_FORCE         1 to redo cases that already have a timing file
#
# @note One thread is the default on purpose. The per algorithm time only means
#       anything on a single thread; more of them measure the throughput of the
#       machine rather than the cost of the algorithm.

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
build_dir="${ACTS_BUILD_DIR:?ACTS_BUILD_DIR is not set}"
source_dir="${ACTS_SOURCE_DIR:?ACTS_SOURCE_DIR is not set}"
data_dir="${GPF_DATA_DIR:-${repo_root}/data}"
out_dir="${GPF_OUT_DIR:-${repo_root}/gpf_timing}"
geometry="${GPF_GEOMETRY:-${data_dir}/ActsTrackingGeometry.json}"
finder_script="${source_dir}/Examples/Scripts/Python/muon_global_pattern_finder.py"
python="${GPF_PYTHON:-python3}"

events="${GPF_EVENTS:-1000}"
repetitions="${GPF_REPETITIONS:-3}"
threads="${GPF_THREADS:-1}"
read -r -a samples <<<"${GPF_SAMPLES:-PG0 PG200}"

if [[ ! -f "${finder_script}" ]]; then
  echo "Run script not found: ${finder_script}" >&2
  exit 1
fi
# the bindings are an option of the build, so say so here rather than letting
# the import fail inside the script
if [[ ! -d "${build_dir}/python" ]]; then
  echo "No python bindings in ${build_dir}; configure ACTS with them" >&2
  exit 1
fi
if [[ ! -f "${geometry}" ]]; then
  echo "Tracking geometry not found: ${geometry}" >&2
  exit 1
fi
if [[ ! "${repetitions}" =~ ^[1-9][0-9]*$ ]]; then
  echo "GPF_REPETITIONS has to be a positive integer, not ${repetitions}" >&2
  exit 1
fi

mkdir -p -- "${out_dir}/runs" "${out_dir}/logs"

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

for sample in "${samples[@]}"; do
  ntuple="$(ntuple_for "${sample}")"
  if [[ ! -f "${ntuple}" ]]; then
    echo "Missing n-tuple for ${sample}: ${ntuple}" >&2
    exit 1
  fi
  for repetition in $(seq 1 "${repetitions}"); do
    tag="${sample}_e${events}_t${threads}_r$(printf '%02d' "${repetition}")"
    timing="${out_dir}/runs/timing_${tag}.csv"
    if [[ -f "${timing}" && "${GPF_FORCE:-0}" != "1" ]]; then
      echo "Timing already there, skipping: ${tag}"
      continue
    fi
    echo "Timing ${tag}"
    # the patterns are not written: this run measures, it does not validate,
    # and writing them would put the writer's time into the job
    PYTHONPATH="${build_dir}/python:${PYTHONPATH:-}" \
      "${python}" "${finder_script}" \
        --input "${ntuple}" \
        --geometry "${geometry}" \
        --nEvents "${events}" \
        --threads "${threads}" \
        --timingDir "${out_dir}/runs" \
        --timingFile "timing_${tag}.csv" \
      2>&1 | tee -- "${out_dir}/logs/${tag}.log"

    if [[ ! -f "${timing}" ]]; then
      echo "No timing file was written for ${tag}, see ${out_dir}/logs/${tag}.log" >&2
      exit 1
    fi
  done
done

echo
echo "Collecting"
"${python}" "${script_dir}/collect_timing.py" "${out_dir}/runs" \
  --output "${out_dir}/timings.csv"
"${python}" "${script_dir}/plot_timing.py" "${out_dir}/timings.csv" \
  --output "${out_dir}/timing.png"

echo
echo "Timing files: ${out_dir}/runs"
echo "Collected:    ${out_dir}/timings.csv"
echo "Figure:       ${out_dir}/timing.png"
