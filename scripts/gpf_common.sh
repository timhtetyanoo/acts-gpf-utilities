# Shared helpers for the runners: settings, the python interpreter, the n-tuples.

# @brief Settings from flags and from a config file, for the runners
#
# A run has a name, and everything it produces goes into results/<host>/<name>/,
# <host> being the machine's short host name, so that the runs of several machines
# can sit in one repository. The
# name and the other settings are environment variables. A flag, a line in a
# --config file and the variable itself all set the same thing; where they
# disagree the order is
#
#   flag  >  config file  >  environment variable  >  the script's own default
#
# so a config can be tweaked for one run from the command line. The config file
# is plain bash holding assignments, e.g.  GPF_NAME=cpu_pg0.
#
# Call as `gpf_parse_args "$@"` before the first setting is read. A child runner
# started by another runner inherits the resolved values and does not read the
# config again.
#
# An event count is a positive integer or "all"; see gpf_event_cap.
#
# Flags (a script ignores the ones that mean nothing to it):
#   --config FILE            file of settings
#   --name NAME              name of the run, its folder               GPF_NAME
#   --sample NAME            label of the input, e.g. PG0, PG200       GPF_SAMPLE
#   --ntuple FILE            space point n-tuple                       GPF_NTUPLE
#   --events N|all           events per repetition                     GPF_EVENTS
#   --repetitions N          timing repetitions                        GPF_REPETITIONS
#   --backend cpu|cuda       where the finder runs                     GPF_BACKEND
#   --workspace-mb N         GPU memory for the patterns of an event   GPF_WORKSPACE_MB
#   --threads "N ..."        thread counts of a throughput scan        GPF_THREADS
#   --build-dir DIR          ACTS build directory                      ACTS_BUILD_DIR
#   --source-dir DIR         ACTS source tree                          ACTS_SOURCE_DIR
#   --geometry FILE          tracking geometry json                    GPF_GEOMETRY
#   --results-dir DIR        where the runs are kept                   GPF_RESULTS_DIR
#                            (default: results/<host>; GPF_HOST names another <host>)
#   --station-eff-thr X      a match crosses more than this fraction of the
#                            muon's stations                           GPF_STATION_EFF_THR
#   --bending-eff-thr X      a match holds more than this fraction of the
#                            muon's bending hits                       GPF_BENDING_EFF_THR
#   --python PATH            interpreter                               PYTHON
#   -h, --help               the header of the script
gpf_parse_args() {
  local caller="${BASH_SOURCE[1]}"
  local config="" key
  local -A flags=()

  while (($#)); do
    case "$1" in
      --config) config="${2:?--config needs a file}"; shift ;;
      --name) flags[GPF_NAME]="${2:?--name needs a name}"; shift ;;
      --sample) flags[GPF_SAMPLE]="${2:?}"; shift ;;
      --ntuple) flags[GPF_NTUPLE]="${2:?}"; shift ;;
      --events) flags[GPF_EVENTS]="${2:?--events needs a number or 'all'}"; shift ;;
      --repetitions) flags[GPF_REPETITIONS]="${2:?}"; shift ;;
      --backend) flags[GPF_BACKEND]="${2:?--backend needs cpu or cuda}"; shift ;;
      --workspace-mb) flags[GPF_WORKSPACE_MB]="${2:?}"; shift ;;
      --threads) flags[GPF_THREADS]="${2:?}"; shift ;;
      --build-dir) flags[ACTS_BUILD_DIR]="${2?}"; shift ;;
      --source-dir) flags[ACTS_SOURCE_DIR]="${2:?}"; shift ;;
      --geometry) flags[GPF_GEOMETRY]="${2:?}"; shift ;;
      --results-dir) flags[GPF_RESULTS_DIR]="${2:?}"; shift ;;
      --station-eff-thr) flags[GPF_STATION_EFF_THR]="${2:?}"; shift ;;
      --bending-eff-thr) flags[GPF_BENDING_EFF_THR]="${2:?}"; shift ;;
      --python) flags[PYTHON]="${2:?}"; shift ;;
      -h | --help)
        # the leading comment block of the script
        awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "${caller}"
        echo
        echo "Settings can also come from flags and a --config file, see scripts/gpf_common.sh"
        exit 0 ;;
      *) echo "Unknown argument: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
  done

  # a script started by another script has the resolved settings in its
  # environment already, and a second read would override them with the file
  if [[ -n "${config}" && -z "${GPF_SETTINGS_RESOLVED:-}" ]]; then
    if [[ ! -f "${config}" ]]; then
      echo "Config file not found: ${config}" >&2
      exit 2
    fi
    set -a
    # shellcheck disable=SC1090
    source "${config}"
    set +a
    echo "Settings from ${config}"
  fi

  for key in "${!flags[@]}"; do
    export "${key}=${flags[${key}]}"
  done
  export GPF_SETTINGS_RESOLVED=1
}

# @brief The folder of this machine's runs: results/<host>
#
# GPF_HOST names another <host> than the short host name; GPF_RESULTS_DIR
# replaces the whole path.
# @param $1 repository root
gpf_results_dir() {
  printf '%s' "${GPF_RESULTS_DIR:-$1/results/${GPF_HOST:-$(hostname -s)}}"
}

# @brief The folder of a run: results/<host>/<name>
#
# The name is the only thing that tells two runs apart, so it has to be given and
# has to be a plain word.
# @param $1 repository root
gpf_run_dir() {
  local name="${GPF_NAME:-}"
  if [[ -z "${name}" ]]; then
    echo "The run has no name: give --name or set GPF_NAME in the config." >&2
    exit 2
  fi
  if [[ ! "${name}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    echo "The run name '${name}' may only hold letters, digits, _ . and -." >&2
    exit 2
  fi
  printf '%s/%s' "$(gpf_results_dir "$1")" "${name}"
}

# @brief Value for ACTS_GPF_MAX_EVENTS: the count itself, or nothing for "all"
#
# The finder test reads every event when the variable is empty.
# @param $1 a positive integer or "all"
gpf_event_cap() {
  if [[ "$1" == "all" ]]; then
    return
  fi
  if [[ ! "$1" =~ ^[1-9][0-9]*$ ]]; then
    echo "The event count has to be a positive integer or 'all', not '$1'" >&2
    exit 2
  fi
  printf '%s' "$1"
}

# @brief The Python interpreter of the runners
#
# One interpreter, the python3 of the shell, which is the LCG one after
# `source env_setup.sh`: it has ROOT and every analysis package. PYTHON (or
# --python) names another one. Stops with a hint if it cannot import them.
gpf_python() {
  local python="${PYTHON:-python3}"
  if ! "${python}" -c 'import numpy, pandas, pyarrow, awkward, uproot, matplotlib' \
    >/dev/null 2>&1; then
    echo "${python} cannot import numpy, pandas, pyarrow, awkward, uproot and matplotlib." >&2
    echo "Run \`source env_setup.sh\` first, or point PYTHON / --python at an interpreter that has them." >&2
    exit 2
  fi
  printf '%s' "${python}"
}

