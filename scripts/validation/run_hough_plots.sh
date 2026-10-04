#!/usr/bin/env bash
#
# Step 3, optional: the figures of MuonFastRecoValidation, the plotting package of
# houghidipuffvalidation (branch LeonardoDev), drawn from the fastreco.root that
# step 2 wrote. It runs the executable and nothing else.
#
#   run_hough_plots.sh cpu_pg0_all                one run
#   run_hough_plots.sh cpu_before cpu_after       several runs, one curve each
#
# The package needs an Athena release, which the LCG environment of env_setup.sh
# is not. Run this in a shell set up for it, and do not source env_setup.sh there:
#
#   setupATLAS
#   cd <build directory of houghidipuffvalidation>
#   asetup --restore
#   source <platform>/setup.sh          # e.g. x86_64-el9-gcc15-opt/setup.sh
#
# One name writes into results/<name>/hough/, several into
# results/compare/<first>_vs_<second>.../hough/. Several runs have to be of the
# same sample, n-tuple and event count, as for run_compare.sh. Each run is
# replaced, not added to.
#
#   --results-dir DIR    where the runs are kept (default: <this repo>/results)
#   --sample-name TEXT   text of the plots' header (default: the sample of the run)
#
# Writes Efficiency/, Means/, Resolutions/ and dist/ below the output folder. The
# muon plots, the resolutions and the charge, are empty: the finder produces no
# reconstructed muons.

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"

names=()
results_dir="${GPF_RESULTS_DIR:-${repo_root}/results}"
sample_text=""

usage() { sed -n '2,29p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1; }

while (($#)); do
  case "$1" in
    --results-dir)  results_dir="${2:?}";  shift ;;
    --sample-name)  sample_text="${2:?}";  shift ;;
    -h|--help)      usage ;;
    -*) echo "Unknown argument: $1" >&2; usage ;;
    *)  names+=("$1") ;;
  esac
  shift
done
((${#names[@]})) || usage

if ! command -v FastRecoValidation >/dev/null 2>&1; then
  echo "FastRecoValidation is not on the path." >&2
  echo "Set up Athena and the build of houghidipuffvalidation first, see --help." >&2
  exit 1
fi

# @brief A value of the run_info.txt of a run
info() { sed -n "s/^$2: *//p" "$1/run_info.txt" 2>/dev/null | head -n 1; }

results_dir="$(cd -- "${results_dir}" && pwd)"
inputs=()
for name in "${names[@]}"; do
  run="${results_dir}/${name}"
  tuple="${run}/validation/fastreco.root"
  if [[ ! -f "${tuple}" ]]; then
    echo "No ${tuple}: run scripts/validation/run_validation.sh --name ${name} first," >&2
    echo "in a shell where ROOT is available, since that stage writes the file." >&2
    exit 1
  fi
  inputs+=("${name}=${tuple}")
done

# --- several runs must have seen the same events ------------------------------
first="${results_dir}/${names[0]}"
for name in "${names[@]:1}"; do
  for key in sample ntuple events; do
    a="$(info "${first}" "${key}")"
    b="$(info "${results_dir}/${name}" "${key}")"
    if [[ -z "${a}" || -z "${b}" || "${a}" != "${b}" ]]; then
      echo "Not compatible: ${key} differs between ${names[0]} and ${name}" >&2
      echo "  ${names[0]}: ${a:-missing}" >&2
      echo "  ${name}: ${b:-missing}" >&2
      exit 1
    fi
  done
done

if ((${#names[@]} == 1)); then
  out_dir="${first}/hough"
else
  joined="${names[0]}"
  for name in "${names[@]:1}"; do joined="${joined}_vs_${name}"; done
  out_dir="${results_dir}/compare/${joined}/hough"
fi
rm -rf -- "${out_dir}"
mkdir -p -- "${out_dir}"

sample_text="${sample_text:-$(info "${first}" sample)}"

echo "Plotting ${names[*]} into ${out_dir}"
# The tool prints a line for every truth muon without a reconstructed muon, which
# is all of them here, so its output is not kept: it goes to a temporary file that
# is shown only when no plot was written.
log="$(mktemp)"
trap 'rm -f -- "${log}"' EXIT
FastRecoValidation --plot-dir "${out_dir}" --out . --sample-name "${sample_text}" \
  "${inputs[@]}" >"${log}" 2>&1 || true

n_plots="$(find "${out_dir}" -name '*.pdf' | wc -l)"
if ((n_plots == 0)); then
  echo "No plot was written. The end of the output of FastRecoValidation:" >&2
  grep -v "^Evt:" "${log}" | tail -n 25 >&2
  exit 1
fi
echo
echo "${n_plots} plots in ${out_dir}"
