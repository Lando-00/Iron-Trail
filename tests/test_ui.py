from __future__ import annotations

from iron_trail import theme, ui


def test_css_keeps_mobile_sidebar_toggle_reachable() -> None:
    css = ui._CSS

    assert "header { display: none !important; }" not in css
    assert '[data-testid="stExpandSidebarButton"]' in css
    assert '[data-testid="stAppDeployButton"]' in css
    assert '[data-testid="stMainMenu"]' in css
    assert "pointer-events: auto !important" in css


def test_css_makes_tabs_look_like_controls() -> None:
    """Default Streamlit tabs render as small grey text, so users miss whole
    sections (a beta tester never found the Coach chat). They must be styled
    as tappable pills with a visible selected state."""
    css = ui._CSS

    assert '[data-testid="stTab"]' in css
    assert '[data-testid="stTab"][aria-selected="true"]' in css
    assert "min-height: 44px" in css
    assert "flex-wrap: wrap" in css


def test_css_meets_mobile_tap_target_and_hero_rules() -> None:
    """Measured at 390x844: tap targets were 24-38px and the hero number
    wrapped to a 144px two-line block. Both are fixed inside a mobile-only
    media query so desktop is unaffected."""
    css = ui._CSS

    mobile = css.split("@media (max-width: 720px)")[-1]
    assert "min-height: 44px !important" in mobile
    assert '[data-testid="stSidebarNavLink"]' in mobile
    assert ".modebar-container { display: none !important; }" in mobile
    assert "clamp(40px, 12vw, 72px)" in mobile
    assert "white-space: nowrap" in mobile


def test_muted_text_passes_wcag_aa_on_the_app_background() -> None:
    """#5b5b62 scored 2.94:1 on #0a0a0c and failed AA for body text."""

    def _luminance(hex_colour: str) -> float:
        channels = [int(hex_colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    background = _luminance(theme.COLORS["bg"])
    muted = _luminance(theme.COLORS["text_muted"])
    contrast = (max(background, muted) + 0.05) / (min(background, muted) + 0.05)

    assert contrast >= 4.5, f"text_muted contrast is only {contrast:.2f}:1"



    markup = ui._sparkline_svg_markup([2, 4, 3], color="#5b9cf0")

    assert "<svg" in markup
    assert "<polyline" in markup
    assert 'stroke="#5b9cf0"' in markup
    assert "<script" not in markup
    assert "0.00,28.00" in markup
    assert "100.00,16.00" in markup


def test_sparkline_svg_markup_handles_flat_and_invalid_values() -> None:
    flat = ui._sparkline_svg_markup([5, 5])
    invalid = ui._sparkline_svg_markup([float("nan"), float("inf")])

    assert "0.00,16.00 100.00,16.00" in flat
    assert invalid == ""


def test_sparkline_svg_markup_rejects_unsafe_stroke_values() -> None:
    markup = ui._sparkline_svg_markup([1, 2], color='red" onload="alert(1)')

    assert 'stroke="#d4a843"' in markup
    assert "onload" not in markup
