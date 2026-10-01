#!/usr/bin/env bash
#
# Compares two sets of results that already exist. It runs no finder and
# aggregates nothing: it reads what the validation and performance pipelines
# wrote and puts the two sides next to each other.
#
# The four directories are taken as given. How they were produced, on which
# machine and by which driver makes no difference here, and the labels come
# from the command line rather than from the file names.
#
#   --reference-validation DIR   physics of the reference
#   --compare-validation   DIR   physics of the other side
#   --reference-timing     DIR   timing of the reference, holding event_summary.csv
#   --compare-timing       DIR   timing of the other side
#   --reference-label NAME       default: reference
#   --compare-label   NAME       default: compared
#   --samples "PG0 PG200"        default: PG0
#   --output DIR                 default: <this repo>/gpf_compare
#
# Each pair is optional: give the validation pair for a physics comparison, the
# timing pair for a speedup, or both.

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
python="${PYTHON:-${repo_root}/.venv/bin/python}"
command -v "${python}" >/dev/null 2>&1 || python="python3"

reference_validation=""
compare_validation=""
reference_timing=""
compare_timing=""
reference_label="reference"
compare_label="compared"
samples_raw="PG0"
out_dir="${repo_root}/gpf_compare"

usage() { sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1; }

while (($#)); do
  case "$1" in
    --reference-validation) reference_validation="${2:?}"; shift ;;
    --compare-validation)   compare_validation="${2:?}";   shift ;;
    --reference-timing)     reference_timing="${2:?}";     shift ;;
    --compare-timing)       compare_timing="${2:?}";       shift ;;
    --reference-label)      reference_label="${2:?}";      shift ;;
    --compare-label)        compare_label="${2:?}";        shift ;;
    --samples)              samples_raw="${2:?}";          shift ;;
    --output)               out_dir="${2:?}";              shift ;;
    --help|-h)              usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
  shift
done

read -r -a samples <<<"${samples_raw}"
did_anything=0

# @brief Prints the single path matching a glob inside a directory
#        Several matches are an error: which of them is meant is a guess
only_match() {
  local directory="$1" pattern="$2" found=()
  shopt -s nullglob
  found=("${directory}"/${pattern})
  shopt -u nullglob
  if ((${#found[@]} == 0)); then
    return 1
  fi
  if ((${#found[@]} > 1)); then
    echo "Several ${pattern} in ${directory}, cannot tell which is meant" >&2
    return 1
  fi
  printf '%s' "${found[0]}"
}

# --- physics ----------------------------------------------------------------
if [[ -n "${reference_validation}" && -n "${compare_validation}" ]]; then
  mkdir -p -- "${out_dir}/physics/logs" "${out_dir}/physics/plots"
  for sample in "${samples[@]}"; do
    reference_patterns="$(only_match "${reference_validation}" "patterns_${sample}_*.root")" || {
      echo "No patterns for ${sample} in ${reference_validation}, skipping"
      continue
    }
    compare_patterns="$(only_match "${compare_validation}" "patterns_${sample}_*.root")" || {
      echo "No patterns for ${sample} in ${compare_validation}, skipping"
      continue
    }

    echo "Patterns ${sample}: ${compare_label} against ${reference_label}"
    "${python}" "${script_dir}/../validation/compare_patterns.py" \
      "${reference_patterns}" "${compare_patterns}" \
      | tee -- "${out_dir}/physics/logs/patterns_${sample}.log" || true
    did_anything=1

    reference_tables="$(only_match "${reference_validation}" "tables_${sample}_*")" || true
    compare_tables="$(only_match "${compare_validation}" "tables_${sample}_*")" || true
    if [[ -f "${reference_tables:-/dev/null}/muon_flags.parquet"
       && -f "${compare_tables:-/dev/null}/muon_flags.parquet" ]]; then
      echo "Overlaying the figures of ${sample}"
      "${python}" "${script_dir}/../validation/make_plots.py" \
        "${reference_tables}" "${compare_tables}" \
        --labels "${reference_label}" "${compare_label}" --sample "${sample}" \
        --output-dir "${out_dir}/physics/plots/${sample}"
    fi
  done

  # the metrics of both sides in one table, each row carrying its label
  reference_scores="${reference_validation}/scores.csv"
  compare_scores="${compare_validation}/scores.csv"
  if [[ -f "${reference_scores}" && -f "${compare_scores}" ]]; then
    {
      printf 'side,'; head -n 1 -- "${reference_scores}"
      tail -n +2 -- "${reference_scores}" | sed "s/^/${reference_label},/"
      tail -n +2 -- "${compare_scores}"   | sed "s/^/${compare_label},/"
    } >"${out_dir}/physics/scores.csv"
    echo "Metrics of both sides in ${out_dir}/physics/scores.csv"
    did_anything=1
  fi
fi

# --- timing -----------------------------------------------------------------
if [[ -n "${reference_timing}" && -n "${compare_timing}" ]]; then
  reference_summary="${reference_timing}/event_summary.csv"
  compare_summary="${compare_timing}/event_summary.csv"
  if [[ -f "${reference_summary}" && -f "${compare_summary}" ]]; then
    mkdir -p -- "${out_dir}/timing"
    echo
    "${python}" "${script_dir}/compare_timing.py" \
      "${reference_summary}" "${compare_summary}" \
      --reference-label "${reference_label}" --compare-label "${compare_label}" \
      --output "${out_dir}/timing/speedup.csv" \
      | tee -- "${out_dir}/timing/speedup.log"
    did_anything=1
  else
    echo "Both timing directories need an event_summary.csv from the benchmark" >&2
  fi
fi

if ((! did_anything)); then
  echo "Nothing was compared; give a validation pair, a timing pair, or both" >&2
  exit 1
fi

echo
echo "Comparison: ${out_dir}"
