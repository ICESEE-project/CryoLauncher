"""Regression: RemoteSubmitResult must accept the fields every real call site
constructs it with. A stray `require_remote_base_dir` definition had been
pasted into the middle of the dataclass body, truncating it to a single
`success` field -- every real remote-submission return statement (six call
sites in this module) passed `jobid=`, `remote_dir=`, etc. and would have
raised TypeError the first time a real SSH/Slurm submission completed.
"""
from __future__ import annotations

from icesee_jupyter_book.core.remote_runner import (
    RemoteSubmitResult,
    require_remote_base_dir,
)


def test_remote_submit_result_accepts_all_fields_every_call_site_uses():
    result = RemoteSubmitResult(
        success=True,
        jobid="12345",
        remote_dir="/scratch/user/run",
        remote_example_dir="/scratch/user/run/example",
        spack_path="/scratch/user/spack",
        used_existing_sbatch=False,
        existing_sbatch_name=None,
        messages=["ok"],
    )
    assert result.success is True
    assert result.jobid == "12345"
    assert result.remote_dir == "/scratch/user/run"
    assert result.messages == ["ok"]


def test_require_remote_base_dir_is_still_a_standalone_function():
    assert callable(require_remote_base_dir)
    assert "jobid" not in require_remote_base_dir.__code__.co_varnames
