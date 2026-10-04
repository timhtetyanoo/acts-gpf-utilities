#!/usr/bin/env bash
#
# Compares two runs that already exist in results/. It runs no finder and
# aggregates nothing: it reads what steps 1 and 2 wrote and puts the two runs next
# to each other. Each part is done when both runs have what it needs, so a run
# that was only timed, or only validated, still gets what it can.
#
#   run_compare.sh --reference cpu_pg0_all --compare cuda_pg0_all
#
#   --reference NAME     the run the other is measured against
#   --compare NAME       the run compared with it
#   --results-dir DIR    where the runs are kept (default: <this repo>/results)
#
# Writes into results/compare/<reference>_vs_<compare>/:
#   patterns.log     the patterns, hit by hit (needs both patterns.root)
#   plots/           the figures of both runs overlaid (needs both validations)
#   scores.csv       the metrics of both runs in one table
#   speedup.csv      the timing of both runs and the speedup (needs both timings)
#
# Only compatible runs are compared: the same sample, the same n-tuple and the
# same event count, read from run_info.txt of each. Otherwise the two would not
# have seen the same events, and every number below would mix that with the
# difference between the runs.

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
# shellcheck source=../gpf_common.sh
source "${script_dir}/../gpf_common.sh"

reference=""
compared=""
results_dir="${GPF_RESULTS_DIR:-${repo_root}/results}"

usage() { sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1; }

while (($#)); do
  case "$1" in
    --reference)   reference="${2:?}";   shift ;;
    --compare)     compared="${2:?}";    shift ;;
    --results-dir) results_dir="${2:?}"; shift ;;
    --python)      PYTHON="${2:?}"; export PYTHON; shift ;;
    --help|-h)     usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
  shift
done
[[ -n "${reference}" && -n "${compared}" ]] || usage

python="$(gpf_python)"
reference_dir="${results_dir}/${reference}"
compare_dir="${results_dir}/${compared}"
out_dir="${results_dir}/compare/${reference}_vs_${compared}"
for d in "${reference_dir}" "${compare_dir}"; do
  [[ -d "${d}" ]] || { echo "No such run: ${d}" >&2; exit 1; }
done

# --- only runs that saw the same events can be compared ----------------------
# @brief A value of the run_info.txt of a run
info() { sed -n "s/^$2: *//p" "$1/run_info.txt" 2>/dev/null | head -n 1; }

incompatible=0
for key in sample ntuple events; do
  a="$(info "${reference_dir}" "${key}")"
  b="$(info "${compare_dir}" "${key}")"
  if [[ -z "${a}" || -z "${b}" ]]; then
    echo "Cannot compare: ${key} is missing from run_info.txt of ${reference} or ${compared}" >&2
    incompatible=1
  elif [[ "${a}" != "${b}" ]]; then
    echo "Not compatible: ${key} differs" >&2
    echo "  ${reference}: ${a}" >&2
    echo "  ${compared}: ${b}" >&2
    incompatible=1
  fi
done
if ((incompatible)); then
  echo "Run both with the same sample, n-tuple and --events, then compare." >&2
  exit 1
fi

rm -rf -- "${out_dir}"
mkdir -p -- "${out_dir}"
did_anything=0

# --- the patterns, hit by hit -----------------------------------------------
if [[ -f "${reference_dir}/patterns.root" && -f "${compare_dir}/patterns.root" ]]; then
  echo "Patterns: ${compared} against ${reference}"
  # a red exit is a reason to look at the figures, not a verdict: no set -e here
  "${python}" "${script_dir}/../validation/compare_patterns.py" \
    "${reference_dir}/patterns.root" "${compare_dir}/patterns.root" \
    | tee -- "${out_dir}/patterns.log" || true
  did_anything=1
fi

# --- the figures and the metrics --------------------------------------------
reference_val="${reference_dir}/validation"
compare_val="${compare_dir}/validation"
if [[ -f "${reference_val}/tables/muon_flags.parquet"
   && -f "${compare_val}/tables/muon_flags.parquet" ]]; then
  echo "Overlaying the figures"
  sample="$(info "${reference_dir}" sample)"
  "${python}" "${script_dir}/../validation/make_plots.py" \
    "${reference_val}/tables" "${compare_val}/tables" \
    --labels "${reference}" "${compared}" --sample "${sample}" \
    --output-dir "${out_dir}/plots"
  did_anything=1
fi
if [[ -f "${reference_val}/scores.csv" && -f "${compare_val}/scores.csv" ]]; then
  {
    printf 'run,'; head -n 1 -- "${reference_val}/scores.csv"
    tail -n +2 -- "${reference_val}/scores.csv" | sed "s/^/${reference},/"
    tail -n +2 -- "${compare_val}/scores.csv"   | sed "s/^/${compared},/"
  } >"${out_dir}/scores.csv"
  echo "Metrics of both runs in ${out_dir}/scores.csv"
  did_anything=1
fi

# --- the timing --------------------------------------------------------------
reference_summary="${reference_dir}/timing/summary.csv"
compare_summary="${compare_dir}/timing/summary.csv"
if [[ -f "${reference_summary}" && -f "${compare_summary}" ]]; then
  echo
  "${python}" "${script_dir}/compare_timing.py" \
    "${reference_summary}" "${compare_summary}" \
    --reference-label "${reference}" --compare-label "${compared}" \
    --output "${out_dir}/speedup.csv" | tee -- "${out_dir}/speedup.log"
  did_anything=1
fi

if ((! did_anything)); then
  echo "Nothing to compare: the two runs share no patterns, validation or timing" >&2
  exit 1
fi

echo
echo "Comparison: ${out_dir}"
