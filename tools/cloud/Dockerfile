# ============================================================
# ICESEE Combined Container — Docker
# Converted from combined-env-inbuilt-matlab.def
# Base: docker.io/bkyanjo/combined-lean:v1.0
# ============================================================

FROM docker.io/bkyanjo/combined-lean:v1.0

# ── %files ────────────────────────────────────────────────────
COPY scripts/gen_pip_reqs.py /opt/build-scripts/gen_pip_reqs.py

# ── %post ─────────────────────────────────────────────────────
RUN set -eu \
    && apt-get update && apt-get install -y --no-install-recommends \
        git \
        rsync \
    && rm -rf /var/lib/apt/lists/* \
    \
    # Install and configure ICESEE Python dependencies
    && chmod +x /opt/build-scripts/gen_pip_reqs.py \
    && python3 /opt/build-scripts/gen_pip_reqs.py \
        --pyproject /opt/ICESEE/pyproject.toml \
        --out /tmp/icesee-pip-reqs.txt \
    && grep -viE '^[[:space:]]*(numpy|mpi4py|petsc4py|h5py)([[:space:]]|[<>=!~\[]|$)' \
        /tmp/icesee-pip-reqs.txt > /tmp/icesee-pip-reqs-safe.txt \
    && /opt/venv-icepack/bin/pip install --no-cache-dir -r /tmp/icesee-pip-reqs-safe.txt \
    && /opt/venv-firedrake/bin/pip install --no-cache-dir -r /tmp/icesee-pip-reqs-safe.txt \
    && /opt/venv-icepack/bin/pip install --no-cache-dir --no-deps bigmpi4py \
    && /opt/venv-firedrake/bin/pip install --no-cache-dir --no-deps bigmpi4py

# ── AWS CLI v2 (build-time, baked into the image) ────────────────
# CryoStack's cloud runner (cryostack_src/cloud/runtime.py) shells out to
# `aws s3 sync` to fetch a run's staged inputs and publish its outputs --
# it needs this binary present in the running Fargate container, not
# something a job installs for itself at start (the exact live failure this
# fixes: "the batch container has no 'aws' CLI (needed for S3 I/O)").
#
# Ubuntu 24.04 (this image's base) carries no `awscli` apt package at all
# (dropped from the archive) -- installed instead via AWS's own official
# installer, using `curl`/`unzip`, BOTH of which this base image already
# ships (verified: no new base dependency introduced by this). The version
# is pinned for a reproducible, tested image; bump the number here (and the
# TESTED_IMAGES digest in cryostack_src/models/stack/images.py once the
# rebuilt image is pushed) to pick up a newer AWS CLI release.
RUN set -eu \
    && AWSCLI_VERSION=2.36.40 \
    && cd /tmp \
    && curl -fsSL \
        "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-${AWSCLI_VERSION}.zip" \
        -o awscliv2.zip \
    && unzip -q awscliv2.zip \
    && ./aws/install \
    && rm -rf /tmp/awscliv2.zip /tmp/aws \
    && aws --version

# ── Cache directory helper ────────────────────────────────────
RUN printf '%s\n' \
    '#!/bin/sh' \
    'set -e' \
    'USER_NAME="${USER:-$(id -un 2>/dev/null || echo user)}"' \
    'choose_cache_base() {' \
    '    for cand in "${APPTAINER_CACHEDIR:-}" "${SINGULARITY_CACHEDIR:-}" "/scratch/${USER_NAME}/combined_cache" "/tmp/${USER_NAME}/combined_cache" "/var/tmp/${USER_NAME}/combined_cache"; do' \
    '        [ -n "$cand" ] || continue' \
    '        if mkdir -p "$cand" 2>/dev/null; then echo "$cand"; return 0; fi' \
    '    done' \
    '    return 1' \
    '}' \
    'BASE_CACHE="$(choose_cache_base)" || { echo "ERROR: could not create a writable cache directory" >&2; exit 1; }' \
    'mkdir -p "${BASE_CACHE}/pyop2" "${BASE_CACHE}/tsfc" "${BASE_CACHE}/xdg" "${BASE_CACHE}/matplotlib"' \
    'export PERSISTENT_DIR="${BASE_CACHE}"' \
    'export PYOP2_CACHE_DIR="${BASE_CACHE}/pyop2"' \
    'export FIREDRAKE_TSFC_KERNEL_CACHE_DIR="${BASE_CACHE}/tsfc"' \
    'export XDG_CACHE_HOME="${BASE_CACHE}/xdg"' \
    'export MPLCONFIGDIR="${BASE_CACHE}/matplotlib"' \
    > /opt/set_persistent_dir.sh \
    && chmod +x /opt/set_persistent_dir.sh

# ── with-firedrake ────────────────────────────────────────────
RUN printf '%s\n' \
    '#!/bin/bash' \
    'set -e' \
    '. /opt/set_persistent_dir.sh' \
    '[ -f /opt/venv-icesee/bin/activate ] && . /opt/venv-icesee/bin/activate' \
    'if [ "$#" -eq 0 ]; then exec /usr/local/bin/activate-firedrake bash' \
    'else exec /usr/local/bin/activate-firedrake "$@"; fi' \
    > /usr/local/bin/with-firedrake && chmod +x /usr/local/bin/with-firedrake

# ── with-icepack ──────────────────────────────────────────────
RUN printf '%s\n' \
    '#!/bin/bash' \
    'set -e' \
    '. /opt/set_persistent_dir.sh' \
    '[ -f /opt/venv-icesee/bin/activate ] && . /opt/venv-icesee/bin/activate' \
    'if [ "$#" -eq 0 ]; then exec /usr/local/bin/activate-icepack bash' \
    'else exec /usr/local/bin/activate-icepack "$@"; fi' \
    > /usr/local/bin/with-icepack && chmod +x /usr/local/bin/with-icepack

# ── with-icesee ───────────────────────────────────────────────
RUN printf '%s\n' \
    '#!/bin/sh' \
    'set -e' \
    '. /opt/set_persistent_dir.sh' \
    'if [ "$#" -eq 0 ]; then exec /usr/local/bin/activate-icesee bash' \
    'else exec /usr/local/bin/activate-icesee "$@"; fi' \
    > /usr/local/bin/with-icesee && chmod +x /usr/local/bin/with-icesee

# ── with-issm ─────────────────────────────────────────────────
RUN printf '%s\n' \
    '#!/bin/bash' \
    'set -e' \
    '. /opt/set_persistent_dir.sh' \
    'export ISSM_DIR="${ISSM_DIR:-/opt/ISSM}"' \
    '. /opt/venv-icesee/bin/activate' \
    'ICESEE_MPI_ROOT="/opt/spack/linux-skylake/openmpi-5.0.10-f5se2v23aaj7xdbrgzf6zpdjjnbt6lmj"' \
    'ICESEE_HDF5_ROOT="/opt/spack/linux-skylake/hdf5-1.14.5-oomu4lo2wkwg4ufbuiumyjuimwhmlp4o"' \
    'export PATH="${ICESEE_MPI_ROOT}/bin:${PATH:-}"' \
    'export LD_LIBRARY_PATH="${ICESEE_MPI_ROOT}/lib:${ICESEE_HDF5_ROOT}/lib:${LD_LIBRARY_PATH:-}"' \
    'if [ -f "${ISSM_DIR}/etc/environment.sh" ]; then set +u; . "${ISSM_DIR}/etc/environment.sh"; set -u; fi' \
    'export PATH="${ICESEE_MPI_ROOT}/bin:${PATH:-}"' \
    'export LD_LIBRARY_PATH="${ICESEE_MPI_ROOT}/lib:${ICESEE_HDF5_ROOT}/lib:${LD_LIBRARY_PATH:-}"' \
    'if [ "$#" -eq 0 ]; then exec /bin/bash; else exec "$@"; fi' \
    > /usr/local/bin/with-issm && chmod +x /usr/local/bin/with-issm

# ── issm-matlab ───────────────────────────────────────────────
RUN printf '%s\n' \
    '#!/bin/bash' \
    'set -e' \
    '. /opt/set_persistent_dir.sh' \
    'export ISSM_DIR="${ISSM_DIR:-/opt/ISSM}"' \
    '[ -f "${ISSM_DIR}/etc/environment.sh" ] && . "${ISSM_DIR}/etc/environment.sh"' \
    'exec matlab -r "addpath('"'"'${ISSM_DIR}/bin'"'"','"'"'${ISSM_DIR}/lib'"'"');"' \
    > /usr/local/bin/issm-matlab && chmod +x /usr/local/bin/issm-matlab

# ── MATLAB startup.m ──────────────────────────────────────────
RUN mkdir -p /opt/matlab && printf '%s\n' \
    "isdir_bin = exist('/opt/ISSM/bin','dir');" \
    "isdir_lib = exist('/opt/ISSM/lib','dir');" \
    "if isdir_bin == 7; addpath('/opt/ISSM/bin'); end" \
    "if isdir_lib == 7; addpath('/opt/ISSM/lib'); end" \
    > /opt/matlab/startup.m

# ── %environment ──────────────────────────────────────────────
ENV OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    HDF5_MPI=ON \
    ISSM_DIR=/opt/ISSM \
    MLM_LICENSE_FILE=1711@matlablic.ecs.gatech.edu \
    MATLABPATH=/opt/matlab \
    PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    MPLCONFIGDIR=/tmp/matplotlib \
    PMIX_MCA_psec=native \
    PYTHONPATH=/opt \
    ICESEE_CONTAINER=1

# ── %runscript → ENTRYPOINT ───────────────────────────────────
# Sources cache dirs then exec's the given command or falls back to bash.
RUN printf '%s\n' \
    '#!/bin/sh' \
    'set -e' \
    '. /opt/set_persistent_dir.sh' \
    'if [ "$#" -gt 0 ]; then exec "$@"; else exec /bin/bash; fi' \
    > /usr/local/bin/docker-entrypoint.sh && chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["bash"]

# ── Labels (from %labels) ─────────────────────────────────────
LABEL maintainer="Brian Kyanjo" \
      name="Combined Lean container" \
      description="Combined runtime with built-in MATLAB base image"