#!/usr/bin/env bash
#
# Step 2 of 2: validates the patterns that step 1 wrote, with the selection and
# the matching of MuonFastRecoValidation (see scripts/validation/gpfval.py). It never runs the
# finder: it reads results/<name>/patterns.root and the input n-tuple, and builds
# the validation tables, the FastReco tuple, the metrics and the figures. Every
# run redoes every stage: the tables follow from the patterns and the n-tuple, so
# reusing old ones could only mean tables of an older run.
#
# Runs anywhere the results folder and the n-tuple are: no ACTS build, no
# tracking geometry. The sample and the n-tuple are taken from run_info.txt of the
# run unless given.
#
#   run_validation.sh --name cpu_pg0_all
#   run_validation.sh --config configs/cpu_pg0_all.conf
#
# Writes into results/<name>/validation/:
#   scores.csv       the metrics
#   metrics.log      the same, and how they move with the matching ratio
#   plots/           efficiency, composition, pulls, direction
#   tables/          the parquet tables the metrics are computed from
#   fastreco.root    the n-tuple for MuonFastRecoValidation (needs ROOT)
#
# Settings (flags are listed in scripts/gpf_common.sh):
#   GPF_NAME          name of the run                  (required)
#   GPF_SAMPLE        sample                           (default: from run_info.txt)
#   GPF_NTUPLE        n-tuple                          (default: from run_info.txt)
#   GPF_RESULTS_DIR   where the runs are kept          (default: <this repo>/results)
#   GPF_STATION_EFF_THR   a match crosses more than this fraction of the muon's
#                         stations                     (default: 0.5)
#   GPF_BENDING_EFF_THR   a match holds more than this fraction of the muon's
#                         bending hits                 (default: 0.5)
#   PYTHON            python interpreter               (default: python3 of the shell)

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
# shellcheck source=../gpf_common.sh
source "${script_dir}/../gpf_common.sh"
gpf_parse_args "$@"

name="${GPF_NAME:-}"
run_dir="$(gpf_run_dir "${repo_root}")"
out_dir="${run_dir}/validation"
patterns="${run_dir}/patterns.root"
python="$(gpf_python)"

# @brief A value of run_info.txt
info() { sed -n "s/^$1: *//p" "${run_dir}/run_info.txt" 2>/dev/null | head -n 1; }

# The n-tuple the patterns were found in, as the run recorded it
ntuple="${GPF_NTUPLE:-$(info ntuple)}"
sample="${GPF_SAMPLE:-$(info sample)}"
if [[ -z "${ntuple}" ]]; then
  echo "No n-tuple for ${name}: run_info.txt does not name one; give --ntuple." >&2
  exit 1
fi
sample="${sample:-$(basename -- "${ntuple}" .root)}"

# --- the inputs have to be there -------------------------------------------
if [[ ! -f "${patterns}" ]]; then
  echo "No patterns for ${name}: ${patterns}" >&2
  echo "Run scripts/run/run_finder.sh first." >&2
  exit 1
fi
if [[ ! -f "${ntuple}" ]]; then
  echo "Missing n-tuple: ${ntuple}" >&2
  exit 1
fi

rm -rf -- "${out_dir}"
mkdir -p -- "${out_dir}"

# --- 1. the validation tables ----------------------------------------------
"${python}" "${script_dir}/build_validation_tables.py" \
  "${patterns}" "${ntuple}" "${out_dir}/tables"

# --- 2. the n-tuple for MuonFastRecoValidation ------------------------------
# Read by the FastRecoValidation executable of houghidipuffvalidation, branch
# LeonardoDev. Needs ROOT, which the LCG environment of env_setup.sh provides;
# without it the stage is skipped and the others still finish.
if gpf_has_root "${python}"; then
  "${python}" "${script_dir}/to_fastreco_tuple.py" \
    "${out_dir}/tables" "${out_dir}/fastreco.root"
else
  echo "Skipping the FastReco tuple: ${python} cannot import ROOT." >&2
  echo "Run \`source env_setup.sh\` and repeat to get it." >&2
fi

# --- 3. the metrics ---------------------------------------------------------
"${python}" "${script_dir}/compute_metrics.py" "${out_dir}/tables" \
  --sample "${sample}" --implementation "${name}" \
  --station-eff-thr "${GPF_STATION_EFF_THR:-0.5}" \
  --bending-eff-thr "${GPF_BENDING_EFF_THR:-0.5}" \
  --scan --output "${out_dir}/scores.csv" | tee -- "${out_dir}/metrics.log"

# --- 4. the figures ---------------------------------------------------------
"${python}" "${script_dir}/make_plots.py" "${out_dir}/tables" \
  --labels "${name}" --sample "${sample}" --output-dir "${out_dir}/plots"

echo
echo "Metrics: ${out_dir}/scores.csv"
echo "Figures: ${out_dir}/plots"
