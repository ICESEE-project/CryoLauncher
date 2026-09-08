"""Performance commit 2 -- the aiohttp web shell serves immediately; the
application Voila backends warm up in the background behind a themed page.

No real Voila process is ever spawned; port waits are mocked.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_APP_PATH = _REPO / "bin" / "icesee_app.py"


class _FakeProc:
    instances: list = []

    def __init__(self, *a, **k):
        self.starts = 0
        self.stops = 0
        _FakeProc.instances.append(self)

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1


def _load_app_module(monkeypatch, tmp_path, *, port_ok=True, start_mode="background"):
    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    monkeypatch.setenv("CRYOSTACK_APP_START_MODE", start_mode)
    _FakeProc.instances = []

    spec = importlib.util.spec_from_file_location("_icesee_app_warmup", _APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod, "ManagedProcess", _FakeProc)

    import cryostack_src.service_warmup as sw

    async def wait(host, port, timeout):
        await asyncio.sleep(0)
        return port_ok

    monkeypatch.setattr(sw, "_wait_for_port", wait)
    return mod


_uid = [0]


def _session_cookie(auth):
    _uid[0] += 1
    user = auth.storage.create_user(
        email=f"w{_uid[0]}@example.org", display_name="W", institution=None, password_hash="x",
    )
    session = auth.storage.create_session(ttl_seconds=3600, user_id=user.id)
    return {"icesee_session": session.id}


async def _client(mod):
    from aiohttp.test_utils import TestClient, TestServer

    app = mod.make_app()
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, app


def test_public_and_auth_routes_serve_without_waiting_for_voila(monkeypatch, tmp_path):
    mod = _load_app_module(monkeypatch, tmp_path)

    async def go():
        client, app = await _client(mod)
        try:
            # book index is a static file -> available immediately
            r = await client.get("/index.html")
            assert r.status == 200
            # auth login page -> available immediately
            r = await client.get("/auth/login")
            assert r.status == 200
            # an unauthenticated app hit redirects to login, never hangs on Voila
            r = await client.get("/icesheets/", allow_redirects=False)
            assert r.status in (302, 303)
            assert "/auth/login" in r.headers["Location"]
        finally:
            await client.close()

    asyncio.run(go())


def test_background_warmup_starts_both_services(monkeypatch, tmp_path):
    mod = _load_app_module(monkeypatch, tmp_path, port_ok=True)

    async def go():
        client, app = await _client(mod)
        try:
            state = app["state"]
            # give the background warm-up task a chance to complete
            for _ in range(50):
                if (state.icesheets.state is mod.ServiceState.READY
                        and state.run_center.state is mod.ServiceState.READY):
                    break
                await asyncio.sleep(0.01)
            assert state.icesheets.state is mod.ServiceState.READY
            assert state.run_center.state is mod.ServiceState.READY
            # exactly one process per service
            assert sum(p.starts for p in _FakeProc.instances) == 2
        finally:
            await client.close()

    asyncio.run(go())


def test_authenticated_hit_during_warmup_gets_the_themed_starting_page(monkeypatch, tmp_path):
    # port never comes up quickly -> stays STARTING
    mod = _load_app_module(monkeypatch, tmp_path)

    import cryostack_src.service_warmup as sw

    async def slow(host, port, timeout):
        await asyncio.sleep(5)
        return True

    monkeypatch.setattr(sw, "_wait_for_port", slow)

    async def go():
        client, app = await _client(mod)
        try:
            from icesee_auth import AuthManager
            auth = AuthManager()
            r = await client.get("/icesheets/", cookies=_session_cookie(auth),
                                 allow_redirects=False)
            assert r.status == 503
            assert r.headers.get("Retry-After")
            body = await r.text()
            assert "CryoLauncher is starting" in body
            assert "CryoStack" in body
            assert "http-equiv=\"refresh\"" in body
        finally:
            await client.close()

    asyncio.run(go())


def test_failed_backend_shows_retry_not_a_raw_502(monkeypatch, tmp_path):
    mod = _load_app_module(monkeypatch, tmp_path, port_ok=False)

    async def go():
        client, app = await _client(mod)
        try:
            state = app["state"]
            for _ in range(50):
                if state.icesheets.state is mod.ServiceState.FAILED:
                    break
                await asyncio.sleep(0.01)
            assert state.icesheets.state is mod.ServiceState.FAILED

            from icesee_auth import AuthManager
            auth = AuthManager()
            r = await client.get("/icesheets/", cookies=_session_cookie(auth),
                                 allow_redirects=False)
            assert r.status == 503
            body = await r.text()
            assert "could not start" in body
            assert "warmup_retry=1" in body   # a Retry control, not a spinner

            # retry resets the service and re-warms it
            import cryostack_src.service_warmup as sw

            async def ok(host, port, timeout):
                await asyncio.sleep(0)
                return True

            monkeypatch.setattr(sw, "_wait_for_port", ok)
            await client.get("/icesheets/?warmup_retry=1", cookies=_session_cookie(auth),
                             allow_redirects=False)
            for _ in range(50):
                if state.icesheets.state is mod.ServiceState.READY:
                    break
                await asyncio.sleep(0.01)
            assert state.icesheets.state is mod.ServiceState.READY
        finally:
            await client.close()

    asyncio.run(go())


def test_ready_backend_is_proxied_and_not_restarted(monkeypatch, tmp_path):
    mod = _load_app_module(monkeypatch, tmp_path, port_ok=True)

    async def fake_dispatch(request, port):
        from aiohttp import web
        return web.Response(text=f"proxied:{port}")

    monkeypatch.setattr(mod, "proxy_dispatch", fake_dispatch)

    async def go():
        client, app = await _client(mod)
        try:
            state = app["state"]
            for _ in range(50):
                if state.icesheets.state is mod.ServiceState.READY:
                    break
                await asyncio.sleep(0.01)

            from icesee_auth import AuthManager
            auth = AuthManager()
            cookies = _session_cookie(auth)
            for _ in range(5):
                r = await client.get("/icesheets/", cookies=cookies, allow_redirects=False)
                assert r.status == 200
                assert (await r.text()) == "proxied:8870"
            # still exactly one process launch for icesheets
            starts = sum(p.starts for p in _FakeProc.instances)
            assert starts == 2  # icesheets + run_center, each once
        finally:
            await client.close()

    asyncio.run(go())


def test_shutdown_cancels_warmup_and_stops_services(monkeypatch, tmp_path):
    mod = _load_app_module(monkeypatch, tmp_path, port_ok=True)

    async def go():
        client, app = await _client(mod)
        state = app["state"]
        for _ in range(50):
            if state.icesheets.state is mod.ServiceState.READY:
                break
            await asyncio.sleep(0.01)
        await client.close()   # triggers on_cleanup
        assert state._warmup_task is None or state._warmup_task.done()
        assert sum(p.stops for p in _FakeProc.instances) == 2

    asyncio.run(go())


def test_lazy_mode_does_not_warm_until_requested(monkeypatch, tmp_path):
    mod = _load_app_module(monkeypatch, tmp_path, port_ok=True, start_mode="lazy")

    async def go():
        client, app = await _client(mod)
        try:
            state = app["state"]
            await asyncio.sleep(0.05)
            assert state.icesheets.state is mod.ServiceState.STOPPED
            assert sum(p.starts for p in _FakeProc.instances) == 0

            from icesee_auth import AuthManager
            auth = AuthManager()
            await client.get("/icesheets/", cookies=_session_cookie(auth),
                             allow_redirects=False)
            for _ in range(50):
                if state.icesheets.state is mod.ServiceState.READY:
                    break
                await asyncio.sleep(0.01)
            assert state.icesheets.state is mod.ServiceState.READY
            # ICESEE was never touched
            assert state.run_center.state is mod.ServiceState.STOPPED
        finally:
            await client.close()

    asyncio.run(go())
