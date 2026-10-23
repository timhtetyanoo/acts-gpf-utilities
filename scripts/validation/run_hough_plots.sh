#!/usr/bin/env bash
#
# Step 3, optional: the figures of MuonFastRecoValidation, the plotting package of
# houghidipuffvalidation. It writes each run's n-tuple for the package,
# validation/fastreco.root, from the tables of step 2, then runs the executable.
# The n-tuple is rewritten only when the tables are newer than it.
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
# The n-tuple is written with the python3 of that shell when it has ROOT, numpy,
# pandas and pyarrow (PYTHON names another interpreter). A release without
# pyarrow writes it in a clean shell set up with env_setup.sh next to this
# repository (GPF_ENV_SETUP names another setup script).
#
# One name writes into results/<host>/<name>/hough/, several into
# results/<host>/compare/<first>_vs_<second>.../hough/. Several runs have to be of the
# same sample, n-tuple and event count, as for run_compare.sh. Each run is
# replaced, not added to.
#
#   --results-dir DIR    where the runs are kept (default: <this repo>/results/<host>)
#   --sample-name TEXT   text of the plots' header (default: the sample of the run)
#   --labels A,B,...     legend label of each run, in the order of the names
#                        (default: the run names)
#
# Writes Efficiency/, Means/, Resolutions/ and dist/ below the output folder. The
# muon plots, the resolutions and the charge, are empty: the finder produces no
# reconstructed muons.

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
# shellcheck source=../gpf_common.sh
source "${script_dir}/../gpf_common.sh"

names=()
results_dir="$(gpf_results_dir "${repo_root}")"
sample_text=""
labels=""

usage() { sed -n '2,37p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1; }

while (($#)); do
  case "$1" in
    --results-dir)  results_dir="${2:?}";  shift ;;
    --sample-name)  sample_text="${2:?}";  shift ;;
    --labels)       labels="${2:?}";       shift ;;
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

python="${PYTHON:-python3}"
env_setup="${GPF_ENV_SETUP:-${repo_root}/../env_setup.sh}"

results_dir="$(cd -- "${results_dir}" && pwd)"
label_list=()
if [[ -n "${labels}" ]]; then
  IFS=, read -r -a label_list <<<"${labels}"
  if ((${#label_list[@]} != ${#names[@]})); then
    echo "--labels has ${#label_list[@]} labels for ${#names[@]} runs." >&2
    exit 1
  fi
fi
inputs=()
i=0
for name in "${names[@]}"; do
  tables="${results_dir}/${name}/validation/tables"
  if [[ ! -d "${tables}" ]]; then
    echo "No ${tables}: run scripts/validation/run_validation.sh --name ${name} first." >&2
    exit 1
  fi
  inputs+=("${label_list[i]:-${name}}=${results_dir}/${name}/validation/fastreco.root")
  i=$((i + 1))
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

# --- the n-tuple of each run --------------------------------------------------
# Written from the tables, and written again when they have been rebuilt since.
for name in "${names[@]}"; do
  tables="${results_dir}/${name}/validation/tables"
  tuple="${results_dir}/${name}/validation/fastreco.root"
  if [[ ! -f "${tuple}" || "${tables}/patterns.parquet" -nt "${tuple}" \
        || "${tables}/muons.parquet" -nt "${tuple}" ]]; then
    if "${python}" -c 'import ROOT, numpy, pandas, pyarrow' >/dev/null 2>&1; then
      "${python}" "${script_dir}/to_fastreco_tuple.py" "${tables}" "${tuple}"
    elif [[ -f "${env_setup}" ]]; then
      echo "Writing the n-tuple of ${name} in a shell set up with ${env_setup}"
      env -i HOME="${HOME}" USER="${USER}" TERM=dumb PATH=/usr/bin:/bin \
        bash -c 'source "$1" >/dev/null 2>&1 && python3 "$2" "$3" "$4"' _ \
        "${env_setup}" "${script_dir}/to_fastreco_tuple.py" "${tables}" "${tuple}"
    else
      echo "${name} needs its n-tuple written: ${python} cannot import ROOT, numpy," >&2
      echo "pandas and pyarrow, and there is no ${env_setup}. Give GPF_ENV_SETUP" >&2
      echo "or point PYTHON at an interpreter that has them." >&2
      exit 1
    fi
  fi
done

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
