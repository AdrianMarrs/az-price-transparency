"""Download price files that refuse programs, with a real browser (Microsoft Edge, driven
by Playwright).

Some hospitals' servers sit behind a bot check (Cloudflare) that turns away any program,
even one sending a browser's User-Agent, because it can tell the client apart by how it
connects. The federal rule says the file must be downloadable by automated tools, so
fetching it with a browser takes nothing the hospital may withhold; the compliance check
still fails it for blocking programs (access = browser_download).

Each file is tried in headless Edge first, then in a visible Edge window, which gets past
checks that refuse headless browsers. Nothing else is done to hide the automation, and
a CAPTCHA is never solved: a file still blocked then is reported, for --fetch-in-browser
(a person) to get. Each mode keeps its own profile under data/browser-profile: a headless
visit marks the profile's cookies, and a window sharing them was then refused too (City of
Hope, October 2026).

Needs Microsoft Edge installed (no Playwright browser download), or BROWSER_CHANNEL=chromium
for Playwright's own Chromium (the cloud pipeline's image, docker/pipeline.Dockerfile, which
has no display, so only the headless try runs there). Turned off with BROWSER_FALLBACK=0, and
off anywhere the browser or a display is missing (CI).
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

PROFILE_DIR = Path("data/browser-profile")
WAIT_MS = 30_000  # for the download to start; a bot check that lets one through takes seconds


def channel() -> str | None:
    """Playwright's channel: msedge (the default), or None for its bundled Chromium."""
    name = os.environ.get("BROWSER_CHANNEL", "msedge")
    return None if name == "chromium" else name


@dataclass
class Fetched:
    ccn: str
    url: str
    path: Path | None = None  # the saved file, when it worked
    mode: str = ""  # headless or headed
    error: str = ""  # why not, when it didn't


def enabled() -> bool:
    if os.environ.get("BROWSER_FALLBACK", "1") == "0":
        return False
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def fetch_files(jobs: list[tuple[str, str]], dest_dir: Path) -> list[Fetched]:
    """Download each (ccn, url) into dest_dir: headless first, then a visible window for
    any the bot check refused."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    dest_dir.mkdir(parents=True, exist_ok=True)
    results = {ccn: Fetched(ccn, url) for ccn, url in jobs}
    with sync_playwright() as p:
        # No display (a container): a window can't open, so only the headless try.
        no_display = sys.platform.startswith("linux") and not os.environ.get("DISPLAY")
        for mode in ("headless",) if no_display else ("headless", "headed"):
            todo = [r for r in results.values() if r.path is None]
            if not todo:
                break
            try:
                context = p.chromium.launch_persistent_context(
                    str(PROFILE_DIR / mode), channel=channel(), headless=mode == "headless",
                    accept_downloads=True,
                )  # fmt: skip
            except PlaywrightError as e:  # no Edge, or no display for a window
                for r in todo:
                    why = f"{mode} browser would not start: {e.message.splitlines()[0]}"
                    r.error = f"{r.error}; {why}" if r.error else why
                continue
            try:
                page = context.new_page()
                for r in todo:
                    fetch_one(page, r, dest_dir, mode)
            finally:
                context.close()
    return list(results.values())


def fetch_one(page, r: Fetched, dest_dir: Path, mode: str) -> None:
    """Open the URL and save the download it starts; on failure note what the page showed."""
    from playwright.sync_api import Error as PlaywrightError

    try:
        with page.expect_download(timeout=WAIT_MS) as info:
            try:
                page.goto(r.url, timeout=WAIT_MS)
            except PlaywrightError:
                pass  # "Download is starting" aborts the navigation; expect_download decides
        download = info.value
        name = Path(httpx.URL(r.url).path).name or download.suggested_filename
        path = dest_dir / r.ccn / name  # the file's own name: import_manual checks it
        path.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(path)
        r.path, r.mode, r.error = path, mode, ""
    except PlaywrightError as e:
        title = ""
        try:
            title = page.title()
        except PlaywrightError:
            pass
        why = f"{mode}: {title or e.message.splitlines()[0]}"
        r.error = f"{r.error}; {why}" if r.error else why  # keep the headless try's reason
