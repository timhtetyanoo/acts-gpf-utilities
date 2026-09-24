#!/usr/bin/env bash
#
# Runs the whole chain: pattern finding, truth preprocessing, scoring and the
# figures. Every stage is skipped when its output already exists, so a rerun
# only does the work that is actually missing.
#
# Required:
#   ACTS_BUILD_DIR   build directory holding bin/ActsUnitTestGlobalPatternFinderData
#   GPF_DATA_DIR     directory holding the n-tuples & the tracking geometry
#
# Optional: see run_global_pattern_validation.sh for the run stage. In addition
#   GPF_SCORES       csv the scores are collected in   (default: ${GPF_OUT_DIR}/scores.csv)
#   GPF_PLOT_DIR     directory of the figures          (default: ${GPF_OUT_DIR}/plots)
#   GPF_MIN_SHARED   geometry ids a match requires     (default: 3)
#   PYTHON           python interpreter                (default: python3)

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
data_dir="${GPF_DATA_DIR:?GPF_DATA_DIR is not set}"
out_dir="${GPF_OUT_DIR:-${data_dir}/gpf_validation}"
scores="${GPF_SCORES:-${out_dir}/scores.csv}"
plot_dir="${GPF_PLOT_DIR:-${out_dir}/plots}"
python="${PYTHON:-python3}"

read -r -a samples <<<"${GPF_SAMPLES:-PG0 PG200}"
read -r -a implementations <<<"${GPF_IMPLEMENTATIONS:-cpu}"

# --- 1. the patterns -------------------------------------------------------
GPF_OUT_DIR="${out_dir}" "${script_dir}/run_global_pattern_validation.sh"

# --- 2. the truth ----------------------------------------------------------
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
  truth="${out_dir}/truth_${sample}.parquet"
  if [[ -f "${truth}" && "${GPF_FORCE:-0}" != "1" ]]; then
    echo "Truth already prepared, skipping: ${sample}"
    continue
  fi
  echo "Preparing the truth of ${sample}"
  "${python}" "${script_dir}/preprocess_truth.py" "$(ntuple_for "${sample}")" \
    "${truth}"
done

# --- 3. the scores ---------------------------------------------------------
rm -f -- "${scores}"
for sample in "${samples[@]}"; do
  for implementation in "${implementations[@]}"; do
    patterns="${out_dir}/patterns_${sample}_${implementation}.root"
    echo "Scoring ${sample} ${implementation}"
    "${python}" "${script_dir}/score_patterns.py" "${patterns}" \
      "${out_dir}/truth_${sample}.parquet" \
      --sample "${sample}" --implementation "${implementation}" \
      --min-shared "${GPF_MIN_SHARED:-3}" --output "${scores}"
  done
done

# --- 4. the figures --------------------------------------------------------
"${python}" "${script_dir}/plot_performance.py" --scores "${scores}" \
  --patterns "${out_dir}"/patterns_*.root --output-dir "${plot_dir}"

echo
echo "Scores:  ${scores}"
echo "Figures: ${plot_dir}"
