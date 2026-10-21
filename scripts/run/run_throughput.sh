#!/usr/bin/env bash
#
# Events per second of the finder against the number of threads, in one
# process. The events are read into memory first, so reading is not measured;
# the threads then share them, each taking the next event until none is left.
# Every thread count runs the events once to warm up and once timed, and has to
# reproduce the pattern count of each event of a pass on one thread.
#
#   run_throughput.sh --config configs/cpu_pg200.conf --name throughput_cpu_pg200 --events 1000
#   run_throughput.sh --config configs/cuda_pg200.conf --name throughput_cuda_pg200 --events 1000
#
# Writes results/<host>/<name>/:
#   throughput.csv   per thread count: events per second, wall and CPU time,
#                    cores in use, events that overflowed, failed or found a
#                    different number of patterns than on one thread; for a
#                    GPU run also the GPU's mean utilisation and power, median
#                    SM clock and peak memory during that pass
#   gpu.csv          nvidia-smi samples every 200 ms (GPU run)
#   run_info.txt     what was run
#   log.txt          output of the test
#
# Settings (flags are listed in scripts/gpf_common.sh):
#   GPF_NAME          name of the run                  (required)
#   GPF_NTUPLE        space point n-tuple              (required)
#   GPF_GEOMETRY      tracking geometry json made with that n-tuple (required)
#   GPF_EVENTS        events held in memory and run    (default: 1000; "all"
#                     holds the whole sample in memory)
#   GPF_THREADS       thread counts                    (default: "1 2 4 8 12")
#   GPF_BACKEND       cpu or cuda                      (default: cpu)
#   GPF_WORKSPACE_MB  GPU memory in MiB for the patterns of each event in
#                     flight, the same for every thread count (default: 2048)
#   GPF_SEED_FROM_MDT, GPF_SEED_FROM_INNER   as in run_finder.sh
#   ACTS_SOURCE_DIR   ACTS source tree                 (default: <this repo>/../acts)
#   ACTS_BUILD_DIR    build directory                  (default: ${ACTS_SOURCE_DIR}/build)
#   GPF_RESULTS_DIR   where the runs are kept          (default: <this repo>/results/<host>)

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
sample="${GPF_SAMPLE:-$(basename -- "${ntuple}" .root)}"
backend="${GPF_BACKEND:-cpu}"
case "${backend}" in
  cpu)
    executable="${build_dir}/bin/ActsUnitTestGlobalPatternFinderData"
    test_case="GlobalPatternFinderDataSuite/pattern_finding_throughput"
    ;;
  cuda)
    executable="${build_dir}/bin/ActsUnitTestCudaGlobalPatternFinderData"
    test_case="CudaGlobalPatternFinderDataSuite/cuda_pattern_finding_throughput"
    ;;
  *) echo "GPF_BACKEND has to be cpu or cuda, not ${backend}" >&2; exit 1 ;;
esac
events="${GPF_EVENTS:-1000}"
threads="${GPF_THREADS:-1 2 4 8 12}"
workspace_mb="${GPF_WORKSPACE_MB:-2048}"
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

if [[ -e "${run_dir}" ]]; then
  echo "Replacing the earlier run ${name}"
  rm -rf -- "${run_dir}"
fi
mkdir -p -- "${run_dir}"

{
  echo "name:          ${name}"
  echo "sample:        ${sample}"
  echo "ntuple:        ${ntuple}"
  echo "geometry:      ${geometry}"
  echo "events:        ${events}"
  echo "threads:       ${threads}"
  echo "backend:       ${backend}"
  if [[ "${backend}" == cuda ]]; then
    echo "workspace:     ${workspace_mb} MiB per event in flight"
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
  echo "cpu:           $(lscpu | sed -n 's/^Model name: *//p' | head -n 1), $(nproc) threads"
  echo "gpu:           $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 || true)"
  echo "started:       $(date '+%F %T')"
} >"${run_dir}/run_info.txt"

echo "Running ${name}: ${events} events on ${threads} threads"
# A GPU run samples the GPU every 200 ms; each timed pass gets the samples
# taken while it ran
sampler=""
stop_sampler() {
  if [[ -n "${sampler}" ]]; then
    kill "${sampler}" 2>/dev/null || true
    wait "${sampler}" 2>/dev/null || true
    sampler=""
  fi
}
trap stop_sampler EXIT
if [[ "${backend}" == cuda ]] && command -v nvidia-smi >/dev/null; then
  nvidia-smi --format=csv,nounits --loop-ms=200 \
    --query-gpu=timestamp,utilization.gpu,memory.used,power.draw,clocks.sm \
    >"${run_dir}/gpu.csv" 2>/dev/null &
  sampler=$!
fi
ACTS_GPF_NTUPLE="${ntuple}" \
ACTS_GPF_GEOMETRY="${geometry}" \
ACTS_GPF_MAX_EVENTS="$(gpf_event_cap "${events}")" \
ACTS_GPF_THREADS="${threads}" \
ACTS_GPF_THROUGHPUT="${run_dir}/throughput.csv" \
ACTS_GPF_WORKSPACE_MB="${workspace_mb}" \
ACTS_GPF_SEED_FROM_MDT="${GPF_SEED_FROM_MDT:-}" \
ACTS_GPF_SEED_FROM_INNER="${GPF_SEED_FROM_INNER:-}" \
  "${executable}" --run_test="${test_case}" --log_level=error \
  --report_level=no --color_output=no >"${run_dir}/log.txt" 2>&1 || {
  echo "The throughput test failed; the end of ${run_dir}/log.txt:" >&2
  tail -n 5 "${run_dir}/log.txt" >&2
  exit 1
}
stop_sampler
echo "finished:      $(date '+%F %T')" >>"${run_dir}/run_info.txt"
if [[ -s "${run_dir}/gpu.csv" ]]; then
  "$(gpf_python)" "${script_dir}/throughput_gpu.py" \
    "${run_dir}/throughput.csv" "${run_dir}/gpu.csv"
fi

echo
column -s, -t "${run_dir}/throughput.csv"
echo
echo "Run: ${run_dir}"
