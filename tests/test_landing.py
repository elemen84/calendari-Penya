from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


def _unfold_ics(value: str) -> str:
    lines: list[str] = []
    for line in value.splitlines():
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return "\n".join(lines)


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


def test_landing_remains_in_catalan() -> None:
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")

    assert '<html lang="ca">' in html
    assert "Calendari de la Penya" in html
    assert "Subscriu-t'hi una vegada" in html
    assert "Actualització automàtica cada 48 hores." in html
    assert "Liga Endesa" in html
    assert "Basketball Champions League" in html


def test_landing_uses_penya_identity_with_optional_shield_fallback() -> None:
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    styles = (PUBLIC / "styles.css").read_text(encoding="utf-8")
    app = (PUBLIC / "app.js").read_text(encoding="utf-8")
    favicon = (PUBLIC / "favicon.svg").read_text(encoding="utf-8")

    assert 'src="./assets/penya-shield.png"' in html
    assert 'Calendari no oficial de la Penya' in html
    assert "--green: #0a6a43" in styles
    assert "--green-dark: #074d31" in styles
    assert "--accent: #d8842a" in styles
    assert 'shield.addEventListener("error", showFallback)' in app
    assert '#0a6a43' in favicon
    assert '#111111' in favicon


def test_workflow_keeps_daily_run_and_publishes_public_directory() -> None:
    workflow = (ROOT / ".github/workflows/sync-calendar.yml").read_text(encoding="utf-8")
    script = (ROOT / "scripts/sync_calendar.py").read_text(encoding="utf-8")

    assert 'cron: "15 4 * * *"' in workflow
    assert "timedelta(hours=48)" in script
    assert "actions/upload-pages-artifact@v3" in workflow
    assert "path: public" in workflow
    assert "actions/deploy-pages@v4" in workflow
    assert "git add data/sync-state.json data/standings public/penya.ics" in workflow
    assert "GOOGLE_" not in workflow
    assert "secrets." not in workflow
    assert "google" not in script.casefold()

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "google" not in requirements.casefold()
    assert "google" not in project.casefold()
    assert not (ROOT / "src/calendar/google_calendar.py").exists()


def test_current_ics_has_unique_uids() -> None:
    ics = (PUBLIC / "penya.ics").read_text(encoding="utf-8")
    uids = [line.removeprefix("UID:") for line in ics.splitlines() if line.startswith("UID:")]

    assert len(uids) == 40
    assert len(uids) == len(set(uids))


def test_published_ics_uses_catalan_event_labels() -> None:
    ics = _unfold_ics((PUBLIC / "penya.ics").read_text(encoding="utf-8"))
    events = ics.split("BEGIN:VEVENT")[1:]
    acb_events = [event for event in events if "UID:liga-endesa:" in event]
    bcl_events = [event for event in events if "UID:bcl:" in event]

    assert acb_events
    assert bcl_events
    assert all("CLASSIFICACIÓ" in event for event in acb_events)
    assert all("Classificació encara no disponible" in event for event in acb_events)
    assert all(
        all(
            label not in event
            for label in ("Clasificación", "Fuente", "Actualizado", "Classification", "Source")
        )
        for event in acb_events
    )
    assert all("CLASSIFICACIÓ" not in event for event in bcl_events)
