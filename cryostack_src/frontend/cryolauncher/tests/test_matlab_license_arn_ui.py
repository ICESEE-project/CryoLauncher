"""ISSM cloud MATLAB license: the (non-secret) Secrets Manager ARN field in
Cloud Environment -> Advanced cloud settings.

Backend (cryostack_src/cloud/matlab_license.py, AWSConnection.
matlab_license_secret_arn / with_matlab_license_secret) already existed and
is unit-tested in cryostack_src/cloud/tests/test_cloud_matlab_license.py.
What was missing was: (1) a UI field to actually set the ARN, and (2) wiring
it to save onto the user's AWSConnection record -- both UI-only /
local-filesystem-only, no real AWS contact, no Secrets Manager permissions.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import ipywidgets as W

from cryostack_src.cloud.connect.models import AWSConnection
from cryostack_src.cloud.connect.store import AWSConnectionStore
from cryostack_src.frontend.cryolauncher.cloud_environment import (
    build_cloud_environment_card,
)
from cryostack_src.workspace.identity import WorkspaceUser

_GW = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"


def test_cloud_environment_card_exposes_the_license_arn_field_and_save_button():
    card = build_cloud_environment_card()
    assert isinstance(card.matlab_license_arn, W.Text)
    assert isinstance(card.matlab_license_save_button, W.Button)
    assert card.matlab_license_arn.value == ""
    # the field never renders inline in the primary view -- it lives inside
    # Advanced cloud settings alongside queue/job-definition/etc.
    assert card.matlab_license_arn in card.advanced.children[0].children


def test_cloud_environment_card_prefills_an_existing_arn():
    arn = "arn:aws:secretsmanager:us-east-2:774888247882:secret:issm-license-abc123"
    card = build_cloud_environment_card(matlab_license_secret_arn=arn)
    assert card.matlab_license_arn.value == arn


def test_gateway_saves_the_arn_onto_the_connection_never_a_license_value(tmp_path):
    """End-to-end through the real gateway closures: build the page, set the
    field, click Save, and confirm the store now holds ONLY the ARN --
    exactly the non-secret identifier, never a license value."""
    import matplotlib
    matplotlib.use("Agg")

    user = WorkspaceUser(user_id="matlab-license-ui-user", source="env-override")
    store = AWSConnectionStore(user=user, workspace_root=tmp_path)
    connection = store.create(region="us-east-2").with_role(
        "arn:aws:iam::774888247882:role/CryoStackExecutionRole"
    ).mark_connected(account_id="774888247882")
    store.save(connection)

    # The Save handler resolves the workspace root LIVE (same pattern as
    # resolve_cloud_execution elsewhere) -- the env vars must stay set for
    # the handler invocation below, not just for the build.
    import os
    os.environ["CRYOSTACK_WORKSPACE_USER"] = "matlab-license-ui-user"
    os.environ["USER"] = "matlab-license-ui-svc"
    os.environ["CRYOSTACK_WORKSPACE_ROOT"] = str(tmp_path)
    try:
        from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
        page = build_icesheets_ui()

        save_button = None

        def walk(w):
            nonlocal save_button
            if isinstance(w, W.Button) and getattr(w, "description", "") == "Save license ARN":
                save_button = w
            for c in getattr(w, "children", ()):
                walk(c)

        walk(page)
        assert save_button is not None, "Save license ARN button not found"
        assert save_button._click_handlers.callbacks

        handler = save_button._click_handlers.callbacks[0]

        def freevar(fn, name):
            idx = fn.__code__.co_freevars.index(name)
            return fn.__closure__[idx].cell_contents

        cloud_environment = freevar(handler, "cloud_environment")
        arn = "arn:aws:secretsmanager:us-east-2:774888247882:secret:issm-license-abc123"
        cloud_environment.matlab_license_arn.value = arn
        handler(None)
    finally:
        del os.environ["CRYOSTACK_WORKSPACE_USER"]
        del os.environ["USER"]
        del os.environ["CRYOSTACK_WORKSPACE_ROOT"]

    reloaded = AWSConnectionStore(user=user, workspace_root=tmp_path).load()
    assert reloaded.matlab_license_secret_arn == arn
    # the ARN, not a license value, and nothing else on the record changed
    assert reloaded.role_arn == connection.role_arn
    assert reloaded.account_id == "774888247882"


def test_gateway_rejects_a_pasted_license_value_instead_of_an_arn(tmp_path):
    import matplotlib
    matplotlib.use("Agg")

    user = WorkspaceUser(user_id="matlab-license-reject-user", source="env-override")
    store = AWSConnectionStore(user=user, workspace_root=tmp_path)
    connection = store.create(region="us-east-2").with_role(
        "arn:aws:iam::774888247882:role/CryoStackExecutionRole"
    ).mark_connected(account_id="774888247882")
    store.save(connection)

    import os
    os.environ["CRYOSTACK_WORKSPACE_USER"] = "matlab-license-reject-user"
    os.environ["USER"] = "matlab-license-reject-svc"
    os.environ["CRYOSTACK_WORKSPACE_ROOT"] = str(tmp_path)
    try:
        from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
        page = build_icesheets_ui()
    finally:
        del os.environ["CRYOSTACK_WORKSPACE_USER"]
        del os.environ["USER"]
        del os.environ["CRYOSTACK_WORKSPACE_ROOT"]

    save_button = None

    def walk(w):
        nonlocal save_button
        if isinstance(w, W.Button) and getattr(w, "description", "") == "Save license ARN":
            save_button = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    handler = save_button._click_handlers.callbacks[0]

    def freevar(fn, name):
        idx = fn.__code__.co_freevars.index(name)
        return fn.__closure__[idx].cell_contents

    cloud_environment = freevar(handler, "cloud_environment")
    cloud_environment.matlab_license_arn.value = "27000@my-license-server"
    handler(None)   # must not raise -- the error is printed, not thrown

    reloaded = AWSConnectionStore(user=user, workspace_root=tmp_path).load()
    assert reloaded.matlab_license_secret_arn == ""    # rejected, never saved
