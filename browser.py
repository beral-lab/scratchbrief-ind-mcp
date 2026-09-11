"""
browser.py — nodriver lifecycle for indiankanoon.org.

indiankanoon.org sits behind Cloudflare's JS challenge ("Just a moment...").
Confirmed against the live site (2026-09-06):
  - headless=True gets stuck showing the challenge page indefinitely.
  - headless=False (a real, visible Chrome window) clears it in ~0-2s.
  - Once cleared, Cloudflare's clearance cookie is written into the Chrome
    profile dir (user_data_dir). A *headless* browser reusing that same
    profile dir then clears the challenge instantly too, with no visible
    window — confirmed by warming up headful once and immediately reusing
    the profile headless.

So: keep one persistent Chrome profile on disk (PROFILE_DIR). Most calls
just reuse it headless. Only when that clearance has expired (or on first
ever run) does a call pay for one quick, fully-automated headful warm-up
pass — no human interaction needed, unlike a login flow.

Also confirmed the hard way: a CDP call (page.evaluate, browser.get) can
hang forever on a broken devtools websocket with no exception surfaced --
observed as a `get_document()` call that just never returned. Every such
call in this module goes through evaluate()/goto() below, which enforce a
hard timeout and reset the shared browser on expiry, rather than calling
nodriver directly.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import nodriver as uc

BASE_URL = "https://indiankanoon.org"

# api_server.py (the always-on self-started backend) and indiankanoon_mcp.py
# (launched separately by Claude Desktop) both use this module, but Chrome
# only allows one process per --user-data-dir -- sharing PROFILE_DIR between
# two concurrently-running processes made the second one fail to launch with
# "Failed to connect to browser" whenever the backend was already running.
# IK_CHROME_PROFILE_DIR (set in Claude Desktop's config for the MCP server)
# gives each process its own profile so they can run at the same time.
PROFILE_DIR = Path(os.environ.get("IK_CHROME_PROFILE_DIR") or Path(__file__).parent / ".chrome-profile")

_CHALLENGE_TITLE_MARKER = "just a moment"
_CHALLENGE_POLL_INTERVAL = 2  # seconds
_CHALLENGE_MAX_POLLS = 15  # ~30s ceiling before giving up

_CDP_TIMEOUT = 20  # seconds, per evaluate()/goto() call
_LAUNCH_TIMEOUT = 30  # seconds, for starting the Chrome subprocess itself

_browser: uc.Browser | None = None
_lock = asyncio.Lock()


async def _bounded(coro, what: str, timeout: float = _CDP_TIMEOUT):
    """Runs `coro` with a hard timeout that never itself blocks.

    asyncio.wait_for() cancels its inner task on timeout and then *waits for
    that cancellation to complete* -- if the inner call is stuck in a
    non-cooperative wait (observed with both nodriver's CDP websocket calls
    AND the initial Chrome subprocess launch itself, on Windows), the
    cancelled task never actually finishes, and wait_for hangs right along
    with it. asyncio.wait() with a timeout instead just checks whether the
    task finished in time; on timeout we fire off a cancel and move on
    without waiting for it, so this call is guaranteed to return.
    """
    task = asyncio.ensure_future(coro)
    done, _pending = await asyncio.wait({task}, timeout=timeout)
    if task in done:
        return task.result()
    task.cancel()
    await close_browser()
    raise RuntimeError(
        f"TIMEOUT: {what} did not respond within {timeout}s "
        "(devtools connection likely broken). The browser has been reset "
        "-- retry the request."
    )


async def evaluate(page, expression: str):
    """page.evaluate() with a hard timeout. Resets the shared browser on
    timeout so the next call gets a fresh connection instead of hanging on
    the same broken one."""
    return await _bounded(page.evaluate(expression), "page.evaluate()")


async def _goto(browser: uc.Browser, url: str):
    return await _bounded(browser.get(url), "navigation")


async def _kill_stray_chrome() -> None:
    """Best-effort cleanup of Chrome processes still holding PROFILE_DIR
    open. Only ever matches by our own isolated --user-data-dir path, so
    this can't touch the user's real Chrome windows. Needed because a
    launch that times out below leaves its Chrome subprocess orphaned (we
    never got a handle to it to call .stop() on)."""
    profile = str(PROFILE_DIR).replace("\\", "\\\\")
    cmd = (
        "wmic process where \"name='chrome.exe' and CommandLine like "
        f"'%{profile}%'\" call terminate"
    )
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=10)
    except Exception:
        pass


async def _launch(headless: bool) -> uc.Browser:
    PROFILE_DIR.mkdir(exist_ok=True)
    return await _bounded(
        uc.start(headless=headless, user_data_dir=str(PROFILE_DIR)),
        "browser launch",
        timeout=_LAUNCH_TIMEOUT,
    )


async def _past_challenge(page) -> bool:
    """Polls the page title; True once Cloudflare's interstitial is gone.

    Requires readyState=='complete' AND a non-empty title: right after
    navigation starts, document.title is briefly "" (not yet the real page
    title, not yet "Just a moment..." either) -- treating "no marker present"
    as "cleared" at that instant is a false positive that races the actual
    page load and leaves callers reading a half-empty DOM.
    """
    for _ in range(_CHALLENGE_MAX_POLLS):
        title = (await evaluate(page, "document.title")) or ""
        ready = await evaluate(page, "document.readyState")
        if title and ready == "complete" and _CHALLENGE_TITLE_MARKER not in title.lower():
            return True
        await page.sleep(_CHALLENGE_POLL_INTERVAL)
    return False


async def _warm_up() -> None:
    """One-time visible pass, solely to mint a clearance cookie into PROFILE_DIR."""
    browser = await _launch(headless=False)
    try:
        page = await _goto(browser, BASE_URL + "/")
        await _past_challenge(page)
    finally:
        try:
            await browser.stop()
        except Exception:
            pass


async def _get_browser() -> uc.Browser:
    global _browser
    if _browser is None:
        _browser = await _launch(headless=True)
    return _browser


async def close_browser() -> None:
    """Stops the shared browser, if any. Also used internally to reset
    after a stale/expired clearance cookie -- or a hung CDP connection --
    is detected mid-session."""
    global _browser
    if _browser is not None:
        browser, _browser = _browser, None
        try:
            await browser.stop()
        except Exception:
            pass
    await _kill_stray_chrome()


async def new_page(url: str, *, _warmed: bool = False):
    """Navigates the shared headless browser to `url`, escalating to a
    headful warm-up pass automatically if Cloudflare is still blocking.

    Raises RuntimeError("NEEDS_CLEARANCE: ...") if even a fresh warm-up
    doesn't get past the challenge (e.g. IndiaKanoon is rate-limiting this
    IP) — callers should surface that message rather than retry in a loop.
    """
    async with _lock:
        browser = await _get_browser()
        page = await _goto(browser, url)
        if await _past_challenge(page):
            return page
        if _warmed:
            raise RuntimeError(
                "NEEDS_CLEARANCE: IndiaKanoon's Cloudflare challenge is "
                "still blocking requests even after a fresh headful "
                "warm-up pass. Try again in a minute."
            )
        await close_browser()
        await _warm_up()
    return await new_page(url, _warmed=True)
