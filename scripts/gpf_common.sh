# Shared helpers for the validation and benchmark runners.
# Source after `repo_root` is set.

# @brief n-tuple of a sample, honouring GPF_<SAMPLE>_NTUPLE
# @param $1 data directory
# @param $2 sample name (PG0, PG200, ...)
gpf_ntuple_for() {
  local data_dir="$1"
  local sample="$2"
  local override="GPF_${sample}_NTUPLE"
  local fallback
  case "${sample}" in
    PG0) fallback="${data_dir}/ParticleGun_MU0.root" ;;
    PG200) fallback="${data_dir}/ParticleGun_MU200.root" ;;
    *) fallback="${data_dir}/${sample}.root" ;;
  esac
  printf '%s' "${!override:-${fallback}}"
}
