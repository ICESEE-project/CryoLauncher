# ============================================================
# Remote backend (system ssh + Slurm)
# ============================================================

from __future__ import annotations

import os
import re
import time
import json
import base64
import tarfile
import tempfile
import zipfile
import shutil
import getpass
import subprocess
from pathlib import Path
import urllib.request
import urllib.error
from dataclasses import dataclass

@dataclass
class RemoteSubmitResult:
    success: bool
    jobid: str | None
    remote_dir: str
    remote_example_dir: str | None
    spack_path: str | None
    used_existing_sbatch: bool
    existing_sbatch_name: str | None
    messages: list[str]


def require_remote_base_dir(value):
    """Fail closed on a missing remote working directory (no developer default).

    Imported lazily to avoid a circular import via cryostack_src.remote.__init__.
    """
    from cryostack_src.remote.runtime import require_remote_base_dir as _impl
    return _impl(value)

def resolve_remote_abs_path(host: str, user: str, port: int, remote_path: str) -> str:
    rc, out, err = rsh(
        host,
        user,
        port,
        f"python3 - <<'PY'\nimport os\nprint(os.path.abspath(os.path.expanduser({remote_path!r})))\nPY",
        timeout=20,
    )
    resolved = (out or "").strip()
    if rc != 0 or not resolved:
        raise RuntimeError(f"Could not resolve remote absolute path: {remote_path}\n{err or out}")
    return resolved

def relay_result_payload(result: dict) -> dict:
    return result.get("result", result)

def submit_remote_example(
    *,
    host: str,
    user: str,
    port: int,
    example_cfg: dict,
    params_text: str,
    remote_base_dir: str,
    remote_tag: str,
    spack_enable: bool,
    spack_repo_url: str,
    spack_dirname: str,
    spack_install_if_needed: bool,
    spack_install_mode: str,
    spack_slurm_dir: str,
    spack_pmix_dir: str,
    spack_use_existing_sbatch: bool,
    slurm_time: str,
    slurm_job_name: str,
    slurm_nodes: int,
    slurm_ntasks: int,
    slurm_tpn: int,
    slurm_part: str,
    slurm_mem: str,
    slurm_account: str,
    slurm_mail: str,
    remote_module_lines: str,
    remote_export_lines: str,
    cluster_mpi_np: int,
    ens_size: int,
    cluster_model_nprocs: int,
) -> RemoteSubmitResult:
    messages: list[str] = []

    if not host or not user:
        raise ValueError("Provide Host + User first.")

    rdir = make_remote_run_dir(
        require_remote_base_dir(remote_base_dir),
        remote_tag.strip() or "icesee",
    )
    messages.append(f"[remote] Remote run dir: {rdir}")

    spack_path = None
    if spack_enable:
        spack_parent = require_remote_base_dir(remote_base_dir)
        spack_name = spack_dirname.strip() or "ICESEE-Spack"
        repo = spack_repo_url.strip()

        messages.append("[remote] Spack enabled")
        messages.append(f"  parent: {spack_parent}")
        messages.append(f"  repo  : {repo}")
        messages.append(f"  name  : {spack_name}")

        spack_path, (rc, out, err) = remote_ensure_spack(
            host, user, port, spack_parent, spack_name, repo
        )
        if out.strip():
            messages.append(out.strip())
        if err.strip():
            messages.append(err.strip())
        if rc != 0:
            raise RuntimeError("Failed to ensure ICESEE-Spack on remote host.")

        spack_path = resolve_remote_abs_path(host, user, port, spack_path)
        messages.append(f"[remote] Resolved ICESEE-Spack path: {spack_path}")

        if spack_install_if_needed:
            install_flag = spack_install_mode or ""
            messages.append(f"[remote] Spack install requested: {install_flag or '(default)'}")
            rc, out, err = remote_maybe_install_spack(
                host, user, port, spack_path, install_flag, spack_slurm_dir, spack_pmix_dir
            )
            if out.strip():
                messages.append(out.strip())
            if err.strip():
                messages.append(err.strip())
            if rc != 0:
                raise RuntimeError("Remote ICESEE-Spack install failed.")
    else:
        raise RuntimeError("Remote currently requires ICESEE-Spack enabled.")

    remote_rel = example_cfg.get("remote_rel")
    if not remote_rel:
        raise RuntimeError("This example has no remote_rel configured in EXAMPLES.")

    remote_example_dir = f"{spack_path.rstrip('/')}/{remote_rel.lstrip('/')}"
    messages.append(f"[remote] Remote example dir : {remote_example_dir}")

    rc, out, err = rsh(
        host, user, port,
        f"test -d {sh_quote(remote_example_dir)} && echo OK || echo MISSING",
        timeout=20,
    )
    if "OK" not in (out or ""):
        raise RuntimeError(
            f"Remote example directory not found.\nstdout: {(out or '').strip()}\nstderr: {(err or '').strip()}"
        )

    remote_sbatch = example_cfg.get("remote_sbatch")
    if spack_use_existing_sbatch and remote_sbatch:
        chk = f"test -f {sh_quote(remote_example_dir + '/' + remote_sbatch)} && echo OK || echo MISSING"
        rc2, out2, err2 = rsh(host, user, port, chk, timeout=20)

        if "OK" in (out2 or ""):
            remote_write_text(host, user, port, f"{rdir}/params.yaml", params_text, timeout=30)
            rsh(
                host, user, port,
                f"cp {sh_quote(rdir+'/params.yaml')} {sh_quote(remote_example_dir+'/params.yaml')}",
                timeout=20,
            )

            submit_cmd = f"""
set -e
cd {sh_quote(remote_example_dir)}
source {sh_quote(spack_path)}/scripts/activate.sh
sbatch {sh_quote(remote_sbatch)}
"""
            r = ssh_run(host, user, port, submit_cmd, timeout=30)
            if r.returncode != 0:
                raise RuntimeError(r.stderr or r.stdout)

            m = re.search(r"Submitted batch job\s+(\d+)", r.stdout)
            if not m:
                raise RuntimeError(f"Could not parse JobID from:\n{r.stdout}\n{r.stderr}")

            jobid = m.group(1)
            messages.append("[remote] ✅ Submitted existing sbatch from example dir")
            messages.append(f"  sbatch: {remote_sbatch}")
            messages.append(f"  jobid : {jobid}")

            return RemoteSubmitResult(
                success=True,
                jobid=jobid,
                remote_dir=remote_example_dir,
                remote_example_dir=remote_example_dir,
                spack_path=spack_path,
                used_existing_sbatch=True,
                existing_sbatch_name=remote_sbatch,
                messages=messages,
            )

        messages.append("[remote] NOTE: remote_sbatch configured but not found; falling back to generated slurm_run.sh.")

    account_line, mail_lines = slurm_optional_lines(slurm_account.strip(), slurm_mail.strip())

    outfile = "icesee-enkf-%j.out"
    run_script_name = example_cfg.get("run_script")

    slurm_text = render_slurm_script(
        dict(
            TIME=slurm_time.strip(),
            JOB_NAME=slurm_job_name.strip() or "ICESEE",
            NODES=int(slurm_nodes),
            NTASKS=int(slurm_ntasks),
            TPN=int(slurm_tpn),
            PARTITION=slurm_part.strip(),
            MEM=slurm_mem.strip(),
            ACCOUNT_LINE=account_line,
            MAIL_LINES=mail_lines,
            OUTFILE=outfile,
            MODULE_LINES=sanitize_multiline(remote_module_lines),
            EXPORT_LINES=sanitize_multiline(remote_export_lines),
            SPACK_PATH=spack_path,
            NP=int(cluster_mpi_np),
            NENS=int(ens_size),
            MODEL_NPROCS=int(cluster_model_nprocs),
            RUN_SCRIPT=run_script_name,
            PARAMS_PATH=f"{rdir}/params.yaml",
            EXAMPLE_DIR=remote_example_dir,
            SRUN_MPI_FLAG="--mpi=pmix",
        )
    )

    if "{{" in slurm_text or "}}" in slurm_text:
        raise RuntimeError("SLURM_TEMPLATE render left unresolved placeholders. Check keys passed to render_slurm_script().")

    messages.append("[remote] Writing params.yaml + slurm_run.sh, then sbatch…")

    jobid = remote_stage_and_submit(
        host=host,
        user=user,
        port=port,
        remote_dir=rdir,
        params_text=params_text,
        slurm_text=slurm_text,
    )

    messages.append("[remote] ✅ Submitted generated slurm_run.sh")
    messages.append(f"  jobid : {jobid}")
    messages.append(f"  rdir  : {rdir}")
    messages.append(f"  example dir: {remote_example_dir}")

    return RemoteSubmitResult(
        success=True,
        jobid=jobid,
        remote_dir=rdir,
        remote_example_dir=remote_example_dir,
        spack_path=spack_path,
        used_existing_sbatch=False,
        existing_sbatch_name=None,
        messages=messages,
    )

def submit_remote_example_container(
    *,
    host: str,
    user: str,
    port: int,
    example_cfg: dict,
    params_text: str,
    remote_base_dir: str,
    remote_tag: str,
    spack_repo_url: str,
    spack_dirname: str,
    slurm_time: str,
    slurm_job_name: str,
    slurm_nodes: int,
    slurm_ntasks: int,
    slurm_tpn: int,
    slurm_part: str,
    slurm_mem: str,
    slurm_account: str,
    slurm_mail: str,
    remote_module_lines: str,
    remote_export_lines: str,
    cluster_mpi_np: int,
    ens_size: int,
    cluster_model_nprocs: int,
    container_source: str,
    container_image_uri: str,
) -> RemoteSubmitResult:
    messages: list[str] = []

    if not host or not user:
        raise ValueError("Provide Host + User first.")

    rdir = make_remote_run_dir(
        require_remote_base_dir(remote_base_dir),
        remote_tag.strip() or "icesee",
    )
    messages.append(f"[remote] Remote run dir: {rdir}")

    # keep using ICESEE-Spack to locate the example directory and scripts
    spack_parent = require_remote_base_dir(remote_base_dir)
    spack_name = spack_dirname.strip() or "ICESEE-Spack"
    repo = spack_repo_url.strip()

    messages.append("[remote] Container backend enabled")
    messages.append(f"  spack parent: {spack_parent}")
    messages.append(f"  spack repo  : {repo}")
    messages.append(f"  spack name  : {spack_name}")

    spack_path, (rc, out, err) = remote_ensure_spack(
        host, user, port, spack_parent, spack_name, repo
    )
    if out.strip():
        messages.append(out.strip())
    if err.strip():
        messages.append(err.strip())
    if rc != 0:
        raise RuntimeError("Failed to ensure ICESEE-Spack on remote host.")

    spack_path = resolve_remote_abs_path(host, user, port, spack_path)
    messages.append(f"[remote] Resolved ICESEE-Spack path: {spack_path}")

    remote_rel = example_cfg.get("remote_rel")
    if not remote_rel:
        raise RuntimeError("This example has no remote_rel configured in EXAMPLES.")

    remote_example_dir = f"{spack_path.rstrip('/')}/{remote_rel.lstrip('/')}"
    messages.append(f"[remote] Remote example dir : {remote_example_dir}")

    rc, out, err = rsh(
        host, user, port,
        f"test -d {sh_quote(remote_example_dir)} && echo OK || echo MISSING",
        timeout=20,
    )
    if "OK" not in (out or ""):
        raise RuntimeError(
            f"Remote example directory not found.\nstdout: {(out or '').strip()}\nstderr: {(err or '').strip()}"
        )

    account_line, mail_lines = slurm_optional_lines(slurm_account.strip(), slurm_mail.strip())

    resolved_base = resolve_remote_abs_path(host, user, port, require_remote_base_dir(remote_base_dir))
    remote_root = f"{resolved_base.rstrip('/')}/{remote_tag.strip() or 'icesee'}"
    container_root = f"{remote_root}/ICESEE-Containers"
    container_dir = f"{container_root}/spack-managed/combined-container"
    sif_path = f"{container_dir}/combined-env.sif"
    def_path = f"{container_dir}/combined-env-inbuilt-matlab.def"

    run_script_name = example_cfg.get("run_script")
    outfile = f"{rdir}/icesee-enkf-%j.out"

    slurm_text = f"""#!/bin/bash
#SBATCH -t {slurm_time.strip()}
#SBATCH -J {slurm_job_name.strip() or "ICESEE"}
#SBATCH -N {int(slurm_nodes)}
#SBATCH -n {int(slurm_ntasks)}
#SBATCH --ntasks-per-node={int(slurm_tpn)}
#SBATCH -p {slurm_part.strip()}
#SBATCH --mem={slurm_mem.strip()}
{account_line}
#SBATCH -o {outfile}
{mail_lines}

set -euo pipefail
cd "${{SLURM_SUBMIT_DIR}}"

module purge || true
{sanitize_multiline(remote_module_lines)}

{sanitize_multiline(remote_export_lines)}

echo "[icesee] Host: $(hostname)"
echo "[icesee] Date: $(date)"
echo "[icesee] PWD : $(pwd)"

echo "[icesee] Checking apptainer..."
if ! command -v apptainer >/dev/null 2>&1; then
  echo "[icesee] apptainer not found in PATH. Trying module load apptainer..."
  source /etc/profile >/dev/null 2>&1 || true
  module load apptainer >/dev/null 2>&1 || true
fi

if ! command -v apptainer >/dev/null 2>&1; then
  echo "[icesee][ERROR] apptainer not found, and module load apptainer failed."
  exit 2
fi

mkdir -p "{remote_root}"

if [ ! -d "{container_root}" ]; then
  echo "[icesee] Cloning ICESEE-Containers..."
  git clone https://github.com/ICESEE-project/ICESEE-Containers.git "{container_root}"
fi

cd "{container_dir}"

if [ ! -f "{sif_path}" ]; then
  if [ ! -f "{def_path}" ]; then
    echo "[icesee][ERROR] Definition file not found: {def_path}"
    exit 2
  fi
  echo "[icesee] Building Apptainer image..."
  apptainer build combined-env.sif combined-env-inbuilt-matlab.def
else
  echo "[icesee] Using existing Apptainer image: {sif_path}"
fi

cd "{remote_example_dir}"

# bind example dir and run dir to the same absolute paths inside the container
if command -v srun >/dev/null 2>&1; then
  /usr/bin/time -v \\
    srun --mpi=pmix -n "{int(cluster_mpi_np)}" \\
      apptainer exec \\
      -B "{remote_example_dir}:{remote_example_dir},{rdir}:{rdir}" \\
      "{sif_path}" \\
      python "{run_script_name}" \\
        -F "{rdir}/params.yaml" \\
        --Nens="{int(ens_size)}" \\
        --model_nprocs="{int(cluster_model_nprocs)}" \\
        --verbose
else
  /usr/bin/time -v \\
    apptainer exec \\
      -B "{remote_example_dir}:{remote_example_dir},{rdir}:{rdir}" \\
      "{sif_path}" \\
      python "{run_script_name}" \\
        -F "{rdir}/params.yaml" \\
        --Nens="{int(ens_size)}" \\
        --model_nprocs="{int(cluster_model_nprocs)}" \\
        --verbose
fi

echo "=== Finished ==="
"""

    messages.append("[remote] Writing params.yaml + slurm_run.sh, then sbatch…")

    jobid = remote_stage_and_submit(
        host=host,
        user=user,
        port=port,
        remote_dir=rdir,
        params_text=params_text,
        slurm_text=slurm_text,
    )

    messages.append("[remote] ✅ Submitted container-based slurm_run.sh")
    messages.append(f"  jobid : {jobid}")
    messages.append(f"  rdir  : {rdir}")
    messages.append(f"  example dir: {remote_example_dir}")
    messages.append(f"  image : {sif_path}")

    return RemoteSubmitResult(
        success=True,
        jobid=jobid,
        remote_dir=rdir,
        remote_example_dir=remote_example_dir,
        spack_path=spack_path,
        used_existing_sbatch=False,
        existing_sbatch_name=None,
        messages=messages,
    )

def sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _ssh_base(host: str, user: str, port: int):
    target = f"{user}@{host}" if user else host
    return [
        "ssh",
        "-p", str(int(port)),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=10",
        "-o", "ServerAliveCountMax=2",
        target,
    ]


def ssh_run(host: str, user: str, port: int, remote_cmd: str, timeout: int = 20):
    cmd = _ssh_base(host, user, port) + [remote_cmd]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

def http_json(method: str, url: str, payload: dict | None = None, headers: dict | None = None, timeout: int = 20):
    headers = headers or {}
    data = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        data = body
        headers = {**headers, "Content-Type": "application/json"}

    req = urllib.request.Request(url=url, data=data, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            txt = resp.read().decode("utf-8", errors="replace")
            # try JSON; fall back to text
            try:
                return resp.status, json.loads(txt), txt
            except Exception:
                return resp.status, None, txt
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
        return e.code, None, txt

def make_remote_run_dir(base_dir: str, tag: str = "icesee") -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"{base_dir.rstrip('/')}/{tag}-{ts}"


SLURM_TEMPLATE = """#!/bin/bash
#SBATCH -t {{TIME}}
#SBATCH -J {{JOB_NAME}}
#SBATCH -N {{NODES}}
#SBATCH -n {{NTASKS}}
#SBATCH --ntasks-per-node={{TPN}}
#SBATCH -p {{PARTITION}}
#SBATCH --mem={{MEM}}
{{ACCOUNT_LINE}}
#SBATCH -o {{OUTFILE}}
{{MAIL_LINES}}

set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"

# --- Modules (optional; provided by UI) ---
module purge || true
{{MODULE_LINES}}

# --- Activate ICESEE-Spack env ---
SPACK_PATH="{{SPACK_PATH}}"
if [ ! -d "${SPACK_PATH}" ]; then
  echo "[ERROR] SPACK_PATH does not exist: ${SPACK_PATH}"
  exit 2
fi
source "${SPACK_PATH}/scripts/activate.sh"

# --- Optional: add MPI from spack env to PATH/LD_LIBRARY_PATH ---
# Many spack envs already handle this; keep it robust:
if command -v spack >/dev/null 2>&1; then
  # Use the env inside the repo (if it exists)
  ENV_DIR="${SPACK_PATH}/.spack-env/icesee"
  if [ -d "${ENV_DIR}" ]; then
    MPI_DIR="$(spack -e "${ENV_DIR}" location -i openmpi 2>/dev/null || true)"
    if [ -n "${MPI_DIR}" ] && [ -d "${MPI_DIR}" ]; then
      export PATH="${MPI_DIR}/bin:${PATH}"
      export LD_LIBRARY_PATH="${MPI_DIR}/lib:${LD_LIBRARY_PATH:-}"
      echo "[info] MPI_DIR=${MPI_DIR}"
    else
      echo "[info] openmpi not resolved via spack -e ${ENV_DIR} (ok if system MPI is used)"
    fi
  fi
fi

# --- Exports (optional; provided by UI) ---
{{EXPORT_LINES}}

# --- Run config from UI ---
NP="{{NP}}"
NENS="{{NENS}}"
MODEL_NPROCS="{{MODEL_NPROCS}}"
RUN_SCRIPT="{{RUN_SCRIPT}}"
PARAMS_PATH="{{PARAMS_PATH}}"
EXAMPLE_DIR="{{EXAMPLE_DIR}}"

if [ ! -d "${EXAMPLE_DIR}" ]; then
  echo "[ERROR] EXAMPLE_DIR missing: ${EXAMPLE_DIR}"
  exit 3
fi

cd "${EXAMPLE_DIR}"

echo "[run] hostname=$(hostname)"
echo "[run] pwd=$(pwd)"
echo "[run] NP=${NP} NENS=${NENS} MODEL_NPROCS=${MODEL_NPROCS}"
echo "[run] RUN_SCRIPT=${RUN_SCRIPT}"
echo "[run] PARAMS_PATH=${PARAMS_PATH}"

# --- Launcher: prefer srun on Slurm clusters; fallback to mpirun ---
if command -v srun >/dev/null 2>&1; then
  /usr/bin/time -v \
    srun {{SRUN_MPI_FLAG}} -n "${NP}" \
      python "${RUN_SCRIPT}" \
        -F "${PARAMS_PATH}" \
        --Nens="${NENS}" \
        --model_nprocs="${MODEL_NPROCS}" \
        --verbose
else
  /usr/bin/time -v \
    mpirun -np "${NP}" \
      python "${RUN_SCRIPT}" \
        -F "${PARAMS_PATH}" \
        --Nens="${NENS}" \
        --model_nprocs="${MODEL_NPROCS}" \
        --verbose
fi

echo "=== Finished ==="
"""

def slurm_optional_lines(account: str, mail: str) -> tuple[str, str]:
    account_line = f"#SBATCH -A {account.strip()}" if account.strip() else ""
    if mail.strip():
        mail_lines = "\n".join([
            "#SBATCH --mail-type=BEGIN,END,FAIL",
            f"#SBATCH --mail-user={mail.strip()}",
        ])
    else:
        mail_lines = ""
    return account_line, mail_lines

def sanitize_multiline(s: str) -> str:
    # keep user text but strip trailing spaces
    return "\n".join([ln.rstrip() for ln in (s or "").splitlines() if ln.strip() != ""])

def render_slurm_script(d: dict) -> str:
    txt = SLURM_TEMPLATE
    for k, v in d.items():
        txt = txt.replace("{{" + k + "}}", str(v))
    return txt


def remote_write_text(host: str, user: str, port: int, remote_path: str, text: str, timeout: int = 30):
    cmd = f"""
set -e
mkdir -p $(dirname {sh_quote(remote_path)})
cat > {sh_quote(remote_path)} <<'EOF_ICESEE'
{text.rstrip()}
EOF_ICESEE
"""
    r = ssh_run(host, user, port, cmd, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout)

def remote_stage_and_submit(
    *,
    host: str,
    user: str,
    port: int,
    remote_dir: str,
    params_text: str,
    slurm_text: str,
) -> str:
    # stage files in remote_dir
    remote_write_text(host, user, port, f"{remote_dir}/params.yaml", params_text, timeout=30)
    remote_write_text(host, user, port, f"{remote_dir}/slurm_run.sh", slurm_text, timeout=30)

    # make executable and submit
    r = ssh_run(host, user, port, f"chmod +x {sh_quote(remote_dir+'/slurm_run.sh')} && cd {sh_quote(remote_dir)} && sbatch slurm_run.sh", timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout)

    m = re.search(r"Submitted batch job\s+(\d+)", r.stdout)
    if not m:
        raise RuntimeError(f"Could not parse JobID from:\n{r.stdout}\n{r.stderr}")
    return m.group(1)

def ensure_local_ssh_key(key_type: str = "ed25519") -> tuple[Path, Path]:
    """
    Ensure ~/.ssh/id_<type> and .pub exist. If not, generate them non-interactively.
    Returns (private_key_path, public_key_path).
    """
    ssh_dir = Path.home() / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ssh_dir, 0o700)

    priv = ssh_dir / f"id_{key_type}"
    pub  = ssh_dir / f"id_{key_type}.pub"

    if pub.exists() and priv.exists():
        return priv, pub

    # Generate keypair
    cmd = [
        "ssh-keygen",
        "-t", key_type,
        "-f", str(priv),
        "-N", "",                 # empty passphrase (for non-interactive GHUB use)
        "-C", f"icesee-{getpass.getuser()}",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr or p.stdout or "ssh-keygen failed")

    os.chmod(priv, 0o600)
    os.chmod(pub, 0o644)
    return priv, pub

def connector_slurm_submit(
    session_id: str,
    host: str,
    user: str,
    port: int,
    remote_script: str,
    timeout: int = 60,
    cluster_name: str = "pace",
):
    from icesee_jupyter_book.core.connector_relay_client import send_command

    res = send_command(
        session_id,
        "slurm-submit",
        {
            "host": host,
            "user": user,
            "port": int(port),
            "remote_script": remote_script,
            "timeout": timeout,
            "cluster_name": cluster_name,
        },
    )
    return relay_result_payload(res)

def _paramiko_connect_password(host: str, user: str, port: int, password: str, timeout: int = 20):
    try:
        import paramiko
    except Exception as e:
        raise RuntimeError(
            "Paramiko is required for password bootstrap. Install with: pip install paramiko"
        ) from e

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=int(port),
        username=user,
        password=password,
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
        look_for_keys=False,
        allow_agent=False,
    )
    return client


def remote_install_pubkey_with_password(
    *,
    host: str,
    user: str,
    port: int,
    password: str,
    pubkey_text: str
):
    """
    Connect using Paramiko password auth and add pubkey to ~/.ssh/authorized_keys safely.
    Idempotent: won't duplicate the key if already installed.
    """
    client = _paramiko_connect_password(host, user, port, password, timeout=25)

    # Normalize key line
    key_line = pubkey_text.strip()
    if not key_line or "ssh-" not in key_line:
        client.close()
        raise ValueError("Public key text looks invalid.")

    # Remote commands: create ~/.ssh, set perms, append key if missing
    # Using sh to keep it portable.
    cmd = f"""
set -e
mkdir -p ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
# Append key if not already present
grep -Fqx {sh_quote(key_line)} ~/.ssh/authorized_keys || echo {sh_quote(key_line)} >> ~/.ssh/authorized_keys
echo OK
"""
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    client.close()

    if rc != 0:
        raise RuntimeError(err or out or "Failed to update authorized_keys")


def explain_ssh_failure_hint(stderr: str) -> str:
    s = (stderr or "").lower()
    if "permission denied" in s:
        return "Auth failed (Permission denied). If you normally type a password in a terminal, use Bootstrap with password once."
    if "could not resolve hostname" in s:
        return "Host not reachable / DNS issue."
    if "operation timed out" in s or "connection timed out" in s:
        return "Connection timed out (VPN/firewall/host unreachable)."
    if "keyboard-interactive" in s or "authentication" in s:
        return "Interactive auth is being requested. BatchMode blocks it; bootstrap keys or use OnDemand."
    return "SSH failed. Check host/user/VPN and whether passwordless key auth is enabled."


def rsh(host, user, port, cmd, timeout=600):
    """SSH run with a timeout and returned stdout/stderr."""
    r = ssh_run(host, user, port, cmd, timeout=timeout)
    return r.returncode, r.stdout, r.stderr

def remote_ensure_spack(host, user, port, remote_parent_dir, spack_name, repo_url):
    """
    Ensure ICESEE-Spack is cloned inside remote_parent_dir/spack_name.
    """
    spack_path = f"{remote_parent_dir.rstrip('/')}/{spack_name}"
    cmd = f"""
set -e
mkdir -p {sh_quote(remote_parent_dir)}
if [ ! -d {sh_quote(spack_path)} ]; then
echo "[spack] cloning {repo_url} -> {spack_path}"
cd {sh_quote(remote_parent_dir)}
git clone {sh_quote(repo_url)} {sh_quote(spack_name)}
else
echo "[spack] exists: {spack_path}"
fi
echo "[spack] done"
"""
    return spack_path, rsh(host, user, port, cmd, timeout=180)

def remote_maybe_install_spack(host, user, port, spack_path, install_flag, slurm_dir, pmix_dir):
    """
    Run scripts/install.sh (idempotent-ish) if user requested.
    Uses a marker file to avoid re-running.
    """
    marker = f"{spack_path}/.icesee_spack_installed"
    slurm = slurm_dir.strip()
    pmix  = pmix_dir.strip()

    # Build env prefix only if provided
    env_prefix = ""
    # if slurm:
    #     env_prefix += f"SLURM_DIR={sh_quote(slurm)} "
    # if pmix:
    #     env_prefix += f"PMIX_DIR={sh_quote(pmix)} "

    cmd = f"""
set -e
cd {sh_quote(spack_path)}
if [ -f {sh_quote(marker)} ]; then
echo "[spack] install marker present: {marker}"
exit 0
fi
echo "[spack] running install.sh {install_flag}"
{env_prefix} ./scripts/install.sh {install_flag}
touch {sh_quote(marker)}
echo "[spack] install completed"
"""
    return rsh(host, user, port, cmd, timeout=60*60)  # installs can be long


def remote_test_connection(host: str, user: str, port: int) -> dict:
    r = ssh_run(host, user, port, "hostname && whoami && date", timeout=15)
    return {
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
        "ok": (r.returncode == 0),
    }


def remote_job_status(
    host: str,
    user: str,
    port: int,
    jobid: str,
) -> dict:
    # ---------------------------------------------------------
    # First: live queue
    # ---------------------------------------------------------
    r = ssh_run(
        host,
        user,
        port,
        (
            f"squeue -j {jobid} "
            "-h -o '%i|%T|%M|%D|%R'"
        ),
        timeout=15,
    )

    squeue_out = (r.stdout or "").strip()

    if r.returncode == 0 and squeue_out:
        parts = squeue_out.splitlines()[0].split("|")

        return {
            "returncode": r.returncode,
            "stdout": r.stdout,
            "stderr": r.stderr,
            "source": "squeue",
            "state": (
                parts[1].strip()
                if len(parts) > 1
                else None
            ),
            "exit_code": None,
        }

    # ---------------------------------------------------------
    # Job left squeue: query Slurm accounting
    # ---------------------------------------------------------
    a = ssh_run(
        host,
        user,
        port,
        (
            f"sacct -j {jobid} "
            "--noheader "
            "--parsable2 "
            "--format=JobIDRaw,State,ExitCode"
        ),
        timeout=15,
    )

    state = None
    exit_code = None

    if a.returncode == 0:
        for line in (a.stdout or "").splitlines():
            line = line.strip()

            if not line:
                continue

            parts = line.split("|")

            if len(parts) < 3:
                continue

            row_jobid = parts[0].strip()

            # Prefer the parent job, not .batch/.extern steps.
            if row_jobid == str(jobid):
                state = parts[1].strip()
                exit_code = parts[2].strip()
                break

    return {
        "returncode": a.returncode,
        "stdout": a.stdout,
        "stderr": a.stderr,
        "source": "sacct",
        "state": state,
        "exit_code": exit_code,
    }


def remote_tail_log(host: str, user: str, port: int, remote_dir: str, jobid: str, n: int = 120) -> dict:
    out_file = f"{remote_dir}/icesee-enkf-{jobid}.out"
    cmd = f"test -f {sh_quote(out_file)} && tail -n {int(n)} {sh_quote(out_file)} || echo 'log not yet created'"
    r = ssh_run(host, user, port, cmd, timeout=15)
    return {
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
        "log_file": out_file,
    }


def remote_cancel_job(host: str, user: str, port: int, jobid: str) -> dict:
    r = ssh_run(host, user, port, f"scancel {jobid}", timeout=15)
    return {
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
        "ok": (r.returncode == 0),
    }

def connector_ssh(
    session_id: str,
    host: str,
    user: str,
    port: int,
    command: str,
    timeout: int = 60,
    cluster_name: str = "pace",
):
    from icesee_jupyter_book.core.connector_relay_client import send_command

    res = send_command(
        session_id,
        "ssh-run",
        {
            "host": host,
            "user": user,
            "port": int(port),
            "command": command,
            "timeout": int(timeout),
            "cluster_name": cluster_name,
        },
    )
    return relay_result_payload(res)


def connector_fetch_archive(
    session_id: str,
    host: str,
    user: str,
    port: int,
    remote_path: str,
    timeout: int = 600,
    cluster_name: str = "pace",
):
    from icesee_jupyter_book.core.connector_relay_client import send_command

    res = send_command(
        session_id,
        "fetch-archive",
        {
            "host": host,
            "user": user,
            "port": int(port),
            "remote_path": remote_path,
            "timeout": int(timeout),
            "cluster_name": cluster_name,
        },
    )
    return relay_result_payload(res)

def connector_install_pubkey_with_password(
    session_id: str,
    host: str,
    user: str,
    port: int,
    password: str,
    pubkey_text: str,
    timeout: int = 60,
):
    from icesee_jupyter_book.core.connector_relay_client import send_command

    res = send_command(
        session_id,
        "install-pubkey",
        {
            "host": host,
            "user": user,
            "port": int(port),
            "password": password,
            "pubkey_text": pubkey_text,
            "timeout": int(timeout),
        },
    )
    return relay_result_payload(res)

def bootstrap_passwordless_ssh(
    *,
    host: str,
    user: str,
    port: int,
    password: str,
    access_mode: str = "direct",
    session_id: str | None = None,
    cluster_name: str = "pace",
):
    if access_mode == "connector":
        if not session_id:
            raise RuntimeError("Connector bootstrap requested, but no session_id was provided.")

        from icesee_jupyter_book.core.connector_relay_client import send_command

        res = send_command(
            session_id,
            "bootstrap-passwordless-ssh",
            {
                "host": host,
                "user": user,
                "hpc_user": user,
                "port": int(port),
                "password": password,
                "cluster_name": cluster_name,
                "timeout": 180,
            },
            timeout=200,
        )

        return res.get("result", res)

    priv, pub = ensure_local_ssh_key(key_type="ed25519")
    pubkey_text = pub.read_text(encoding="utf-8").strip()

    remote_install_pubkey_with_password(
        host=host,
        user=user,
        port=port,
        password=password,
        pubkey_text=pubkey_text,
    )

    r = ssh_run(host, user, port, "hostname && whoami && date", timeout=20)

    return {
        "ok": r.returncode == 0,
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
        "private_key": str(priv),
        "public_key": str(pub),
        "messages": [
            "[auth] Local SSH key ready",
            f"[auth] private key: {priv}",
            f"[auth] public key : {pub}",
        ],
    }
    
def connector_write_text(
    session_id: str,
    host: str,
    user: str,
    port: int,
    remote_path: str,
    text: str,
    timeout: int = 60,
    cluster_name: str = "pace",
):
    import base64
    import shlex

    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")

    cmd = (
        "python3 -c "
        + shlex.quote(
            "import base64, pathlib; "
            f"p = pathlib.Path({remote_path!r}); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            f"p.write_text(base64.b64decode({encoded!r}).decode('utf-8'), encoding='utf-8'); "
            "print(str(p))"
        )
    )

    res = connector_ssh(
        session_id, host, user, port, cmd,
        timeout=timeout,
        cluster_name=cluster_name,
    )

    if not res.get("ok"):
        raise RuntimeError(
            f"Failed to write remote file through connector: {remote_path}\n"
            f"STDOUT:\n{res.get('stdout', '')}\n\n"
            f"STDERR:\n{res.get('stderr', '')}"
        )

    return res


def connector_stage_and_submit(
    *,
    session_id: str,
    host: str,
    user: str,
    port: int,
    remote_dir: str,
    params_text: str,
    slurm_text: str,
    cluster_name: str = "pace",
) -> str:
    import re

    connector_write_text(
        session_id,
        host,
        user,
        port,
        f"{remote_dir}/params.yaml",
        params_text,
        timeout=60,
        cluster_name=cluster_name,
    )

    connector_write_text(
        session_id,
        host,
        user,
        port,
        f"{remote_dir}/slurm_run.sh",
        slurm_text,
        timeout=60,
        cluster_name=cluster_name,
    )

    chmod_cmd = f"chmod +x {sh_quote(remote_dir + '/slurm_run.sh')}"
    cres = connector_ssh(session_id, host, user, port, chmod_cmd, timeout=30, cluster_name=cluster_name)
    if not cres.get("ok"):
        raise RuntimeError(
            "Failed to chmod remote slurm_run.sh through connector\n"
            f"STDOUT:\n{cres.get('stdout', '')}\n\n"
            f"STDERR:\n{cres.get('stderr', '')}"
        )

    sres = connector_slurm_submit(
        session_id,
        host,
        user,
        port,
        f"{remote_dir}/slurm_run.sh",
        timeout=60,
        cluster_name=cluster_name,
    )

    if not sres.get("ok"):
        raise RuntimeError(
            "Failed to submit remote slurm_run.sh through connector\n"
            f"STDOUT:\n{sres.get('stdout', '')}\n\n"
            f"STDERR:\n{sres.get('stderr', '')}"
        )

    if sres.get("jobid"):
        return str(sres["jobid"])

    stdout = sres.get("stdout", "") or ""
    m = re.search(r"Submitted batch job\s+(\d+)", stdout)
    if not m:
        raise RuntimeError(f"Could not parse JobID from connector submit response:\n{sres}")

    return m.group(1)


def submit_remote_example_via_connector(
    *,
    session_id: str,
    host: str,
    user: str,
    port: int,
    example_cfg: dict,
    params_text: str,
    remote_base_dir: str,
    remote_tag: str,
    spack_enable: bool,
    spack_repo_url: str,
    spack_dirname: str,
    spack_install_if_needed: bool,
    spack_install_mode: str,
    spack_slurm_dir: str,
    spack_pmix_dir: str,
    spack_use_existing_sbatch: bool,
    slurm_time: str,
    slurm_job_name: str,
    slurm_nodes: int,
    slurm_ntasks: int,
    slurm_tpn: int,
    slurm_part: str,
    slurm_mem: str,
    slurm_account: str,
    slurm_mail: str,
    remote_module_lines: str,
    remote_export_lines: str,
    cluster_mpi_np: int,
    ens_size: int,
    cluster_model_nprocs: int,
    cluster_name: str,
) -> RemoteSubmitResult:
    import re

    messages: list[str] = []

    if not session_id:
        raise RuntimeError("Missing connector session ID.")

    if not host or not user:
        raise ValueError("Provide Host + User first.")

    if not spack_enable:
        raise RuntimeError("Remote currently requires ICESEE-Spack enabled.")

    remote_base_input = require_remote_base_dir(remote_base_dir)

    rbase_cmd = (
        "python3 -c "
        + sh_quote(
            f"import os; print(os.path.abspath(os.path.expanduser({remote_base_input!r})))"
        )
    )

    rbase = connector_ssh(session_id, host, user, port, rbase_cmd, timeout=60, cluster_name=cluster_name)
    if not rbase.get("ok"):
        raise RuntimeError(
            "Failed to resolve remote base dir through connector\n"
            f"STDOUT:\n{rbase.get('stdout', '')}\n\n"
            f"STDERR:\n{rbase.get('stderr', '')}"
        )

    remote_base_abs = (rbase.get("stdout") or "").strip().splitlines()[-1]
    tag = remote_tag.strip() or "icesee"

    rdir = make_remote_run_dir(remote_base_abs, tag)
    messages.append("[connector] Using local connector / VPN bridge")
    messages.append(f"[connector] Remote base dir: {remote_base_abs}")
    messages.append(f"[connector] Remote run dir : {rdir}")

    spack_name = spack_dirname.strip() or "ICESEE-Spack"
    repo = spack_repo_url.strip()
    spack_path = f"{remote_base_abs.rstrip('/')}/{spack_name}"

    ensure_cmd = f"""
set -e
mkdir -p {sh_quote(remote_base_abs)}
if [ ! -d {sh_quote(spack_path)} ]; then
  echo "[spack] cloning {repo} -> {spack_path}"
  cd {sh_quote(remote_base_abs)}
  git clone {sh_quote(repo)} {sh_quote(spack_name)}
else
  echo "[spack] exists: {spack_path}"
fi
test -f {sh_quote(spack_path + '/scripts/activate.sh')}
echo {sh_quote(spack_path)}
"""

    eres = connector_ssh(session_id, host, user, port, ensure_cmd, timeout=600, cluster_name=cluster_name)
    if not eres.get("ok"):
        raise RuntimeError(
            "Failed to ensure ICESEE-Spack through connector\n"
            f"STDOUT:\n{eres.get('stdout', '')}\n\n"
            f"STDERR:\n{eres.get('stderr', '')}"
        )

    messages.append("[connector] Spack enabled")
    messages.append(f"[connector] ICESEE-Spack path: {spack_path}")

    if spack_install_if_needed:
        install_flag = spack_install_mode or ""
        env_prefix = ""
        # if spack_slurm_dir.strip():
        #     env_prefix += f"SLURM_DIR={sh_quote(spack_slurm_dir.strip())} "
        # if spack_pmix_dir.strip():
        #     env_prefix += f"PMIX_DIR={sh_quote(spack_pmix_dir.strip())} "

        install_cmd = f"""
set -e
cd {sh_quote(spack_path)}
echo "[spack] running install.sh {install_flag}"
{env_prefix} ./scripts/install.sh {install_flag}
echo "[spack] install completed"
"""
        ires = connector_ssh(session_id, host, user, port, install_cmd, timeout=7200, cluster_name=cluster_name)
        if not ires.get("ok"):
            raise RuntimeError(
                "Remote ICESEE-Spack install failed through connector\n"
                f"STDOUT:\n{ires.get('stdout', '')}\n\n"
                f"STDERR:\n{ires.get('stderr', '')}"
            )

    remote_rel = example_cfg.get("remote_rel")
    if not remote_rel:
        raise RuntimeError("This example has no remote_rel configured in EXAMPLES.")

    remote_example_dir = f"{spack_path.rstrip('/')}/{remote_rel.lstrip('/')}"
    messages.append(f"[connector] Remote example dir: {remote_example_dir}")

    chk = connector_ssh(
        session_id,
        host,
        user,
        port,
        f"test -d {sh_quote(remote_example_dir)} && echo OK || echo MISSING",
        timeout=30, cluster_name=cluster_name,
    )

    if not chk.get("ok") or "OK" not in (chk.get("stdout") or ""):
        raise RuntimeError(
            "Remote example directory not found through connector.\n"
            f"STDOUT:\n{chk.get('stdout', '')}\n\n"
            f"STDERR:\n{chk.get('stderr', '')}"
        )

    remote_sbatch = example_cfg.get("remote_sbatch")

    if spack_use_existing_sbatch and remote_sbatch:
        sbatch_path = f"{remote_example_dir}/{remote_sbatch}"
        chk2 = connector_ssh(
            session_id,
            host,
            user,
            port,
            f"test -f {sh_quote(sbatch_path)} && echo OK || echo MISSING",
            timeout=30, cluster_name=cluster_name,
        )

        if chk2.get("ok") and "OK" in (chk2.get("stdout") or ""):
            connector_write_text(
                session_id,
                host,
                user,
                port,
                f"{rdir}/params.yaml",
                params_text,
                timeout=60,
            )

            copy_cmd = f"cp {sh_quote(rdir + '/params.yaml')} {sh_quote(remote_example_dir + '/params.yaml')}"
            cres = connector_ssh(session_id, host, user, port, copy_cmd, timeout=30, cluster_name=cluster_name)
            if not cres.get("ok"):
                raise RuntimeError(
                    "Failed to copy params.yaml into example dir through connector\n"
                    f"STDOUT:\n{cres.get('stdout', '')}\n\n"
                    f"STDERR:\n{cres.get('stderr', '')}"
                )

            submit_cmd = f"""
set -e
cd {sh_quote(remote_example_dir)}
source {sh_quote(spack_path + '/scripts/activate.sh')}
sbatch {sh_quote(remote_sbatch)}
"""
            sres = connector_ssh(session_id, host, user, port, submit_cmd, timeout=60, cluster_name=cluster_name)
            if not sres.get("ok"):
                raise RuntimeError(
                    "Failed to submit existing sbatch through connector\n"
                    f"STDOUT:\n{sres.get('stdout', '')}\n\n"
                    f"STDERR:\n{sres.get('stderr', '')}"
                )

            stdout = sres.get("stdout", "") or ""
            m = re.search(r"Submitted batch job\s+(\d+)", stdout)
            if not m:
                raise RuntimeError(f"Could not parse JobID from:\n{stdout}")

            jobid = m.group(1)

            messages.append("[connector] ✅ Submitted existing sbatch from example dir")
            messages.append(f"  sbatch: {remote_sbatch}")
            messages.append(f"  jobid : {jobid}")

            return RemoteSubmitResult(
                success=True,
                jobid=jobid,
                remote_dir=remote_example_dir,
                remote_example_dir=remote_example_dir,
                spack_path=spack_path,
                used_existing_sbatch=True,
                existing_sbatch_name=remote_sbatch,
                messages=messages,
            )

        messages.append("[connector] NOTE: remote_sbatch configured but not found; falling back to generated slurm_run.sh.")

    account_line, mail_lines = slurm_optional_lines(
        slurm_account.strip(),
        slurm_mail.strip(),
    )

    outfile = "icesee-enkf-%j.out"
    run_script_name = example_cfg.get("run_script")

    slurm_text = render_slurm_script(
        dict(
            TIME=slurm_time.strip(),
            JOB_NAME=slurm_job_name.strip() or "ICESEE",
            NODES=int(slurm_nodes),
            NTASKS=int(slurm_ntasks),
            TPN=int(slurm_tpn),
            PARTITION=slurm_part.strip(),
            MEM=slurm_mem.strip(),
            ACCOUNT_LINE=account_line,
            MAIL_LINES=mail_lines,
            OUTFILE=outfile,
            MODULE_LINES=sanitize_multiline(remote_module_lines),
            EXPORT_LINES=sanitize_multiline(remote_export_lines),
            SPACK_PATH=spack_path,
            NP=int(cluster_mpi_np),
            NENS=int(ens_size),
            MODEL_NPROCS=int(cluster_model_nprocs),
            RUN_SCRIPT=run_script_name,
            PARAMS_PATH=f"{rdir}/params.yaml",
            EXAMPLE_DIR=remote_example_dir,
            SRUN_MPI_FLAG="--mpi=pmix",
        )
    )

    if "{{" in slurm_text or "}}" in slurm_text:
        raise RuntimeError("SLURM_TEMPLATE render left unresolved placeholders.")

    messages.append("[connector] Writing params.yaml + slurm_run.sh, then sbatch...")

    jobid = connector_stage_and_submit(
        session_id=session_id,
        host=host,
        user=user,
        port=port,
        remote_dir=rdir,
        params_text=params_text,
        slurm_text=slurm_text,
        cluster_name=cluster_name,
    )

    messages.append("[connector] ✅ Submitted generated slurm_run.sh")
    messages.append(f"  jobid : {jobid}")
    messages.append(f"  rdir  : {rdir}")
    messages.append(f"  example dir: {remote_example_dir}")

    return RemoteSubmitResult(
        success=True,
        jobid=jobid,
        remote_dir=rdir,
        remote_example_dir=remote_example_dir,
        spack_path=spack_path,
        used_existing_sbatch=False,
        existing_sbatch_name=None,
        messages=messages,
    )


def submit_remote_example_container_via_connector(
    *,
    session_id: str,
    host: str,
    user: str,
    port: int,
    example_cfg: dict,
    params_text: str,
    remote_base_dir: str,
    remote_tag: str,
    spack_repo_url: str,
    spack_dirname: str,
    slurm_time: str,
    slurm_job_name: str,
    slurm_nodes: int,
    slurm_ntasks: int,
    slurm_tpn: int,
    slurm_part: str,
    slurm_mem: str,
    slurm_account: str,
    slurm_mail: str,
    remote_module_lines: str,
    remote_export_lines: str,
    cluster_mpi_np: int,
    ens_size: int,
    cluster_model_nprocs: int,
    container_source: str,
    container_image_uri: str,
    cluster_name: str,
) -> RemoteSubmitResult:
    messages: list[str] = []

    if not session_id:
        raise RuntimeError("Missing connector session ID.")

    if not host or not user:
        raise ValueError("Provide Host + User first.")

    remote_base_input = require_remote_base_dir(remote_base_dir)

    rbase_cmd = (
        "python3 -c "
        + sh_quote(
            f"import os; print(os.path.abspath(os.path.expanduser({remote_base_input!r})))"
        )
    )

    rbase = connector_ssh(session_id, host, user, port, rbase_cmd, timeout=60, cluster_name=cluster_name)
    if not rbase.get("ok"):
        raise RuntimeError(
            "Failed to resolve remote base dir through connector\n"
            f"STDOUT:\n{rbase.get('stdout', '')}\n\n"
            f"STDERR:\n{rbase.get('stderr', '')}"
        )

    remote_base_abs = (rbase.get("stdout") or "").strip().splitlines()[-1]
    tag = remote_tag.strip() or "icesee"

    rdir = make_remote_run_dir(remote_base_abs, tag)

    messages.append("[connector] Using local connector / VPN bridge")
    messages.append("[connector] Container backend enabled")
    messages.append(f"[connector] Remote base dir: {remote_base_abs}")
    messages.append(f"[connector] Remote run dir : {rdir}")

    spack_name = spack_dirname.strip() or "ICESEE-Spack"
    repo = spack_repo_url.strip()
    spack_path = f"{remote_base_abs.rstrip('/')}/{spack_name}"

    ensure_cmd = f"""
set -e
mkdir -p {sh_quote(remote_base_abs)}
if [ ! -d {sh_quote(spack_path)} ]; then
  echo "[spack] cloning {repo} -> {spack_path}"
  cd {sh_quote(remote_base_abs)}
  git clone {sh_quote(repo)} {sh_quote(spack_name)}
else
  echo "[spack] exists: {spack_path}"
fi
test -f {sh_quote(spack_path + '/scripts/activate.sh')}
echo {sh_quote(spack_path)}
"""

    eres = connector_ssh(session_id, host, user, port, ensure_cmd, timeout=600, cluster_name=cluster_name)
    if not eres.get("ok"):
        raise RuntimeError(
            "Failed to ensure ICESEE-Spack through connector\n"
            f"STDOUT:\n{eres.get('stdout', '')}\n\n"
            f"STDERR:\n{eres.get('stderr', '')}"
        )

    remote_rel = example_cfg.get("remote_rel")
    if not remote_rel:
        raise RuntimeError("This example has no remote_rel configured in EXAMPLES.")

    remote_example_dir = f"{spack_path.rstrip('/')}/{remote_rel.lstrip('/')}"
    messages.append(f"[connector] Remote example dir: {remote_example_dir}")

    chk = connector_ssh(
        session_id,
        host,
        user,
        port,
        f"test -d {sh_quote(remote_example_dir)} && echo OK || echo MISSING",
        timeout=30, cluster_name=cluster_name,
    )

    if not chk.get("ok") or "OK" not in (chk.get("stdout") or ""):
        raise RuntimeError(
            "Remote example directory not found through connector.\n"
            f"STDOUT:\n{chk.get('stdout', '')}\n\n"
            f"STDERR:\n{chk.get('stderr', '')}"
        )

    account_line, mail_lines = slurm_optional_lines(
        slurm_account.strip(),
        slurm_mail.strip(),
    )

    remote_root = f"{remote_base_abs.rstrip('/')}/{tag}"
    container_root = f"{remote_root}/ICESEE-Containers"
    container_dir = f"{container_root}/spack-managed/combined-container"
    sif_path = f"{container_dir}/combined-env.sif"
    def_path = f"{container_dir}/combined-env-inbuilt-matlab.def"

    run_script_name = example_cfg.get("run_script")
    outfile = f"{rdir}/icesee-enkf-%j.out"

    slurm_text = f"""#!/bin/bash
#SBATCH -t {slurm_time.strip()}
#SBATCH -J {slurm_job_name.strip() or "ICESEE"}
#SBATCH -N {int(slurm_nodes)}
#SBATCH -n {int(slurm_ntasks)}
#SBATCH --ntasks-per-node={int(slurm_tpn)}
#SBATCH -p {slurm_part.strip()}
#SBATCH --mem={slurm_mem.strip()}
{account_line}
#SBATCH -o {outfile}
{mail_lines}

set -euo pipefail
cd "${{SLURM_SUBMIT_DIR}}"

module purge || true
{sanitize_multiline(remote_module_lines)}

{sanitize_multiline(remote_export_lines)}

echo "[icesee] Host: $(hostname)"
echo "[icesee] Date: $(date)"
echo "[icesee] PWD : $(pwd)"

echo "[icesee] Checking apptainer..."
if ! command -v apptainer >/dev/null 2>&1; then
  echo "[icesee] apptainer not found in PATH. Trying module load apptainer..."
  source /etc/profile >/dev/null 2>&1 || true
  module load apptainer >/dev/null 2>&1 || true
fi

if ! command -v apptainer >/dev/null 2>&1; then
  echo "[icesee][ERROR] apptainer not found, and module load apptainer failed."
  exit 2
fi

mkdir -p "{remote_root}"

if [ ! -d "{container_root}" ]; then
  echo "[icesee] Cloning ICESEE-Containers..."
  git clone https://github.com/ICESEE-project/ICESEE-Containers.git "{container_root}"
fi

cd "{container_dir}"

if [ ! -f "{sif_path}" ]; then
  if [ ! -f "{def_path}" ]; then
    echo "[icesee][ERROR] Definition file not found: {def_path}"
    exit 2
  fi
  echo "[icesee] Building Apptainer image..."
  apptainer build combined-env.sif combined-env-inbuilt-matlab.def
else
  echo "[icesee] Using existing Apptainer image: {sif_path}"
fi

cd "{remote_example_dir}"

if command -v srun >/dev/null 2>&1; then
  /usr/bin/time -v \\
    srun --mpi=pmix -n "{int(cluster_mpi_np)}" \\
      apptainer exec \\
      -B "{remote_example_dir}:{remote_example_dir},{rdir}:{rdir}" \\
      "{sif_path}" \\
      python "{run_script_name}" \\
        -F "{rdir}/params.yaml" \\
        --Nens="{int(ens_size)}" \\
        --model_nprocs="{int(cluster_model_nprocs)}" \\
        --verbose
else
  /usr/bin/time -v \\
    apptainer exec \\
      -B "{remote_example_dir}:{remote_example_dir},{rdir}:{rdir}" \\
      "{sif_path}" \\
      python "{run_script_name}" \\
        -F "{rdir}/params.yaml" \\
        --Nens="{int(ens_size)}" \\
        --model_nprocs="{int(cluster_model_nprocs)}" \\
        --verbose
fi

echo "=== Finished ==="
"""

    messages.append("[connector] Writing params.yaml + slurm_run.sh, then sbatch...")

    jobid = connector_stage_and_submit(
        session_id=session_id,
        host=host,
        user=user,
        port=port,
        remote_dir=rdir,
        params_text=params_text,
        slurm_text=slurm_text,
        cluster_name=cluster_name,
    )

    messages.append("[connector] ✅ Submitted container-based slurm_run.sh")
    messages.append(f"  jobid : {jobid}")
    messages.append(f"  rdir  : {rdir}")
    messages.append(f"  example dir: {remote_example_dir}")
    messages.append(f"  image : {sif_path}")

    return RemoteSubmitResult(
        success=True,
        jobid=jobid,
        remote_dir=rdir,
        remote_example_dir=remote_example_dir,
        spack_path=spack_path,
        used_existing_sbatch=False,
        existing_sbatch_name=None,
        messages=messages,
    )

def connector_stage_archive(
    session_id: str,
    host: str,
    user: str,
    port: int,
    local_example_path: Path,
    remote_run_dir: str,
    timeout: int = 600,
    cluster_name: str = "pace",
):
    import base64
    import tarfile
    import tempfile
    from pathlib import Path
    from icesee_jupyter_book.core.connector_relay_client import send_command

    local_example_path = Path(local_example_path).expanduser().resolve()
    if not local_example_path.exists():
        raise RuntimeError(f"Example path does not exist: {local_example_path}")

    with tempfile.TemporaryDirectory() as td:
        archive_path = Path(td) / f"{local_example_path.name}.tar.gz"

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(local_example_path, arcname=local_example_path.name)

        archive_b64 = base64.b64encode(archive_path.read_bytes()).decode("ascii")

    res = send_command(
        session_id,
        "stage-archive",
        {
            "host": host,
            "user": user,
            "port": int(port),
            "archive_name": f"{local_example_path.name}.tar.gz",
            "archive_b64": archive_b64,
            "remote_dir": remote_run_dir,
            "timeout": int(timeout),
            "cluster_name": cluster_name,
        },
    )

    return relay_result_payload(res)

def connector_get_public_key(
    session_id: str,
    cluster_name: str = "pace",
    *,
    hpc_username: str = "",
    host: str = "",
):
    # B3: the connector namespaces the key by resource + HPC identity, so the
    # public key shown here must be requested with that same identity.
    from icesee_jupyter_book.core.connector_relay_client import send_command

    res = send_command(
        session_id,
        "get-public-key",
        {
            "cluster_name": cluster_name,
            "user": hpc_username,
            "host": host,
            "timeout": 300,
        },
    )
    return relay_result_payload(res)