#!/usr/bin/env bash
#
# Runs the whole chain: pattern finding, the validation tables, the metrics and
# the figures. Every stage is skipped when its output is
# already there, so a rerun only does the work that is missing.
#
# The first stage needs the ACTS build and therefore the build machine; all the
# later ones only read the pattern files and the n-tuple and run anywhere. Leave
# ACTS_BUILD_DIR unset to analyse pattern files that were produced elsewhere.
#
# Everything is written into <this repo>/gpf_validation. What is small enough to
# push is tracked; the tables are ignored by .gitignore.
#
# Optional:
#   ACTS_BUILD_DIR   build directory; unset skips the pattern finding
#   GPF_DATA_DIR     n-tuples & tracking geometry      (default: <this repo>/data)
#   GPF_OUT_DIR      output directory                  (default: <this repo>/gpf_validation)
#   GPF_SCORES       csv the metrics are collected in  (default: ${GPF_OUT_DIR}/scores.csv)
#   GPF_PLOT_DIR     directory of the figures          (default: ${GPF_OUT_DIR}/plots)
#   GPF_SAMPLES      samples to process                (default: "PG0 PG200")
#   GPF_IMPLEMENTATIONS                                (default: "cpu")
#   GPF_MATCHING_RATIO    ACTS's matchingRatio         (default: 0.5)
#   GPF_MIN_STATIONS      chambers a match needs       (default: 2)
#   PYTHON           python interpreter                (default: <this repo>/.venv/bin/python)

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
data_dir="${GPF_DATA_DIR:-${repo_root}/data}"
out_dir="${GPF_OUT_DIR:-${repo_root}/gpf_validation}"
scores="${GPF_SCORES:-${out_dir}/scores.csv}"
plot_dir="${GPF_PLOT_DIR:-${out_dir}/plots}"
geometry="${GPF_GEOMETRY:-${data_dir}/ActsTrackingGeometry.json}"

python="${PYTHON:-${repo_root}/.venv/bin/python}"
command -v "${python}" >/dev/null 2>&1 || python="python3"

read -r -a samples <<<"${GPF_SAMPLES:-PG0 PG200}"
read -r -a implementations <<<"${GPF_IMPLEMENTATIONS:-cpu}"

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

mkdir -p -- "${out_dir}/logs"

# --- 1. the patterns, on the build machine ---------------------------------
if [[ -n "${ACTS_BUILD_DIR:-}" ]]; then
  GPF_DATA_DIR="${data_dir}" GPF_OUT_DIR="${out_dir}" GPF_GEOMETRY="${geometry}" \
    "${script_dir}/run_global_pattern_validation.sh"
else
  echo "ACTS_BUILD_DIR is unset, using the pattern files already in ${out_dir}"
fi

# --- 2. the validation tables ----------------------------------------------
for sample in "${samples[@]}"; do
  for implementation in "${implementations[@]}"; do
    tag="${sample}_${implementation}"
    tables="${out_dir}/tables_${tag}"
    if [[ -f "${tables}/patterns.parquet" && "${GPF_FORCE:-0}" != "1" ]]; then
      echo "Tables already built, skipping: ${tag}"
      continue
    fi
    "${python}" "${script_dir}/build_validation_tables.py" \
      "${out_dir}/patterns_${tag}.root" "$(ntuple_for "${sample}")" "${tables}"
  done
done

# --- 3. the n-tuple for MuonFastRecoValidation ------------------------------
# Read by the FastRecoValidation executable of houghidipuffvalidation, branch
# LeonardoDev, which has to be built inside an Athena release. Copy the file
# there if this machine has none.
for sample in "${samples[@]}"; do
  for implementation in "${implementations[@]}"; do
    tag="${sample}_${implementation}"
    "${python}" "${script_dir}/to_fastreco_tuple.py" \
      "${out_dir}/tables_${tag}" "${out_dir}/MuonFastRecoTest_${tag}.root"
  done
done

# --- 4. the metrics ---------------------------------------------------------
rm -f -- "${scores}"
for sample in "${samples[@]}"; do
  for implementation in "${implementations[@]}"; do
    tag="${sample}_${implementation}"
    "${python}" "${script_dir}/compute_metrics.py" "${out_dir}/tables_${tag}" \
      --sample "${sample}" --implementation "${implementation}" \
      --matching-ratio "${GPF_MATCHING_RATIO:-0.5}" \
      --min-stations "${GPF_MIN_STATIONS:-2}" \
      --scan --output "${scores}" | tee -- "${out_dir}/logs/metrics_${tag}.log"
  done
done

# --- 5. the figures, one set per sample with the implementations overlaid ---
for sample in "${samples[@]}"; do
  tables=()
  labels=()
  for implementation in "${implementations[@]}"; do
    tables+=("${out_dir}/tables_${sample}_${implementation}")
    labels+=("${implementation}")
  done
  "${python}" "${script_dir}/make_plots.py" "${tables[@]}" \
    --labels "${labels[@]}" --sample "${sample}" \
    --output-dir "${plot_dir}/${sample}"
done

# --- 6. the exact comparison, once there is a second implementation --------
# Graded agreement is in the figures of stage 4; this is the binary gate, so a
# difference is reported and does not stop the chain.
if (( ${#implementations[@]} > 1 )); then
  reference="${implementations[0]}"
  for implementation in "${implementations[@]:1}"; do
    for sample in "${samples[@]}"; do
      echo "Comparing ${sample}: ${implementation} against ${reference}"
      "${python}" "${script_dir}/compare_patterns.py" \
        "${out_dir}/patterns_${sample}_${reference}.root" \
        "${out_dir}/patterns_${sample}_${implementation}.root" \
        | tee -- "${out_dir}/logs/compare_${sample}_${implementation}.log" || true
    done
  done
fi

# --- 7. warn about tracked files too large to push -------------------------
# GitHub rejects files above 100 MB.
if git -C "${repo_root}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  while IFS= read -r -d '' f; do
    if ! git -C "${repo_root}" check-ignore -q -- "${f}"; then
      echo "Warning: ${f} is tracked and larger than 50 MB, consider ignoring it" >&2
    fi
  done < <(find "${out_dir}" -type f -size +50M -print0)
fi

echo
echo "Metrics: ${scores}"
echo "Figures: ${plot_dir}"
