#!/usr/bin/env bash
#
# Step 1 of 2: runs the muon global pattern finder and keeps what it produced.
# Step 2, scripts/validation/run_validation.sh, judges the patterns written here
# and never runs the finder.
#
# A run has a name, and everything it produces goes into results/<host>/<name>/. The
# name, the sample, the event count and the build to use are what a config file
# of one run holds:
#
#   run_finder.sh --config configs/cpu_pg0.conf
#   run_finder.sh --name cpu_test --sample PG0 --ntuple data/ParticleGun_MU0.root \
#     --geometry data/ActsTrackingGeometry_PG0.json --events 100 --repetitions 2
#
# Runs bin/ActsUnitTestGlobalPatternFinderData over the sample, several times,
# or with --backend cuda its GPU twin bin/ActsUnitTestCudaGlobalPatternFinderData,
# which needs a build with ACTS_BUILD_EXAMPLES_CUDA_GLOBAL_PATTERN_FINDER=ON; the
# GPU version is whichever the checkout of that build holds. The
# GPU run writes the same files; its timing has a column per stage of the GPU
# path besides the total.
# Each repetition times every call of the finder on its own and writes one row
# per event. The first repetition also writes the pattern file. The timer wraps
# the finder call only, so writing the patterns is not in the measurement; the
# finder logs at WARNING because its own messages are.
#
# A run always redoes everything and replaces what the same name held before:
# reusing an old timing would report numbers of a different build or load, and
# the validation of old patterns would no longer belong to them.
#
# Around each repetition, /usr/bin/time records the finder process's wall time,
# CPU time and peak memory, and for a GPU run nvidia-smi samples the GPU's
# utilisation, memory, power and clock every 200 ms. nvidia-smi sees the whole
# GPU, so another job on it shows up there.
#
# The analysis of the performance is scripts/run/analyze_performance.sh, which
# can be run alone.
#
# Writes into results/<host>/<name>/:
#   run_info.txt                  what was run: settings, ACTS revision, date
#   patterns.root                 the patterns, the input of step 2
#   performance/summary.csv       one row per repetition, input of the comparison
#   performance/events.csv        every event of every repetition
#   performance/event_times.png   cost against occupancy
#   performance/repetitions/      per repetition: timing_rNN.csv of the finder,
#                                 process_rNN.txt of /usr/bin/time and, on the
#                                 GPU, gpu_rNN.csv of nvidia-smi
#   logs/                    finder output of each repetition
#   profile/                 with GPF_PROFILE: seeds.csv, events.csv and their
#                            analysis, of the first repetition
#
# Settings (flags are listed in scripts/gpf_common.sh):
#   GPF_NAME          name of the run                  (required)
#   GPF_NTUPLE        space point n-tuple              (required)
#   GPF_GEOMETRY      tracking geometry json made with that n-tuple (required)
#   GPF_SAMPLE        label of the input, e.g. PG0     (default: the n-tuple's file name)
#   GPF_EVENTS        events per repetition            (a number or "all", default: 500)
#   GPF_REPETITIONS   timing repetitions               (default: 3)
#   GPF_PROFILE       1: the stages of the CPU finder into profile/, read by
#                     scripts/profile/analyze_profile.py. Needs the profiling
#                     build, -DACTS_GPF_PROFILE on the gpf-profiling branch
#   GPF_BACKEND       cpu or cuda                      (default: cpu)
#   GPF_WORKSPACE_MB  GPU memory in MiB for the patterns of an event; an event
#                     that needs more keeps the best ones and reports an
#                     overflow (default: half of the free device memory)
#   GPF_SEED_FROM_MDT 1: MDT hits seed too             (default: 0)
#   GPF_SEED_FROM_INNER 1: the inner station seeds too, besides the middle and
#                     outer ones                       (default: 0)
#   ACTS_SOURCE_DIR   ACTS source tree                 (default: <this repo>/../acts)
#   ACTS_BUILD_DIR    build directory                  (default: ${ACTS_SOURCE_DIR}/build)
#   GPF_RESULTS_DIR   where the runs are kept          (default: <this repo>/results/<host>)
#   PYTHON            interpreter for the analysis     (default: python3 of the shell)

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
# shellcheck source=../gpf_common.sh
source "${script_dir}/../gpf_common.sh"
gpf_parse_args "$@"

name="${GPF_NAME:-}"
run_dir="$(gpf_run_dir "${repo_root}")"
source_dir="$(cd -- "${ACTS_SOURCE_DIR:-${repo_root}/../acts}" && pwd)"
build_dir="$(cd -- "${ACTS_BUILD_DIR:-${source_dir}/build}" && pwd)"
ntuple="${GPF_NTUPLE:-}"
geometry="${GPF_GEOMETRY:-}"
if [[ -z "${ntuple}" || -z "${geometry}" ]]; then
  echo "Give the input: GPF_NTUPLE and GPF_GEOMETRY in the config, or --ntuple and" >&2
  echo "--geometry. The geometry has to be the one exported with the n-tuple." >&2
  exit 1
fi
# A label of the input for the tables and the plots; the files decide nothing
sample="${GPF_SAMPLE:-$(basename -- "${ntuple}" .root)}"
python="$(gpf_python)"
backend="${GPF_BACKEND:-cpu}"
case "${backend}" in
  cpu) executable="${build_dir}/bin/ActsUnitTestGlobalPatternFinderData" ;;
  cuda) executable="${build_dir}/bin/ActsUnitTestCudaGlobalPatternFinderData" ;;
  *) echo "GPF_BACKEND has to be cpu or cuda, not ${backend}" >&2; exit 1 ;;
esac
events="${GPF_EVENTS:-500}"
repetitions="${GPF_REPETITIONS:-3}"

if [[ ! "${repetitions}" =~ ^[1-9][0-9]*$ ]]; then
  echo "GPF_REPETITIONS has to be a positive integer, not ${repetitions}" >&2
  exit 1
fi
for needed in "${ntuple}" "${geometry}"; do
  if [[ ! -f "${needed}" ]]; then
    echo "Not found: ${needed}" >&2
    exit 1
  fi
done
if [[ ! -x "${executable}" ]]; then
  echo "Executable not found: ${executable}" >&2
  exit 1
fi

# --- start from nothing: this name now holds this run and only this run ------
if [[ -e "${run_dir}" ]]; then
  echo "Replacing the earlier run ${name}"
  rm -rf -- "${run_dir}"
fi
mkdir -p -- "${run_dir}/performance/repetitions" "${run_dir}/logs"

# --- what is being run, for the record --------------------------------------
{
  echo "name:          ${name}"
  echo "sample:        ${sample}"
  echo "ntuple:        ${ntuple}"
  echo "geometry:      ${geometry}"
  echo "events:        ${events}"
  echo "repetitions:   ${repetitions}"
  [[ -n "${GPF_PROFILE:-}" ]] && echo "profile:       yes"
  echo "backend:       ${backend}"
  if [[ "${backend}" == cuda ]]; then
    echo "workspace:     ${GPF_WORKSPACE_MB:-half of the free GPU memory}${GPF_WORKSPACE_MB:+ MiB}"
  fi
  echo "mdt seeds:     ${GPF_SEED_FROM_MDT:-0}"
  echo "inner seeds:   ${GPF_SEED_FROM_INNER:-0}"
  echo "build:         ${build_dir}"
  echo "executable:    ${executable} ($(date -r "${executable}" '+%F %T'))"
  echo "acts branch:   $(git -C "${source_dir}" branch --show-current 2>/dev/null || echo unknown)"
  echo "acts revision: $(git -C "${source_dir}" rev-parse --short HEAD 2>/dev/null || echo unknown)$(
    [[ -n "$(git -C "${source_dir}" status --porcelain --untracked-files=no 2>/dev/null)" ]] && echo ' (+ local changes)')"
  echo "utilities rev: $(git -C "${repo_root}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "host:          $(hostname)"
  echo "gpu:           $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 || true)"
  echo "started:       $(date '+%F %T')"
} >"${run_dir}/run_info.txt"

# @brief Ends the GPU sampling of a repetition, if one runs
sampler=""
stop_sampler() {
  if [[ -n "${sampler}" ]]; then
    kill "${sampler}" 2>/dev/null || true
    wait "${sampler}" 2>/dev/null || true
    sampler=""
  fi
}
trap stop_sampler EXIT

# @brief One repetition of the finder; the first one also writes the patterns
run_cpp() {
  local repetition="$1"
  local tag="r$(printf '%02d' "${repetition}")"
  local repetitions_dir="${run_dir}/performance/repetitions"
  local timing="${repetitions_dir}/timing_${tag}.csv"
  local log="${run_dir}/logs/${tag}.log"
  local output=""
  local profile=""
  ((repetition == 1)) && output="${run_dir}/patterns.root"
  ((repetition == 1)) && [[ -n "${GPF_PROFILE:-}" ]] && profile="${run_dir}/profile"

  echo "Running ${name} ${tag}"
  if [[ "${backend}" == cuda ]] && command -v nvidia-smi >/dev/null; then
    nvidia-smi --format=csv,nounits --loop-ms=200 \
      --query-gpu=timestamp,utilization.gpu,memory.used,power.draw,clocks.sm \
      >"${repetitions_dir}/gpu_${tag}.csv" 2>/dev/null &
    sampler=$!
  fi
  ACTS_GPF_NTUPLE="${ntuple}" \
  ACTS_GPF_GEOMETRY="${geometry}" \
  ACTS_GPF_MAX_EVENTS="$(gpf_event_cap "${events}")" \
  ACTS_GPF_TIMING="${timing}" \
  ACTS_GPF_OUTPUT="${output}" \
  ACTS_GPF_LOG_LEVEL=WARNING \
  ACTS_GPF_WORKSPACE_MB="${GPF_WORKSPACE_MB:-}" \
  ACTS_GPF_SEED_FROM_MDT="${GPF_SEED_FROM_MDT:-}" \
  ACTS_GPF_SEED_FROM_INNER="${GPF_SEED_FROM_INNER:-}" \
  ACTS_GPF_PROFILE_DIR="${profile}" \
    /usr/bin/time --format='%e %U %S %M' \
    --output="${repetitions_dir}/process_${tag}.txt" \
    "${executable}" --log_level=error --report_level=no --color_output=no \
    >"${log}" 2>&1 || {
    stop_sampler
    echo "The finder failed in ${tag}; the end of ${log}:" >&2
    tail -n 5 "${log}" >&2
    exit 1
  }
  stop_sampler
  if [[ ! -f "${timing}" ]]; then
    echo "No timing file was written for ${tag}, see ${log}" >&2
    exit 1
  fi
  if [[ -n "${output}" && ! -f "${output}" ]]; then
    echo "No pattern file was written, see ${log}" >&2
    exit 1
  fi
  if [[ -n "${profile}" && ! -f "${profile}/seeds.csv" ]]; then
    echo "No profile was written: ${executable} is not a profiling build" >&2
    exit 1
  fi
}

for repetition in $(seq 1 "${repetitions}"); do
  run_cpp "${repetition}"
done

echo
echo "Collecting"
"${script_dir}/analyze_performance.sh"
if [[ -n "${GPF_PROFILE:-}" ]]; then
  "${python}" "${script_dir}/../profile/analyze_profile.py" "${run_dir}/profile"
fi
echo "finished:      $(date '+%F %T')" >>"${run_dir}/run_info.txt"

echo
echo "Run:      ${run_dir}"
echo "Patterns: ${run_dir}/patterns.root"
echo "Performance: ${run_dir}/performance/summary.csv"
echo "Next:     scripts/validation/run_validation.sh --name ${name}"
