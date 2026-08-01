from __future__ import annotations

import re

import plotly.graph_objects as go
import pytest

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


def test_sparkline_svg_markup_renders_safe_polyline() -> None:
    markup = ui._sparkline_svg_markup([2, 4, 3], color="#5b9cf0")

    assert "<svg" in markup
    assert "<polyline" in markup
    assert 'stroke="#5b9cf0"' in markup
    assert "<script" not in markup
    assert "0.00,28.00" in markup
    assert "100.00,16.00" in markup


def test_css_holds_no_colour_literals() -> None:
    """Colours live in theme.COLORS only. A literal in the stylesheet would be
    invisible to the palette, so the two would drift apart."""
    css = ui._CSS

    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", css)
    assert not re.findall(r"rgba?\(\s*\d", css)


def test_every_css_variable_used_is_defined_by_the_palette() -> None:
    declared = set(re.findall(r"--it-[a-z-]+(?=:)", theme.css_variables()))
    # --it-chart-h is a layout token the stylesheet declares for itself.
    declared |= set(re.findall(r"--it-[a-z-]+(?=:)", ui._CSS))
    used = set(re.findall(r"var\((--it-[a-z-]+)", ui._CSS))

    assert used, "expected the stylesheet to reference custom properties"
    assert used <= declared, f"undefined custom properties: {sorted(used - declared)}"
    assert "--it-accent-gold" in used


def test_css_variables_render_hex_and_rgb_forms() -> None:
    block = theme.css_variables()

    assert block.startswith(":root {")
    assert f"--it-accent-gold: {theme.COLORS['accent_gold']};" in block
    # rgba(var(--it-accent-gold-rgb), 0.18) needs a bare triple, not a hex.
    assert "--it-accent-gold-rgb: 212, 168, 67;" in block
    assert "--it-overlay-rgb: 255, 255, 255;" in block


def test_chart_layout_drops_the_hardcoded_height_so_css_can_drive_it() -> None:
    """A server-rendered figure cannot know the viewport. Heights come from
    --it-chart-h in the CSS instead, which flips at the 720px breakpoint."""
    fig = go.Figure(go.Scatter(x=[1, 2], y=[1, 2]))
    fig.update_layout(height=440)

    ui.chart_layout(fig)

    assert fig.layout.height is None
    assert fig.layout.autosize is True
    assert fig.layout.margin.l == 36
    assert fig.layout.legend.orientation == "h"
    assert fig.layout.xaxis.automargin is True
    assert fig.layout.yaxis.automargin is True


def test_chart_layout_only_shortens_month_level_date_ticks() -> None:
    """`Mar 2026` measured 57.6px on a 358px-wide chart. Overriding only the
    month-to-year tick band shortens it to `Mar '26` without touching the
    day-level ticks desktop actually renders."""
    fig = ui.chart_layout(go.Figure(go.Scatter(x=[1, 2], y=[1, 2])), date_axis=True)

    stops = fig.layout.xaxis.tickformatstops
    assert [stop.value for stop in stops] == ["%b '%y"]
    assert stops[0].dtickrange[1] == "M12"

    plain = ui.chart_layout(go.Figure(go.Scatter(x=[1, 2], y=[1, 2])))
    assert not plain.layout.xaxis.tickformatstops


def test_chart_layout_keeps_polar_charts_centred() -> None:
    """The radar has no cartesian axes, and an asymmetric left margin would
    push it off centre."""
    fig = go.Figure(go.Scatterpolar(r=[1, 2], theta=[0, 90]))

    ui.chart_layout(fig, date_axis=True)

    assert fig.layout.margin.l == fig.layout.margin.r == 24
    assert not fig.layout.xaxis.tickformatstops


def test_chart_key_encodes_the_size_token_and_rejects_unknown_sizes() -> None:
    assert ui._chart_key("compact", "timeofday") == "it-chart-compact-timeofday"
    with pytest.raises(ValueError, match="unknown chart size"):
        ui._chart_key("enormous", "whatever")


def test_css_drives_chart_height_at_both_breakpoints() -> None:
    css = ui._CSS
    mobile = css.split("@media (max-width: 720px)")[-1]

    assert 'var(--it-chart-h' in css
    for size in ui.CHART_SIZES:
        assert f'[class*="st-key-it-chart-{size}"]' in css
        assert f'[class*="st-key-it-chart-{size}"]' in mobile


def test_sparkline_svg_markup_handles_flat_and_invalid_values() -> None:
    flat = ui._sparkline_svg_markup([5, 5])
    invalid = ui._sparkline_svg_markup([float("nan"), float("inf")])

    assert "0.00,16.00 100.00,16.00" in flat
    assert invalid == ""


def test_sparkline_svg_markup_rejects_unsafe_stroke_values() -> None:
    markup = ui._sparkline_svg_markup([1, 2], color='red" onload="alert(1)')

    assert 'stroke="#d4a843"' in markup
    assert "onload" not in markup
