from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


def test_landing_builds_https_calendar_url_for_github_pages() -> None:
    app = (PUBLIC / "app.js").read_text(encoding="utf-8")

    assert 'new URL("penya.ics", window.location.href)' in app
    assert 'calendarUrl.protocol = "https:"' in app


def test_landing_builds_webcal_url() -> None:
    app = (PUBLIC / "app.js").read_text(encoding="utf-8")

    assert 'httpsUrl.replace(/^https:/, "webcal:")' in app


def test_google_calendar_url_encodes_the_https_calendar_url() -> None:
    public_url = "https://example.github.io/penya-calendar/penya.ics"
    expected = f"https://calendar.google.com/calendar/r?cid={quote(public_url, safe='')}"
    app = (PUBLIC / "app.js").read_text(encoding="utf-8")

    assert expected == (
        "https://calendar.google.com/calendar/r?cid="
        "https%3A%2F%2Fexample.github.io%2Fpenya-calendar%2Fpenya.ics"
    )
    assert "encodeURIComponent(httpsUrl)" in app


def test_landing_has_no_download_action_or_language() -> None:
    public_ui = "\n".join(
        (PUBLIC / filename).read_text(encoding="utf-8")
        for filename in ("index.html", "styles.css", "app.js")
    ).casefold()

    assert "download" not in public_ui
    assert "descarrega" not in public_ui


def test_public_landing_contains_subscription_cta_and_no_technical_copy() -> None:
    html = (PUBLIC / "index.html").read_text(encoding="utf-8").casefold()

    assert "subscriu-te al calendari" in html
    assert "ics" not in html
    assert "github actions" not in html
    assert "scraper" not in html


def test_workflow_keeps_daily_run_and_publishes_public_directory() -> None:
    workflow = (ROOT / ".github/workflows/sync-calendar.yml").read_text(encoding="utf-8")
    script = (ROOT / "scripts/sync_calendar.py").read_text(encoding="utf-8")

    assert 'cron: "15 4 * * *"' in workflow
    assert "timedelta(hours=48)" in script
    assert "actions/upload-pages-artifact@v3" in workflow
    assert "path: public" in workflow
    assert "actions/deploy-pages@v4" in workflow


def test_current_ics_has_unique_uids() -> None:
    ics = (PUBLIC / "penya.ics").read_text(encoding="utf-8")
    uids = [line.removeprefix("UID:") for line in ics.splitlines() if line.startswith("UID:")]

    assert len(uids) == len(set(uids))
