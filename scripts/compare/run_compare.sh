#!/usr/bin/env bash
#
# Compares results that the validation and performance pipelines already wrote.
# It does not run the finder. Missing halves are skipped: you can compare
# physics only, timing only, or both.
#
# The first name in GPF_IMPLEMENTATIONS is the reference, the rest are compared
# against it.
#
# Optional:
#   GPF_VALIDATION_DIR     physics outputs      (default: <this repo>/gpf_validation)
#   GPF_TIMING_DIR         parent of cpp/python (default: <this repo>/gpf_timing)
#   GPF_TIMING_CPP_DIR     C++ timings          (default: ${GPF_TIMING_DIR}/cpp)
#   GPF_TIMING_PYTHON_DIR  Sequencer timings    (default: ${GPF_TIMING_DIR}/python)
#   GPF_OUT_DIR            comparison outputs   (default: <this repo>/gpf_compare)
#   GPF_SAMPLES         samples             (default: "PG0")
#   GPF_IMPLEMENTATIONS reference first     (default: "cpu cuda")
#   PYTHON              interpreter         (default: <this repo>/.venv/bin/python)

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
validation_dir="${GPF_VALIDATION_DIR:-${repo_root}/gpf_validation}"
timing_root="${GPF_TIMING_DIR:-${repo_root}/gpf_timing}"
timing_cpp="${GPF_TIMING_CPP_DIR:-${timing_root}/cpp}"
timing_python="${GPF_TIMING_PYTHON_DIR:-${timing_root}/python}"
out_dir="${GPF_OUT_DIR:-${repo_root}/gpf_compare}"
python="${PYTHON:-${repo_root}/.venv/bin/python}"
command -v "${python}" >/dev/null 2>&1 || python="python3"

read -r -a samples <<<"${GPF_SAMPLES:-PG0}"
read -r -a implementations <<<"${GPF_IMPLEMENTATIONS:-cpu cuda}"

if (( ${#implementations[@]} < 2 )); then
  echo "GPF_IMPLEMENTATIONS needs a reference and at least one other, e.g. \"cpu cuda\"" >&2
  exit 1
fi

reference="${implementations[0]}"
mkdir -p -- "${out_dir}/physics/logs" "${out_dir}/physics/plots"
did_anything=0

# --- physics: hit-by-hit patterns, overlaid figures --------------------------
if [[ -d "${validation_dir}" ]]; then
  for sample in "${samples[@]}"; do
    ref_patterns="${validation_dir}/patterns_${sample}_${reference}.root"
    if [[ ! -f "${ref_patterns}" ]]; then
      echo "No validation patterns for ${sample} ${reference}, skipping physics"
      continue
    fi
    physics=0
    for implementation in "${implementations[@]:1}"; do
      cmp_patterns="${validation_dir}/patterns_${sample}_${implementation}.root"
      if [[ ! -f "${cmp_patterns}" ]]; then
        echo "No validation patterns for ${sample} ${implementation}, skipping"
        continue
      fi
      echo "Patterns ${sample}: ${implementation} against ${reference}"
      "${python}" "${script_dir}/../validation/compare_patterns.py" \
        "${ref_patterns}" "${cmp_patterns}" \
        | tee -- "${out_dir}/physics/logs/compare_${sample}_${implementation}.log" || true
      physics=1
    done

    tables=()
    labels=()
    for implementation in "${implementations[@]}"; do
      dir="${validation_dir}/tables_${sample}_${implementation}"
      if [[ -f "${dir}/muon_flags.parquet" ]]; then
        tables+=("${dir}")
        labels+=("${implementation}")
      fi
    done
    if (( ${#tables[@]} > 1 )); then
      echo "Overlaying physics plots for ${sample}"
      "${python}" "${script_dir}/../validation/make_plots.py" "${tables[@]}" \
        --labels "${labels[@]}" --sample "${sample}" \
        --output-dir "${out_dir}/physics/plots/${sample}"
      physics=1
    fi
    if (( physics )); then
      did_anything=1
    fi
  done

  if [[ -f "${validation_dir}/scores.csv" ]]; then
    cp -f -- "${validation_dir}/scores.csv" "${out_dir}/physics/scores.csv"
    did_anything=1
  fi
fi

# --- timing: each driver has its own tree ------------------------------------
collect_cpp="${timing_cpp}/repetitions"
if [[ ! -d "${collect_cpp}" ]]; then
  collect_cpp="${timing_cpp}/runs"
fi
if [[ -d "${collect_cpp}" ]] && compgen -G "${collect_cpp}/timing_*.csv" >/dev/null; then
  echo "C++ event timings from ${collect_cpp}"
  mkdir -p -- "${out_dir}/timing/cpp"
  "${python}" "${script_dir}/../benchmark/aggregate_event_timing.py" \
    "${collect_cpp}" --output-dir "${out_dir}/timing/cpp" \
    | tee -- "${out_dir}/timing/cpp/collect.log"
  "${python}" "${script_dir}/../benchmark/plot_event_timing.py" \
    "${out_dir}/timing/cpp/event_timings.csv" \
    --output "${out_dir}/timing/cpp/event_timing.png"
  did_anything=1
fi

collect_python="${timing_python}/repetitions"
if [[ ! -d "${collect_python}" ]]; then
  collect_python="${timing_python}/runs"
fi
if [[ -d "${collect_python}" ]] && compgen -G "${collect_python}/timing_*.csv" >/dev/null; then
  echo "Sequencer timings from ${collect_python}"
  mkdir -p -- "${out_dir}/timing/python"
  "${python}" "${script_dir}/../benchmark/collect_timing.py" \
    "${collect_python}" --output "${out_dir}/timing/python/timings.csv" \
    | tee -- "${out_dir}/timing/python/collect.log"
  "${python}" "${script_dir}/../benchmark/plot_timing.py" \
    "${out_dir}/timing/python/timings.csv" \
    --output "${out_dir}/timing/python/timing.png"
  did_anything=1
fi

if (( ! did_anything )); then
  echo "Nothing to compare in ${validation_dir}, ${timing_cpp} or ${timing_python}" >&2
  exit 1
fi

echo
echo "Comparison: ${out_dir}"
