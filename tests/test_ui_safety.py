from __future__ import annotations

from iron_trail import ui


def test_html_helpers_escape_uploaded_text(monkeypatch) -> None:
    rendered = []
    monkeypatch.setattr(
        ui.st,
        "markdown",
        lambda body, **kwargs: rendered.append((body, kwargs)),
    )

    ui.hero("Label", "1", '<img src=x onerror="alert(1)">')
    ui.callout("warning", "<script>alert(1)</script>")
    ui.quote_card("<svg onload=alert(1)>")

    combined = "\n".join(body for body, _ in rendered)
    assert "<script>" not in combined
    assert "<img src=x" not in combined
    assert "<svg onload" not in combined
    assert "&lt;script&gt;" in combined
    assert "&lt;img" in combined
    assert "&lt;svg" in combined
