from __future__ import annotations

import re
import shlex
import subprocess
from collections.abc import Mapping
from pathlib import Path

from icesee_jupyter_book.core.remote_runner import (
    connector_slurm_submit,
    connector_ssh,
    connector_stage_archive,
    remote_ensure_spack,
    resolve_remote_abs_path,
    sanitize_multiline,
    slurm_optional_lines,
    ssh_run,
)
import cryostack_src.remote.spack_env as spack_env
from cryostack_src.models.issm.postprocess import (
    build_postprocess as build_issm_postprocess_script,
)
from cryostack_src.models.icepack.postprocess import (
    build_collection_shell_block as build_icepack_collection_block,
)
from cryostack_src.models.icepack.export import (
    build_export_shell_block as build_icepack_export_block,
)
from cryostack_src.models.stack import (
    checkout_bind_suffix,
    checkout_setup_block,
    component_checkout_plan,
)
from cryostack_src.remote.runtime import expand_remote_home, require_remote_base_dir


def _issm_container_mpi_env() -> str:
    """``apptainer exec --env`` flags that keep ISSM's in-container ``mpiexec``
    a local, single-node launch.

    ISSM's ``generic`` cluster inside the ICESEE-Container writes its solver
    launch line as ``mpiexec -np <md.cluster.np> <ISSM_DIR>/bin/issm.exe ...``
    -- verified against both ``/opt/ISSM/bin/generic.m`` and the ICESEE
    ``issm_utils/slurm_cluster/generic.m`` in the image: neither has an
    ``srun`` branch on Linux. That ``mpiexec`` is Spack OpenMPI 5 / PRRTE 4.

    Under a multi-node ``sbatch`` the ``apptainer exec`` inherits ``SLURM_*``,
    so PRRTE's ``slurm`` PLM tries to ``srun prted`` on the other node -- but
    the SIF ships no Slurm/SSH client, so the launch dies with *"No available
    launching agents were found"* (and, once a stray ``srun`` shim was on
    ``PATH``, *"No executable was specified on the prterun command line"*).

    The SIF has no cross-node launcher, so ISSM's self-launched MPI is
    single-node by construction. Pin PRRTE to the batch node:

    * ``PRTE_MCA_ras=^slurm`` -- ignore the multi-node allocation; use only
      the node ``mpiexec`` runs on;
    * ``PRTE_MCA_plm=ssh`` -- a same-node launch is a plain fork, so no
      ``srun`` / ``ssh`` binary is ever exec'd;
    * ``PRTE_MCA_rmaps_default_mapping_policy=:oversubscribe`` -- ``md.cluster.np``
      (2 for every stock ISSM example) may exceed a small node's core count.

    True multi-node ISSM needs the ICESEE-Spack backend (real ``srun`` on the
    host) -- see the note emitted by the submit path.
    """
    return (
        "--env PRTE_MCA_ras=^slurm "
        "--env PRTE_MCA_plm=ssh "
        "--env PRTE_MCA_rmaps_default_mapping_policy=:oversubscribe "
    )


def _issm_container_single_node_note(*, backend: str, model: str, nodes) -> list[str]:
    """One advisory line when a container ISSM run asks for more than one node.

    ISSM's ``md.cluster.np`` (the example owns it) is the sole MPI rank count;
    the ``#SBATCH -N`` request does not feed it and the in-container solver
    cannot span nodes. Surfaced, not enforced -- the run still proceeds on the
    batch node.
    """
    try:
        n = int(nodes)
    except (TypeError, ValueError):
        n = 1
    if backend == "container" and model == "issm" and n > 1:
        return [
            "[remote] NOTE: container ISSM self-launches MPI on the batch node "
            f"only (md.cluster.np ranks); the requested -N {n} is not used by "
            "the solver. Use the ICESEE-Spack backend for multi-node ISSM."
        ]
    return []


_ENV_NAME_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


def _matlab_container_env(
    matlab_license: Mapping | None,
    *,
    backend: str,
    model: str,
) -> tuple[str, str]:
    """``(apptainer --env fragment, execution-log line)`` for MATLAB licensing.

    ISSM runs MATLAB inside the portable ICESEE container, which ships no
    license server. The compute-resource profile must supply one; it is passed
    explicitly with ``apptainer exec --env`` -- never via implicit
    host-environment forwarding.

    Returns ``("", "")`` for any non-ISSM or non-container run (Icepack /
    Firedrake / Spack are untouched). Raises :class:`RuntimeError` -- before any
    job is written or submitted -- when an ISSM container run has no configured
    license, so a Slurm allocation never sits idle on a checkout that will fail.

    ``matlab_license`` is runtime configuration only: the value is spliced into
    the generated command, never logged and never persisted to provenance.
    """
    if backend != "container" or model != "issm":
        return "", ""

    lic = matlab_license or {}
    env_var = str(lic.get("env_var") or "MLM_LICENSE_FILE").strip()
    value = str(lic.get("value") or "").strip()

    if not value:
        raise RuntimeError(
            "[container][ERROR] MATLAB licensing is not configured for this "
            "compute resource. Configure the compute profile's MATLAB license "
            "(e.g. MLM_LICENSE_FILE=<port>@<host>) before running ISSM in a "
            "container."
        )
    if not _ENV_NAME_RE.match(env_var):
        raise RuntimeError(
            f"[container][ERROR] invalid MATLAB license env var name: {env_var!r}"
        )

    return (
        f"--env {env_var}={shlex.quote(value)} ",
        'echo "[container] MATLAB licensing: configured"',
    )


def _assert_spack_ready(run_script, *, model: str, spack_path: str) -> None:
    """Block a scientific ICESEE-Spack run unless the live probe reports Ready.

    ``run_script(script) -> (returncode, stdout, stderr)``. Never installs here --
    a synchronous build must never hold a submission request open. The user runs
    Check / Prepare environment first.
    """
    paths = spack_env.spack_paths_from_repo(spack_path)
    rc, out, err = run_script(spack_env.probe_script(model=model, paths=paths))
    report = spack_env.classify_probe(out or "", model=model, ok=(rc == 0))
    if report.is_ready:
        return
    raise RuntimeError(
        f"ICESEE-Spack is not ready for {model.upper()} on this resource.\n"
        "Check or prepare the environment before running.\n"
        + "\n".join(report.messages)
    )


_ICESEE_CONTAINERS_REPO = "https://github.com/ICESEE-project/ICESEE-Containers.git"
_ICESEE_CONTAINERS_DEFAULT_DEF = "combined-env-inbuilt-matlab.def"
_ICESEE_CONTAINERS_DEFAULT_SIF = "combined-env.sif"


def _apptainer_preamble() -> str:
    return (
        'echo "[container] checking apptainer..."\n'
        "if ! command -v apptainer >/dev/null 2>&1; then\n"
        "    source /etc/profile >/dev/null 2>&1 || true\n"
        "    module load apptainer >/dev/null 2>&1 || true\n"
        "fi\n"
        "if ! command -v apptainer >/dev/null 2>&1; then\n"
        '    echo "[container][ERROR] apptainer not found, and module load apptainer failed."\n'
        "    exit 2\n"
        "fi"
    )


def _oci_cache_slug(image_uri: str) -> str:
    """Deterministic filesystem-safe identity for one OCI reference."""
    import hashlib
    import re

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", image_uri.strip()).strip("-")[:80] or "image"
    digest = hashlib.sha256(image_uri.strip().encode("utf-8")).hexdigest()[:12]
    return f"{cleaned}-{digest}"


def build_container_provision(
    *,
    container_source: str,
    image_uri: str,
    remote_base_abs: str,
    tag: str,
) -> tuple[str, str]:
    """Return ``(sif_path, setup_script)`` for the selected container source.

    Three portable, host-Slurm-free modes, each caching exactly one SIF per
    source/image identity and reusing it on later runs:

    * ``local``          -- ``image_uri`` is an existing SIF path on the remote.
    * ``docker`` / ``oci`` -- ``apptainer pull docker://<image_uri>`` into a
      per-image cache SIF (no image build on the HPC system).
    * ``git`` (default, also legacy ``registry``/empty) -- clone/update
      ICESEE-Containers and build the selected ``.def`` only when the cached
      SIF is absent or older than the definition.
    """
    source = (container_source or "").strip().lower() or "git"
    image_uri = (image_uri or "").strip()
    root = f"{remote_base_abs.rstrip('/')}/{tag}/ICESEE-Containers"
    preamble = _apptainer_preamble()

    if source == "local":
        sif_path = image_uri
        setup = (
            f"{preamble}\n"
            'echo "[container] source: local"\n'
            f'sif_path="{sif_path}"\n'
            'if [ ! -f "$sif_path" ]; then\n'
            '    echo "[container][ERROR] local image not found: $sif_path"\n'
            "    exit 2\n"
            "fi\n"
            'echo "[container] using cached image $sif_path"'
        )
        return sif_path, setup

    if source in {"docker", "oci"}:
        cache_dir = f"{root}/oci-cache"
        sif_path = f"{cache_dir}/{_oci_cache_slug(image_uri)}.sif"
        ref = image_uri if "://" in image_uri else f"docker://{image_uri}"
        setup = (
            f"{preamble}\n"
            'echo "[container] source: docker"\n'
            f'mkdir -p "{cache_dir}"\n'
            f'sif_path="{sif_path}"\n'
            'if [ -f "$sif_path" ]; then\n'
            '    echo "[container] using cached image $sif_path"\n'
            "else\n"
            f'    echo "[container] pulling image {ref} ..."\n'
            f'    if ! apptainer pull "$sif_path" "{ref}"; then\n'
            '        rm -f "$sif_path"\n'
            "        exit 2\n"
            "    fi\n"
            '    echo "[container] using cached image $sif_path"\n'
            "fi"
        )
        return sif_path, setup

    # default: git -- ICESEE-Containers checkout + apptainer build
    def_name = image_uri if image_uri.endswith(".def") else _ICESEE_CONTAINERS_DEFAULT_DEF
    sif_name = (
        _ICESEE_CONTAINERS_DEFAULT_SIF
        if def_name == _ICESEE_CONTAINERS_DEFAULT_DEF
        else f"{def_name[:-4]}.sif"
    )
    build_dir = f"{root}/spack-managed/combined-container"
    sif_path = f"{build_dir}/{sif_name}"
    setup = (
        f"{preamble}\n"
        'echo "[container] source: git"\n'
        f'mkdir -p "{remote_base_abs.rstrip("/")}/{tag}"\n'
        f'if [ ! -d "{root}/.git" ]; then\n'
        '    echo "[container] cloning ICESEE-Containers ..."\n'
        f'    rm -rf "{root}"\n'
        f'    git clone {_ICESEE_CONTAINERS_REPO} "{root}"\n'
        "else\n"
        '    echo "[container] updating ICESEE-Containers ..."\n'
        f'    git -C "{root}" pull --ff-only || true\n'
        "fi\n"
        f'cd "{build_dir}"\n'
        f'def_path="{build_dir}/{def_name}"\n'
        f'sif_path="{sif_path}"\n'
        'if [ ! -f "$def_path" ]; then\n'
        '    echo "[container][ERROR] definition file not found: $def_path"\n'
        "    exit 2\n"
        "fi\n"
        'if [ ! -f "$sif_path" ] || [ "$def_path" -nt "$sif_path" ]; then\n'
        f'    echo "[container] building {sif_name} from {def_name} ..."\n'
        '    if ! apptainer build "$sif_path" "$def_path"; then\n'
        '        rm -f "$sif_path"\n'
        "        exit 2\n"
        "    fi\n"
        "else\n"
        '    echo "[container] using cached image $sif_path"\n'
        "fi"
    )
    return sif_path, setup


def submit_remote_icesheets_via_connector(
    *,
    session_id: str,
    host: str,
    user: str,
    port: int,
    remote_base_dir: str,
    remote_tag: str,
    backend: str,
    model: str,
    example_dir: str,
    exec_dir: str,
    image_uri: str,
    container_source: str,
    spack_enable: bool,
    spack_repo_url: str,
    spack_dirname: str,
    spack_install_if_needed: bool,
    spack_install_mode: str,
    spack_slurm_dir: str,
    spack_pmix_dir: str,
    slurm_time: str,
    slurm_job_name: str,
    slurm_nodes: int,
    slurm_ntasks: int,
    slurm_tpn: int,
    slurm_part: str,
    slurm_mem: str,
    slurm_account: str,
    slurm_mail: str,
    remote_module_lines: str = "",
    remote_export_lines: str = "",
    test_mode: bool = False,
    run_file: str = "",
    cluster_name: str = "pace",
    stack_log_line: str = "",
    stack_software: dict | None = None,
    matlab_license: Mapping | None = None,
):
    import base64
    import shlex

    messages = []

    if not session_id:
        raise RuntimeError("Missing connector session ID.")

    if not host or not user:
        raise ValueError("Provide Host + User first.")

    # Preflight: an ISSM container run needs a MATLAB license from the compute
    # profile. Fail here, before any staging or submission.
    matlab_env_flag, matlab_log_line = _matlab_container_env(
        matlab_license, backend=backend, model=model
    )

    # Resolve remote base through connector.
    remote_base_input = require_remote_base_dir(remote_base_dir)

    resolve_cmd = f'python3 -c "import os; print(os.path.abspath(os.path.expanduser({remote_base_input!r})))"'
    rbase = connector_ssh(session_id, host, user, port, resolve_cmd, timeout=300, cluster_name=cluster_name)
    if not rbase.get("ok"):
        raise RuntimeError(f"Failed to resolve remote base dir:\n{rbase.get('stderr', '')}")

    remote_base_abs = (rbase.get("stdout") or "").strip().splitlines()[-1]
    tag = (remote_tag or "").strip() or "icesheets"

    remote_run_dir = f"{remote_base_abs.rstrip('/')}/{tag}/runs/{model}_{backend}"
    remote_submit_script = f"{remote_run_dir}/run_icesheets.sbatch"

    messages.append("[connector] Using local connector / VPN bridge")
    messages.append(f"[connector] Remote base dir : {remote_base_abs}")
    messages.append(f"[connector] Remote run dir  : {remote_run_dir}")

    account_line, mail_lines = slurm_optional_lines(
        slurm_account.strip(),
        slurm_mail.strip(),
    )

    run_file_name = Path(run_file).name if run_file else ""
    run_file_py = Path(run_file_name).with_suffix(".py").name if run_file_name else ""

    local_example_path = Path(example_dir).expanduser()
    if not local_example_path.exists():
        raise RuntimeError(f"Local example path does not exist: {local_example_path}")

    local_parent = str(local_example_path.resolve().parent)
    local_name = local_example_path.resolve().name

    # Clean and create remote run dir.
    clean_cmd = f'''
rm -rf "{remote_run_dir}"
mkdir -p "{remote_run_dir}"
'''
    cres = connector_ssh(session_id, host, user, port, clean_cmd, timeout=300, cluster_name=cluster_name)
    if not cres.get("ok"):
        raise RuntimeError(f"Failed to prepare remote run dir:\n{cres.get('stderr', '')}")

    # Upload example using connector-side rsync.
    local_upload_path = f"{local_parent}/{local_name}"
    up = connector_stage_archive(
        session_id,
        host,
        user,
        port,
        local_example_path,
        remote_run_dir,
        timeout=600,
    )

    if not up.get("ok"):
        raise RuntimeError(
            "Failed to copy local example to remote host through connector\n"
            f"FULL RESPONSE:\n{up}\n\n"
            f"STDOUT:\n{up.get('stdout','')}\n\n"
            f"STDERR:\n{up.get('stderr','')}"
        )

    remote_example_dir = f"{remote_run_dir}/{local_name}"
    remote_exec_dir = f"{remote_run_dir}/execution"

    messages.append(f"[connector] staged example dir: {remote_example_dir}")
    messages.append(f"[connector] staged exec dir   : {remote_exec_dir}")

    # Backend setup.
    spack_path = None

    if backend == "spack":
        if not spack_enable:
            raise RuntimeError("ICESEE-Spack backend requires spack_enable=True")

        spack_parent = remote_base_abs
        spack_name = spack_dirname.strip() or "ICESEE-Spack"
        repo = spack_repo_url.strip()
        spack_path = f"{spack_parent.rstrip('/')}/{spack_name}"

        ensure_cmd = f'''
set -e
mkdir -p "{spack_parent}"
if [ ! -d "{spack_path}" ]; then
    git clone "{repo}" "{spack_path}"
fi
test -f "{spack_path}/scripts/activate.sh"
echo "{spack_path}"
'''
        eres = connector_ssh(session_id, host, user, port, ensure_cmd, timeout=600, cluster_name=cluster_name)
        if not eres.get("ok"):
            raise RuntimeError(
                "Failed to ensure ICESEE-Spack on remote host through connector\n"
                f"STDOUT:\n{eres.get('stdout','')}\n\nSTDERR:\n{eres.get('stderr','')}"
            )

        messages.append("[connector] Spack backend enabled")
        messages.append(f"[connector] ICESEE-Spack path: {spack_path}")

        # A scientific run must not start unless the live environment is Ready.
        # Building the environment is a durable Slurm setup job (Prepare
        # environment), never a synchronous install here.
        def _probe(script, _sid=session_id):
            r = connector_ssh(_sid, host, user, port, script, timeout=180,
                              cluster_name=cluster_name)
            return (0 if r.get("ok") else 1, r.get("stdout", ""), r.get("stderr", ""))

        _assert_spack_ready(_probe, model=model, spack_path=spack_path)
        messages.append(f"[connector] ICESEE-Spack ready for {model.upper()}")

    elif backend == "container":
        messages.append("[connector] ICESEE-Container backend selected")
        messages += _issm_container_single_node_note(
            backend=backend, model=model, nodes=slurm_nodes
        )
    else:
        raise RuntimeError(f"Unsupported backend: {backend}")

    # Write ISSM postprocess if needed.
    if model == "issm":
        postprocess_path = f"{remote_run_dir}/postprocess_icesee.m"
        postprocess_text = build_issm_postprocess_script()
        encoded_post = base64.b64encode(postprocess_text.encode("utf-8")).decode("ascii")

        write_post_cmd = (
            "python3 -c "
            + shlex.quote(
                "import base64, pathlib; "
                f"p = pathlib.Path({postprocess_path!r}); "
                "p.parent.mkdir(parents=True, exist_ok=True); "
                f"p.write_text(base64.b64decode({encoded_post!r}).decode('utf-8'), encoding='utf-8'); "
                "print(str(p))"
            )
        )

        pres = connector_ssh(session_id, host, user, port, write_post_cmd, timeout=60, cluster_name=cluster_name)
        if not pres.get("ok"):
            raise RuntimeError(
                "Failed to write ISSM postprocess script through connector\n"
                f"STDOUT:\n{pres.get('stdout','')}\n\nSTDERR:\n{pres.get('stderr','')}"
            )

        messages.append(f"[connector] wrote postprocess script: {postprocess_path}")

    # Build run block.
    if backend == "spack":
        issm_matlab_setup = (
            "addpath([getenv('ISSM_DIR') '/bin'], [getenv('ISSM_DIR') '/lib']); "
            "issmversion; "
        )

        if test_mode:
            if model == "issm":
                run_block = f'''
cd "{remote_example_dir}"
matlab -nodesktop -nosplash -r "{issm_matlab_setup}; exit"
'''
            elif model == "icepack":
                run_block = f'''
cd "{remote_example_dir}"
python -c "import icepack; print('Icepack import successful')"
'''
            else:
                raise RuntimeError(f"Unsupported model: {model}")
        else:
            if model == "issm":
                target_m = run_file_name if run_file_name.endswith(".m") else "runme.m"
                run_block = f'''
cd "{remote_example_dir}"
matlab -nodesktop -nosplash -r "{issm_matlab_setup} ICESEE_RUN_DIR='{remote_run_dir}'; setenv('ICESEE_RUN_DIR','{remote_run_dir}'); run('{target_m}'); run('../postprocess_icesee.m'); exit"
'''
            elif model == "icepack":
                if run_file_name.endswith((".py", ".ipynb")):
                    # Icepack science + headless figure capture + structured
                    # export are ONE step -- build_icepack_export_block(
                    # primary=True) appended below. Same contract as Cloud.
                    run_block = f'''
cd "{remote_example_dir}"
'''
                else:
                    run_block = f'''
cd "{remote_example_dir}"
python -c "import icepack; print('Icepack import successful')"
'''
            else:
                raise RuntimeError(f"Unsupported model: {model}")

        body = f'''
cd "{spack_path}"
source "{spack_path}/scripts/activate.sh"

{run_block}
'''

    else:
        sif_path, container_setup = build_container_provision(
            container_source=container_source,
            image_uri=image_uri,
            remote_base_abs=remote_base_abs,
            tag=tag,
        )
        # run-local source overrides (empty for the tested profile)
        _stack_plan = component_checkout_plan(stack_software, remote_run_dir)
        _stack_setup = checkout_setup_block(_stack_plan)
        _stack_binds = checkout_bind_suffix(_stack_plan)
        if model == "issm":
            target_m = run_file_name if run_file_name.endswith(".m") else "runme.m"
            run_block = f'''
mkdir -p "{remote_exec_dir}"
{_stack_setup}
{matlab_log_line}
apptainer exec {matlab_env_flag}{_issm_container_mpi_env()}\
-B "{remote_example_dir}":/opt/ISSM/examples,"{remote_exec_dir}":/opt/ISSM/execution,"{remote_run_dir}":"{remote_run_dir}"{_stack_binds} \
"{sif_path}" with-issm matlab -nodesktop -nosplash -r "cd('/opt/ISSM/examples'); ICESEE_RUN_DIR='{remote_run_dir}'; setenv('ICESEE_RUN_DIR','{remote_run_dir}'); run('{target_m}'); run('{remote_run_dir}/postprocess_icesee.m'); exit"
'''
        else:
            if run_file_name.endswith((".py", ".ipynb")):
                # Icepack science + capture + export = ONE step, shared with
                # Cloud -- build_icepack_export_block(primary=True) below.
                run_block = f'''
mkdir -p "{remote_exec_dir}"
{_stack_setup}
'''
            else:
                run_block = f'''
apptainer exec "{sif_path}" with-icepack python -c "import icepack; print('Icepack import successful')"
'''
        body = container_setup + "\n" + run_block

    # Icepack has no MATLAB neutral-export. Two appended, non-fatal steps:
    #  1. a container-side Firedrake exporter -> structured outputs/ package
    #     (cryostack.icepack.results: mesh + CG1 nodal fields);
    #  2. a stdlib collector that folds in any figures / native files and never
    #     clobbers the exporter's richer metadata.
    if model == "icepack" and not test_mode:
        body = body + "\n" + build_icepack_export_block(
            run_dir=remote_run_dir, example_dir=remote_example_dir, backend=backend,
            sif_path=locals().get("sif_path", ""),
            spack_path=locals().get("spack_path", ""),
            stack_binds=locals().get("_stack_binds", ""),
            run_file_name=run_file_name, run_file_py=run_file_py,
            primary=True,
        )
        body = body + "\n" + build_icepack_collection_block(
            run_dir=remote_run_dir, example_dir=remote_example_dir,
        )

    outfile = f"{remote_run_dir}/icesheets-%j.out"

    # one immutable, human-readable execution record of the resolved stack;
    # the structured provenance lives in the run manifest.
    _stack_echo = f"echo {shlex.quote(stack_log_line)}" if stack_log_line else ""

    slurm_text = f"""#!/bin/bash
#SBATCH -J {slurm_job_name.strip() or "ICESHEETS"}
#SBATCH -t {slurm_time.strip()}
#SBATCH -N {int(slurm_nodes)}
#SBATCH --ntasks={int(slurm_ntasks)}
#SBATCH --ntasks-per-node={int(slurm_tpn)}
#SBATCH -p {slurm_part.strip()}
#SBATCH --mem={slurm_mem.strip()}
{account_line}
{mail_lines}
#SBATCH -o {outfile}

set -euo pipefail

cd "{remote_run_dir}"
mkdir -p outputs/model outputs/figures
export CRYOSTACK_RUN_STARTED="$(date +%s)"

echo "[icesheets] Host: $(hostname)"
echo "[icesheets] Date: $(date)"
echo "[icesheets] PWD : $(pwd)"
echo "[icesheets] Run dir: {remote_run_dir}"
{_stack_echo}

{sanitize_multiline(remote_module_lines)}
{sanitize_multiline(remote_export_lines)}

{body}
"""

    encoded = base64.b64encode(slurm_text.encode("utf-8")).decode("ascii")

    write_cmd = (
        "python3 -c "
        + shlex.quote(
            "import base64, pathlib; "
            f"p = pathlib.Path({remote_submit_script!r}); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            f"p.write_text(base64.b64decode({encoded!r}).decode('utf-8'), encoding='utf-8'); "
            "print(str(p))"
        )
    )

    wres = connector_ssh(session_id, host, user, port, write_cmd, timeout=60, cluster_name=cluster_name)
    if not wres.get("ok"):
        raise RuntimeError(
            "Failed to write remote sbatch script through connector\n"
            f"STDOUT:\n{wres.get('stdout','')}\n\nSTDERR:\n{wres.get('stderr','')}"
        )

    messages.append(f"[connector] wrote script: {remote_submit_script}")

    sres = connector_slurm_submit(
        session_id,
        host,
        user,
        port,
        remote_submit_script,
        timeout=60,
    )

    if not sres.get("ok") or not sres.get("submitted"):
        raise RuntimeError(
            "Failed to submit remote sbatch script through connector\n"
            f"STDOUT:\n{sres.get('stdout','')}\n\nSTDERR:\n{sres.get('stderr','')}"
        )

    jobid = sres["jobid"]

    messages.append("[connector] ✅ Submitted model-only slurm_run.sh")
    messages.append(f"  jobid : {jobid}")
    messages.append(f"  rdir  : {remote_run_dir}")

    return {
        "success": True,
        "jobid": jobid,
        "remote_dir": remote_run_dir,
        "log_file": f"{remote_run_dir}/icesheets-{jobid}.out",
        "spack_path": spack_path,
        "messages": messages,
    }

def submit_remote_icesheets(
    *,
    host: str,
    user: str,
    port: int,
    remote_base_dir: str,
    remote_tag: str,
    backend: str,
    model: str,
    example_dir: str,
    exec_dir: str,
    image_uri: str,
    container_source: str,
    spack_enable: bool,
    spack_repo_url: str,
    spack_dirname: str,
    spack_install_if_needed: bool,
    spack_install_mode: str,
    spack_slurm_dir: str,
    spack_pmix_dir: str,
    slurm_time: str,
    slurm_job_name: str,
    slurm_nodes: int,
    slurm_ntasks: int,
    slurm_tpn: int,
    slurm_part: str,
    slurm_mem: str,
    slurm_account: str,
    slurm_mail: str,
    remote_module_lines: str = "",
    remote_export_lines: str = "",
    test_mode: bool = False,
    run_file: str = "",
    stack_log_line: str = "",
    stack_software: dict | None = None,
    matlab_license: Mapping | None = None,
):
    import base64
    import shlex
    import time

    messages: list[str] = []

    if not host or not user:
        raise ValueError("Provide Host + User first.")

    # Preflight: an ISSM container run needs a MATLAB license from the compute
    # profile. Fail here, before any staging or submission.
    matlab_env_flag, matlab_log_line = _matlab_container_env(
        matlab_license, backend=backend, model=model
    )

    # ---------------------------------------------------------
    # Remote base/run paths
    # ---------------------------------------------------------
    remote_base_input = require_remote_base_dir(remote_base_dir)
    remote_base_shell = expand_remote_home(remote_base_input)
    remote_base_abs = resolve_remote_abs_path(host, user, port, remote_base_shell)

    tag = (remote_tag or "").strip() or "icesheets"
    # ts = time.strftime("%Y%m%d-%H%M%S")
    # remote_run_dir = f"{remote_base_abs.rstrip('/')}/{tag}-{ts}"
    
    remote_run_dir = f"{remote_base_abs.rstrip('/')}/{tag}/runs/{model}_{backend}"
    remote_submit_script = f"{remote_run_dir}/run_icesheets.sbatch"

    messages.append(f"[remote] Remote base dir : {remote_base_abs}")
    messages.append(f"[remote] Remote run dir  : {remote_run_dir}")

    account_line, mail_lines = slurm_optional_lines(
        slurm_account.strip(),
        slurm_mail.strip(),
    )

    spack_path = None
    run_file_name = Path(run_file).name if run_file else ""
    run_file_py = Path(run_file_name).with_suffix(".py").name if run_file_name else ""

    local_example_dir = str(Path(example_dir).expanduser())
    local_exec_dir = str(Path(exec_dir).expanduser())

    messages.append(f"[remote] example_dir input : {local_example_dir}")
    messages.append(f"[remote] exec_dir input    : {local_exec_dir}")
    messages.append(f"[remote] run_file input    : {run_file or '(none)'}")
    messages.append(f"[remote] test_mode         : {test_mode}")

    # ---------------------------------------------------------
    # Backend setup
    # ---------------------------------------------------------
    if backend == "spack":
        if not spack_enable:
            raise RuntimeError("ICESEE-Spack backend requires spack_enable=True")

        spack_parent = remote_base_abs
        spack_name = spack_dirname.strip() or "ICESEE-Spack"
        repo = spack_repo_url.strip()

        messages.append("[remote] Spack backend enabled")
        messages.append(f"  parent: {spack_parent}")
        messages.append(f"  repo  : {repo}")
        messages.append(f"  name  : {spack_name}")

        spack_path_raw, (rc, out, err) = remote_ensure_spack(
            host, user, port, spack_parent, spack_name, repo
        )
        if out.strip():
            messages.append(out.strip())
        if err.strip():
            messages.append(err.strip())
        if rc != 0:
            raise RuntimeError("Failed to ensure ICESEE-Spack on remote host.")

        spack_path = resolve_remote_abs_path(host, user, port, spack_path_raw)
        messages.append(f"[remote] Resolved ICESEE-Spack path: {spack_path}")

        # A scientific run must not start unless the live environment is Ready.
        # Building the environment is a durable Slurm setup job (Prepare
        # environment), never a synchronous install here.
        def _probe(script):
            r = ssh_run(host, user, port, script, timeout=180)
            return (r.returncode, r.stdout, r.stderr)

        _assert_spack_ready(_probe, model=model, spack_path=spack_path)
        messages.append(f"[remote] ICESEE-Spack ready for {model.upper()}")

    elif backend == "container":
        messages.append("[remote] ICESEE-Container backend selected")
        messages.append("[remote] Container setup will be handled inside the submitted Slurm job.")
        messages += _issm_container_single_node_note(
            backend=backend, model=model, nodes=slurm_nodes
        )
    else:
        raise RuntimeError(f"Unsupported backend: {backend}")
    
    clean_cmd = f'''
    rm -rf "{remote_run_dir}"
    mkdir -p "{remote_run_dir}"
    '''
    mkres = ssh_run(host, user, port, clean_cmd, timeout=300)

    # ---------------------------------------------------------
    # Stage local example to remote run dir
    # ---------------------------------------------------------
    local_example_path = Path(local_example_dir)
    if not local_example_path.exists():
        raise RuntimeError(f"Local example path does not exist: {local_example_path}")

    mkres = ssh_run(host, user, port, f'mkdir -p "{remote_run_dir}"', timeout=300)
    if mkres.returncode != 0:
        raise RuntimeError(f"Failed to create remote run dir:\n{mkres.stderr}")

    local_parent = str(local_example_path.resolve().parent)
    local_name = local_example_path.resolve().name

    rsync_cmd = [
        "rsync",
        "-az",
        "-e",
        f"ssh -p {port}",
        f"{local_parent}/{local_name}",
        f"{user}@{host}:{remote_run_dir}/",
    ]
    rs = subprocess.run(rsync_cmd, capture_output=True, text=True)
    if rs.returncode != 0:
        raise RuntimeError(
            "Failed to copy local example to remote host\n"
            f"STDOUT:\n{rs.stdout}\n\nSTDERR:\n{rs.stderr}"
        )

    remote_example_dir = f"{remote_run_dir}/{local_name}"
    remote_exec_dir = f"{remote_run_dir}/execution"

    messages.append(f"[remote] staged example dir: {remote_example_dir}")
    messages.append(f"[remote] staged exec dir   : {remote_exec_dir}")

    if model == "issm":
        import base64
        import shlex

        postprocess_path = f"{remote_run_dir}/postprocess_icesee.m"
        postprocess_text = build_issm_postprocess_script()
        encoded_post = base64.b64encode(postprocess_text.encode("utf-8")).decode("ascii")

        write_post_cmd = (
            "python3 -c "
            + shlex.quote(
                "import base64, pathlib; "
                f"p = pathlib.Path({postprocess_path!r}); "
                "p.parent.mkdir(parents=True, exist_ok=True); "
                f"p.write_text(base64.b64decode({encoded_post!r}).decode('utf-8'), encoding='utf-8'); "
                "print(str(p))"
            )
        )

        pres = ssh_run(host, user, port, write_post_cmd, timeout=60)
        if pres.returncode != 0:
            raise RuntimeError(
                "Failed to write ISSM postprocess script\n"
                f"STDOUT:\n{pres.stdout}\n\nSTDERR:\n{pres.stderr}"
            )

        messages.append(f"[remote] wrote postprocess script: {postprocess_path}")

    # ---------------------------------------------------------
    # Build model-specific run block
    # ---------------------------------------------------------
    if backend == "spack":
        issm_matlab_setup = (
            "addpath([getenv('ISSM_DIR') '/bin'], [getenv('ISSM_DIR') '/lib']); "
            "issmversion; "
        )
        if test_mode:
            if model == "issm":
                run_block = f'''
cd "{remote_example_dir}"
matlab -nodesktop -nosplash -r "{issm_matlab_setup}; exit"
'''
            elif model == "icepack":
                run_block = f'''
cd "{remote_example_dir}"
python -c "import icepack; print('Icepack import successful')"
'''
            else:
                raise RuntimeError(f"Unsupported model: {model}")
        else:
            if model == "issm":
                target_m = run_file_name if run_file_name.endswith(".m") else "runme.m"
                run_block = f'''
cd "{remote_example_dir}"
matlab -nodesktop -nosplash -r "{issm_matlab_setup} ICESEE_RUN_DIR='{remote_run_dir}'; setenv('ICESEE_RUN_DIR','{remote_run_dir}'); run('{target_m}'); run('../postprocess_icesee.m'); exit"
'''
            elif model == "icepack":
                if run_file_name.endswith((".py", ".ipynb")):
                    # Icepack science + headless figure capture + structured
                    # export are ONE step -- build_icepack_export_block(
                    # primary=True) appended below. Same contract as Cloud.
                    run_block = f'''
cd "{remote_example_dir}"
'''
                else:
                    run_block = f'''
cd "{remote_example_dir}"
python -c "import icepack; print('Icepack import successful')"
'''
            else:
                raise RuntimeError(f"Unsupported model: {model}")

        activation_block = f'''
cd "{spack_path}"
source "{spack_path}/scripts/activate.sh"
'''
        body = activation_block + "\n" + run_block

    else:
        sif_path, container_setup = build_container_provision(
            container_source=container_source,
            image_uri=image_uri,
            remote_base_abs=remote_base_abs,
            tag=tag,
        )
        # run-local source overrides (empty for the tested profile / test_mode)
        _stack_plan = component_checkout_plan(stack_software, remote_run_dir) if not test_mode else []
        _stack_setup = checkout_setup_block(_stack_plan)
        _stack_binds = checkout_bind_suffix(_stack_plan)

        if test_mode:
            if model == "issm":
                run_block = f'''
mkdir -p "{remote_exec_dir}"
{matlab_log_line}
apptainer exec {matlab_env_flag}\
-B "{remote_example_dir}":/opt/ISSM/examples,"{remote_exec_dir}":/opt/ISSM/execution \
"{sif_path}" with-issm matlab -nodesktop -nosplash -r "issmversion; exit"
'''
            elif model == "icepack":
                run_block = f'''
mkdir -p "{remote_exec_dir}"
apptainer exec \
-B "{remote_example_dir}":/workspace/example,"{remote_exec_dir}":/workspace/run \
"{sif_path}" with-icepack python -c "import icepack; print('Icepack import successful')"
'''
            else:
                raise RuntimeError(f"Unsupported model: {model}")
        else:
            if model == "issm":
                target_m = run_file_name if run_file_name.endswith(".m") else "runme.m"
                run_block = f'''
mkdir -p "{remote_exec_dir}"
{_stack_setup}
{matlab_log_line}
apptainer exec {matlab_env_flag}{_issm_container_mpi_env()}\
-B "{remote_example_dir}":/opt/ISSM/examples,"{remote_exec_dir}":/opt/ISSM/execution,"{remote_run_dir}":"{remote_run_dir}"{_stack_binds} \
"{sif_path}" with-issm matlab -nodesktop -nosplash -r "cd('/opt/ISSM/examples'); ICESEE_RUN_DIR='{remote_run_dir}'; setenv('ICESEE_RUN_DIR','{remote_run_dir}'); run('{target_m}'); run('{remote_run_dir}/postprocess_icesee.m'); exit"
'''
            elif model == "icepack":
                if run_file_name.endswith((".py", ".ipynb")):
                    # Icepack science + capture + export = ONE step, shared
                    # with Cloud -- build_icepack_export_block(primary=True).
                    run_block = f'''
mkdir -p "{remote_exec_dir}"
{_stack_setup}
'''
                else:
                    run_block = f'''
mkdir -p "{remote_exec_dir}"
apptainer exec "{sif_path}" with-icepack python -c "import icepack; print('Icepack import successful')"
'''
            else:
                raise RuntimeError(f"Unsupported model: {model}")

        body = container_setup + "\n" + run_block

    # Icepack has no MATLAB neutral-export. Two appended, non-fatal steps:
    #  1. a container-side Firedrake exporter -> structured outputs/ package
    #     (cryostack.icepack.results: mesh + CG1 nodal fields);
    #  2. a stdlib collector that folds in any figures / native files and never
    #     clobbers the exporter's richer metadata.
    if model == "icepack" and not test_mode:
        body = body + "\n" + build_icepack_export_block(
            run_dir=remote_run_dir, example_dir=remote_example_dir, backend=backend,
            sif_path=locals().get("sif_path", ""),
            spack_path=locals().get("spack_path", ""),
            stack_binds=locals().get("_stack_binds", ""),
            run_file_name=run_file_name, run_file_py=run_file_py,
            primary=True,
        )
        body = body + "\n" + build_icepack_collection_block(
            run_dir=remote_run_dir, example_dir=remote_example_dir,
        )

    # ---------------------------------------------------------
    # Render sbatch
    # ---------------------------------------------------------
    outfile = f"{remote_run_dir}/icesheets-%j.out"

    # one immutable, human-readable execution record of the resolved stack;
    # the structured provenance lives in the run manifest.
    _stack_echo = f"echo {shlex.quote(stack_log_line)}" if stack_log_line else ""

    slurm_text = f"""#!/bin/bash
#SBATCH -J {slurm_job_name.strip() or "ICESHEETS"}
#SBATCH -t {slurm_time.strip()}
#SBATCH -N {int(slurm_nodes)}
#SBATCH --ntasks={int(slurm_ntasks)}
#SBATCH --ntasks-per-node={int(slurm_tpn)}
#SBATCH -p {slurm_part.strip()}
#SBATCH --mem={slurm_mem.strip()}
{account_line}
{mail_lines}
#SBATCH -o {outfile}

set -euo pipefail

cd "{remote_run_dir}"
mkdir -p outputs/model outputs/figures  # create expected output dirs
export CRYOSTACK_RUN_STARTED="$(date +%s)"

echo "[icesheets] Host: $(hostname)"
echo "[icesheets] Date: $(date)"
echo "[icesheets] PWD : $(pwd)"
echo "[icesheets] Run dir: {remote_run_dir}"
{_stack_echo}

{sanitize_multiline(remote_module_lines)}
{sanitize_multiline(remote_export_lines)}

{body}
"""

    messages.append("[remote] Writing slurm_run.sh, then sbatch...")

    import shlex
    encoded = base64.b64encode(slurm_text.encode("utf-8")).decode("ascii")

    remote_submit_script_q = shlex.quote(remote_submit_script)
    remote_run_dir_q = shlex.quote(remote_run_dir)
    encoded_q = shlex.quote(encoded)

    # Write the sbatch file using python -c instead of heredoc
    write_cmd = (
        "python3 -c "
        + shlex.quote(
            "import base64, pathlib; "
            f"p = pathlib.Path({remote_submit_script!r}); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            f"p.write_text(base64.b64decode({encoded!r}).decode('utf-8'), encoding='utf-8'); "
            "print(str(p))"
        )
    )

    wres = ssh_run(host, user, port, write_cmd, timeout=60)
    if wres.returncode != 0:
        raise RuntimeError(
            "Failed to write remote sbatch script\n"
            f"STDOUT:\n{wres.stdout}\n\nSTDERR:\n{wres.stderr}"
        )
    if (wres.stdout or "").strip():
        messages.append(f"[remote] wrote script: {(wres.stdout or '').strip()}")

    verify_cmd = (
        f'test -f {remote_submit_script_q} && '
        f'echo FOUND && ls -lah {remote_submit_script_q} || '
        f'(echo MISSING && ls -lah {remote_run_dir_q} && exit 1)'
    )

    vres = ssh_run(host, user, port, verify_cmd, timeout=60)
    if vres.returncode != 0:
        raise RuntimeError(
            "Remote submit script was not found after write step\n"
            f"STDOUT:\n{vres.stdout}\n\nSTDERR:\n{vres.stderr}"
        )
    if (vres.stdout or "").strip():
        messages.append((vres.stdout or "").strip())

    submit_cmd = f"sbatch {remote_submit_script_q}"
    sres = ssh_run(host, user, port, submit_cmd, timeout=60)
    if sres.returncode != 0:
        raise RuntimeError(
            "Failed to submit remote sbatch script\n"
            f"STDOUT:\n{sres.stdout}\n\nSTDERR:\n{sres.stderr}"
        )

    stdout = (sres.stdout or "").strip()
    stderr = (sres.stderr or "").strip()

    if stdout:
        messages.append(stdout)
    if stderr:
        messages.append(stderr)

    jobid = None
    for line in stdout.splitlines():
        line = line.strip()
        if "Submitted batch job" in line:
            jobid = line.split()[-1]
            break

    if not jobid:
        raise RuntimeError(f"Could not parse job ID from sbatch output:\n{stdout}")

    messages.append("[remote] ✅ Submitted model-only slurm_run.sh")
    messages.append(f"  jobid : {jobid}")
    messages.append(f"  rdir  : {remote_run_dir}")

    return {
        "success": True,
        "jobid": jobid,
        "remote_dir": remote_run_dir,
        "log_file": f"{remote_run_dir}/icesheets-{jobid}.out" if jobid else None,
        "spack_path": spack_path,
        "messages": messages,
    }
