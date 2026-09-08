#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(REPO_ROOT),
    )


from control_center import (
    install_control_center,
)

from aiohttp import ClientSession, WSMsgType, web

from cryostack_src import perf
from cryostack_src.service_warmup import (
    ManagedVoilaService,
    ServiceState,
    warm_up_all,
)

#: wall-clock at process start -- perf reports "seconds since the process
#: started" for the web shell and each application backend.
_PROCESS_EPOCH = time.time()

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from icesee_auth import AuthManager

from control_center.services.access import (
    AccessService,
)


HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def book_root() -> Path:
    return repo_root() / "icesee_jupyter_book" / "_build" / "html"

def livist_root() -> Path:
    return (
        repo_root()
        / "external"
        / "living-ice-sheet-temperature"
        / "frontend"
        / "dist"
    )

def livist_docs_root() -> Path:
    return (
        repo_root()
        / "external"
        / "living-ice-sheet-temperature"
        / "site"
    )

def frozen_legacies_root() -> Path:
    return (
        repo_root()
        / "icesee_jupyter_book"
        / "applications"
        / "frozen_legacies"
    )


def frozen_legacies_data_root() -> Path:
    return frozen_legacies_root() / "data"


def frozen_legacies_assets_root() -> Path:
    return frozen_legacies_root() / "assets"

def maintainer_guide_source() -> Path:
    return (
        repo_root()
        / "icesee_jupyter_book"
        / "docs"
        / "maintainer_guide.md"
    )


# Minimal page shell for the role-protected Maintainer Guide. It reuses the
# published CryoStack stylesheet (/_static/icesee.css) — no page-specific
# visual system — and the same responsive .cryostack-docs-page rules that the
# public documentation pages use.
_MAINTAINER_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Maintainer Guide — CryoStack</title>
<link rel="stylesheet" href="/_static/icesee.css">
<style>
  body {{ margin: 0; background: #f8fafc; }}
  .cryostack-maintainer-shell {{
    max-width: 960px;
    margin: 0 auto;
    padding: 32px 22px 64px;
  }}
  .cryostack-maintainer-shell .cryostack-section-label {{ margin-bottom: 10px; }}
</style>
</head>
<body>
<main class="cryostack-docs-page cryostack-maintainer-shell">
  <div class="cryostack-section-label">CryoStack Operations</div>
  {body}
</main>
</body>
</html>
"""


async def maintainer_guide_redirect(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/docs/maintainer/")


async def maintainer_guide_page(request: web.Request) -> web.StreamResponse:
    src = maintainer_guide_source()
    if not src.exists():
        raise web.HTTPNotFound(text="Maintainer Guide source is not present.")

    from markdown_it import MarkdownIt

    md = (
        MarkdownIt("commonmark", {"html": False, "linkify": True})
        .enable("table")
        .enable("strikethrough")
    )
    body = md.render(src.read_text(encoding="utf-8"))
    return web.Response(
        text=_MAINTAINER_SHELL.format(body=body),
        content_type="text/html",
    )


# --- application warm-up holding page ------------------------------------
# Shown (instead of a raw 502 / connection-refused) when an application is
# reached before its Voila backend has finished starting. Reuses the canonical
# CryoStack mark and the published stylesheet -- no page-specific visual system.
def _cryostack_mark_uri() -> str:
    try:
        from icesee_jupyter_book.ui.shared_application_header import _mark_data_uri
        return _mark_data_uri()
    except Exception:
        return ""


_WARMING_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{app} is starting — CryoStack</title>
{refresh}
<link rel="stylesheet" href="/_static/icesee.css">
<style>
  body {{ margin: 0; background: #f8fafc; }}
  .cryostack-warmup {{
    max-width: 460px; margin: 12vh auto 0; padding: 34px 26px;
    text-align: center;
    border: 1px solid rgba(15,23,42,.08); border-radius: 16px; background: #fff;
    box-shadow: 0 8px 24px rgba(15,23,42,.05);
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  }}
  .cryostack-warmup img, .cryostack-warmup .mark {{
    width: 52px; height: 52px; object-fit: contain; margin-bottom: 14px;
  }}
  .cryostack-warmup .brand {{
    color: rgba(15,23,42,.55); font-size: 12px; font-weight: 700;
    letter-spacing: .08em; text-transform: uppercase;
  }}
  .cryostack-warmup h1 {{ margin: 6px 0 10px; font-size: 20px; color: #111827; }}
  .cryostack-warmup p {{ color: rgba(15,23,42,.62); font-size: 14px; line-height: 1.55; }}
  .cryostack-warmup .status {{
    display: inline-flex; align-items: center; gap: 8px; margin-top: 14px;
    padding: 6px 13px; border-radius: 999px; font-size: 13px; font-weight: 700;
    background: rgba(37,99,235,.10); color: #1d4ed8;
  }}
  .cryostack-warmup .status.failed {{ background: rgba(220,38,38,.12); color: #b91c1c; }}
  .cryostack-warmup .dot {{ font-size: 11px; }}
  .cryostack-warmup a.retry {{
    display: inline-block; margin-top: 16px; padding: 8px 16px; border-radius: 9px;
    background: #2563eb; color: #fff; font-weight: 700; text-decoration: none; font-size: 13px;
  }}
  .cryostack-warmup .diag {{
    margin-top: 14px; font-size: 12px; color: rgba(15,23,42,.5);
    word-break: break-word; text-align: left;
  }}
  @media (max-width: 430px) {{ .cryostack-warmup {{ margin-top: 8vh; padding: 26px 18px; }} }}
</style>
</head>
<body>
<main class="cryostack-warmup">
  {mark}
  <div class="brand">CryoStack</div>
  <h1>{heading}</h1>
  <p>{message}</p>
  <div class="status{status_class}"><span class="dot">●</span>{status_label}</div>
  {extra}
</main>
</body>
</html>
"""


def _warming_page(app_label: str, state: "ServiceState", *, error: str = "") -> web.Response:
    uri = _cryostack_mark_uri()
    mark = (
        f'<img src="{uri}" alt="CryoStack" />' if uri
        else '<div class="mark" style="font-size:38px;line-height:52px;color:#1d4ed8;">❄</div>'
    )
    if state is ServiceState.FAILED:
        return web.Response(
            status=503,
            content_type="text/html",
            text=_WARMING_PAGE.format(
                app=app_label, refresh="", mark=mark,
                heading=f"{app_label} could not start",
                message="The interactive application backend did not come up. "
                        "An operator can check the service logs.",
                status_class=" failed", status_label="Failed",
                extra=(
                    '<a class="retry" href="?warmup_retry=1">Retry</a>'
                    + (f'<div class="diag">{error}</div>' if error else "")
                ),
            ),
        )
    return web.Response(
        status=503,
        headers={"Retry-After": "3"},
        content_type="text/html",
        text=_WARMING_PAGE.format(
            app=app_label,
            refresh='<meta http-equiv="refresh" content="3">',
            mark=mark,
            heading=f"{app_label} is starting",
            message="Preparing the interactive application… This page will "
                    "continue automatically.",
            status_class="", status_label="Starting",
            extra="",
        ),
    )


def run_center_nb() -> Path:
    return repo_root() / "icesee_jupyter_book" / "icesee_jupyter_notebooks" / "run_center_voila.ipynb"


def icesheets_nb() -> Path:
    return repo_root() / "icesee_jupyter_book" / "icesee_jupyter_notebooks" / "icesheets_voila.ipynb"


def wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.25)
    return False


async def root_redirect(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/index.html")

async def livist_redirect(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/livist/")

async def livist_docs_redirect(
    request: web.Request,
) -> web.StreamResponse:
    raise web.HTTPFound("/livist/docs/")

async def livist_index(request: web.Request) -> web.StreamResponse:
    index_file = livist_root() / "index.html"

    if not index_file.exists():
        raise web.HTTPNotFound(
            text=(
                "LIVIST frontend has not been built. "
                "Run `yarn build` in "
                "external/living-ice-sheet-temperature/frontend."
            )
        )

    return web.FileResponse(index_file)

async def livist_docs_redirect(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/livist/docs/")


async def livist_docs_index(request: web.Request) -> web.StreamResponse:
    index_file = livist_docs_root() / "index.html"

    if not index_file.exists():
        raise web.HTTPNotFound(
            text=(
                "LIVIST documentation has not been built. "
                "Run `uv run zensical build` in "
                "external/living-ice-sheet-temperature."
            )
        )

    return web.FileResponse(index_file)

async def livist_docs_page(request: web.Request) -> web.StreamResponse:
    tail = request.match_info.get("tail", "").strip("/")

    docs_root = livist_docs_root().resolve()
    requested_path = (docs_root / tail).resolve()

    # Prevent paths such as ../../ from escaping the docs directory.
    if docs_root not in requested_path.parents and requested_path != docs_root:
        raise web.HTTPForbidden(text="Invalid documentation path.")

    if requested_path.is_dir():
        requested_path = requested_path / "index.html"

    if not requested_path.exists() or not requested_path.is_file():
        raise web.HTTPNotFound(text="LIVIST documentation page not found.")

    return web.FileResponse(requested_path)

async def frozen_legacies_redirect(
    request: web.Request,
) -> web.StreamResponse:
    raise web.HTTPFound("/frozen-legacies/")


async def frozen_legacies_index(
    request: web.Request,
) -> web.StreamResponse:

    index_file = (
        frozen_legacies_root()
        / "index.html"
    )

    if not index_file.exists():
        raise web.HTTPNotFound(
            text=(
                "FrozenLegacies frontend has not "
                "been created yet. Expected:\n"
                f"{index_file}"
            )
        )

    return web.FileResponse(index_file)

class ManagedProcess:
    def __init__(self, command: list[str], cwd: Path):
        self.command = command
        self.cwd = cwd
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        self.proc = subprocess.Popen(
            self.command,
            cwd=str(self.cwd),
            stdout=sys.stdout,
            stderr=sys.stderr,
            preexec_fn=os.setsid,
        )

    def stop(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            self.proc.wait(timeout=10)
        except Exception:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except Exception:
                pass


class ICESEEState:
    def __init__(self) -> None:
        py = sys.executable
        root = repo_root()

        self.run_center_port = 8866
        self.icesheets_port = 8870

        _run_center_proc = ManagedProcess(
            [
                py,
                "-m",
                "voila",
                str(run_center_nb()),
                "--no-browser",
                "--Voila.ip=127.0.0.1",
                "--port=8866",
                "--Voila.base_url=/icesee-gui/",
                "--Voila.allow_origin=http://127.0.0.1:8080",
            ],
            root,
        )

        _icesheets_proc = ManagedProcess(
            [
                py,
                "-m",
                "voila",
                str(icesheets_nb()),
                "--no-browser",
                "--Voila.ip=127.0.0.1",
                "--port=8870",
                "--Voila.base_url=/icesheets/",
                "--Voila.allow_origin=http://127.0.0.1:8080",
                # Surface the proxy-verified CryoStack identity into the kernel
                # environment (HTTP_X_CRYOSTACK_USER_ID) so Workspace history is
                # isolated per authenticated user. preheat_kernel stays disabled
                # (default) so each render's kernel sees its own request headers.
                "--VoilaConfiguration.http_header_envs=X-CryoStack-User-Id",
                "--VoilaConfiguration.http_header_envs=X-CryoStack-User-Name",
            ],
            root,
        )

        self.run_center = ManagedVoilaService(
            name="icesee", process=_run_center_proc,
            port=self.run_center_port, origin_epoch=_PROCESS_EPOCH,
        )
        self.icesheets = ManagedVoilaService(
            name="icesheets", process=_icesheets_proc,
            port=self.icesheets_port, origin_epoch=_PROCESS_EPOCH,
        )

        self.client: ClientSession | None = None
        self._warmup_task: asyncio.Task | None = None

    def start_mode(self) -> str:
        mode = os.environ.get("CRYOSTACK_APP_START_MODE", "background").strip().lower()
        return mode if mode in ("background", "lazy") else "background"

    async def startup(self, app: web.Application) -> None:
        # Fail fast on a broken deploy -- but this is all cheap `.exists()`.
        if not book_root().joinpath("index.html").exists():
            raise RuntimeError(f"Missing built book at {book_root() / 'index.html'}")
        if not run_center_nb().exists():
            raise RuntimeError(f"Missing notebook {run_center_nb()}")
        if not icesheets_nb().exists():
            raise RuntimeError(f"Missing notebook {icesheets_nb()}")

        self.client = ClientSession()

        # The web shell (home, docs, auth, Control Center, /connect/, static
        # assets) is now serviceable. The two application Voila servers warm up
        # in the background so a user reading the homepage does not wait on
        # them; by the time they click an application it is usually ready.
        if self.start_mode() == "background":
            self._warmup_task = asyncio.create_task(
                warm_up_all(
                    [self.icesheets, self.run_center],
                    origin_label="aiohttp ready",
                    origin_seconds=time.time() - _PROCESS_EPOCH,
                )
            )
        else:  # lazy: first request to an application triggers its warm-up
            perf.mark("aiohttp ready", time.time() - _PROCESS_EPOCH)

    async def cleanup(self, app: web.Application) -> None:
        if self._warmup_task and not self._warmup_task.done():
            self._warmup_task.cancel()
            try:
                await self._warmup_task
            except (asyncio.CancelledError, Exception):
                pass
        if self.client:
            await self.client.close()
        self.run_center.stop()
        self.icesheets.stop()


def build_upstream_headers(
    request: web.Request,
    upstream_port: int,
) -> dict[str, str]:
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP
        and k.lower()
        not in {
            "host",
            "origin",
            "x-cryostack-user-id",
            "x-cryostack-user-email",
            "x-cryostack-user-name",
        }
    }

    headers["Host"] = f"127.0.0.1:{upstream_port}"
    headers["Origin"] = f"http://127.0.0.1:{upstream_port}"

    headers["X-Forwarded-Proto"] = "http"
    headers["X-Forwarded-Host"] = request.host
    headers["X-Forwarded-For"] = (
        request.remote or "127.0.0.1"
    )

    # ---------------------------------------------------------
    # Trusted CryoStack identity
    # ---------------------------------------------------------
    user = request.get("cryostack_user")

    if user is not None:
        headers["X-CryoStack-User-Id"] = user.id
        headers["X-CryoStack-User-Email"] = user.email
        headers["X-CryoStack-User-Name"] = (
            user.display_name
        )

    return headers

async def proxy_http(request: web.Request, upstream_port: int) -> web.StreamResponse:
    state: ICESEEState = request.app["state"]
    assert state.client is not None

    upstream_url = f"http://127.0.0.1:{upstream_port}{request.rel_url}"
    headers = build_upstream_headers(request, upstream_port)
    body = await request.read()

    async with state.client.request(
        request.method,
        upstream_url,
        headers=headers,
        data=body if body else None,
        allow_redirects=False,
    ) as resp:
        out = web.StreamResponse(status=resp.status, reason=resp.reason)
        for k, v in resp.headers.items():
            if k.lower() not in HOP_BY_HOP:
                out.headers[k] = v

        await out.prepare(request)
        async for chunk in resp.content.iter_chunked(65536):
            await out.write(chunk)
        await out.write_eof()
        return out


async def proxy_ws(request: web.Request, upstream_port: int) -> web.WebSocketResponse:
    state: ICESEEState = request.app["state"]
    assert state.client is not None

    upstream_url = f"http://127.0.0.1:{upstream_port}{request.rel_url}"
    headers = build_upstream_headers(request, upstream_port)

    browser_ws = web.WebSocketResponse()
    await browser_ws.prepare(request)

    async with state.client.ws_connect(upstream_url, headers=headers) as upstream_ws:

        async def browser_to_upstream() -> None:
            async for msg in browser_ws:
                if msg.type == WSMsgType.TEXT:
                    await upstream_ws.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await upstream_ws.send_bytes(msg.data)
                elif msg.type == WSMsgType.CLOSE:
                    await upstream_ws.close()

        async def upstream_to_browser() -> None:
            async for msg in upstream_ws:
                if msg.type == WSMsgType.TEXT:
                    await browser_ws.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await browser_ws.send_bytes(msg.data)
                elif msg.type == WSMsgType.CLOSE:
                    await browser_ws.close()

        await asyncio.gather(browser_to_upstream(), upstream_to_browser())

    return browser_ws


async def proxy_dispatch(request: web.Request, upstream_port: int) -> web.StreamResponse:
    upgrade = request.headers.get("Upgrade", "").lower()
    connection = request.headers.get("Connection", "").lower()
    if upgrade == "websocket" or "upgrade" in connection:
        return await proxy_ws(request, upstream_port)
    return await proxy_http(request, upstream_port)


async def _proxy_application(
    request: web.Request, service: "ManagedVoilaService", app_label: str
) -> web.StreamResponse:
    """Proxy to a Voila application, showing a themed 'starting' page (never a
    raw 502 / connection-refused) while its backend warms up."""
    if request.query.get("warmup_retry"):
        service.request_retry()

    state = service.ensure_started()
    if state is not ServiceState.READY:
        # A websocket handshake cannot render an HTML holding page -- ask the
        # browser to retry the whole page instead.
        upgrade = request.headers.get("Upgrade", "").lower()
        if upgrade == "websocket":
            return web.Response(status=503, headers={"Retry-After": "2"},
                                text=f"{app_label} backend is starting")
        return _warming_page(app_label, state, error=service.error)

    return await proxy_dispatch(request, service.port)


async def proxy_run_center(request: web.Request) -> web.StreamResponse:
    state: ICESEEState = request.app["state"]
    return await _proxy_application(request, state.run_center, "ICESEE")


async def proxy_icesheets(request: web.Request) -> web.StreamResponse:
    state: ICESEEState = request.app["state"]
    return await _proxy_application(request, state.icesheets, "CryoLauncher")


def make_app() -> web.Application:
    app = web.Application()
    state = ICESEEState()
    app["state"] = state

    app.on_startup.append(state.startup)
    app.on_cleanup.append(state.cleanup)

    auth = AuthManager()
    auth.install(app)

    #
    # Control Center access/roles
    #
    access_service = AccessService(
        auth.storage,
    )

    app["access_service"] = access_service

    install_control_center(
        app,
        auth=auth,
    )

    protected_run_center = auth.require_login(
        proxy_run_center
    )

    protected_icesheets = auth.require_login(
        proxy_icesheets
    )

    # ICESEE application
    app.router.add_route(
        "*",
        "/icesee-gui",
        protected_run_center,
    )

    app.router.add_route(
        "*",
        "/icesee-gui/{tail:.*}",
        protected_run_center,
    )

    # CryoLauncher application
    app.router.add_route(
        "*",
        "/icesheets",
        protected_icesheets,
    )

    app.router.add_route(
        "*",
        "/icesheets/{tail:.*}",
        protected_icesheets,
    )

    app.router.add_get("/livist/docs", livist_docs_redirect)
    app.router.add_get("/livist/docs/", livist_docs_index)

    app.router.add_get("/livist/docs/{tail:.*}", livist_docs_page)

    app.router.add_get("/livist", livist_redirect)
    app.router.add_get("/livist/", livist_index)

    app.router.add_static(
        "/livist/",
        path=str(livist_root()),
        show_index=False,
    )

    # ---------------------------------------------------------
    # FrozenLegacies application
    # ---------------------------------------------------------

    app.router.add_get(
        "/frozen-legacies",
        frozen_legacies_redirect,
    )

    app.router.add_get(
        "/frozen-legacies/",
        frozen_legacies_index,
    )

    app.router.add_static(
        "/frozen-legacies/assets/",
        path=str(
            frozen_legacies_assets_root()
        ),
        show_index=False,
    )

    app.router.add_static(
        "/frozen-legacies/data/",
        path=str(
            frozen_legacies_data_root()
        ),
        show_index=False,
    )
    
    # Role-protected Maintainer / Operations Guide. Restricted at the request
    # boundary by the same require_roles mechanism as the Control Center; the
    # source markdown is deliberately excluded from the public book build.
    maintainer_access = auth.require_roles(
        "developer",
        "maintainer",
        "admin",
        "owner",
    )
    app.router.add_get("/docs/maintainer", maintainer_guide_redirect)
    app.router.add_get(
        "/docs/maintainer/",
        maintainer_access(maintainer_guide_page),
    )

    app.router.add_get("/", root_redirect)
    app.router.add_static("/", path=str(book_root()), show_index=True)

    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="127.0.0.1", port=8080)