from __future__ import annotations

import pytest

from iron_trail import theme


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    first, second = _luminance(foreground), _luminance(background)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


@pytest.mark.parametrize("name", sorted(theme.PALETTES))
@pytest.mark.parametrize("key", ["text_primary", "text_secondary", "text_muted"])
def test_every_palette_keeps_body_text_at_wcag_aa(name: str, key: str) -> None:
    """The default palette shipped #5b5b62 at 2.94:1 once. Any new palette has
    to clear 4.5:1 against its own background before it can be selectable."""
    palette = theme.PALETTES[name]
    ratio = _contrast(palette[key], palette["bg"])

    assert ratio >= 4.5, f"{name}.{key} is only {ratio:.2f}:1 on {palette['bg']}"


@pytest.mark.parametrize("name", sorted(theme.PALETTES))
def test_every_palette_defines_every_colour(name: str) -> None:
    missing = set(theme.PALETTES[theme.DEFAULT_PALETTE]) - set(theme.PALETTES[name])

    assert not missing, f"{name} is missing {sorted(missing)}"
    assert theme.css_variables(theme.PALETTES[name]).startswith(":root {")
    assert name in theme.PALETTE_LABELS


def test_apply_palette_swaps_colours_charts_and_template_in_place() -> None:
    original_colors = dict(theme.COLORS)
    original_cycle = list(theme.CHART_CYCLE)
    colors, archetypes = theme.COLORS, theme.ARCHETYPE_COLORS
    try:
        theme.apply_palette("high_contrast")

        assert theme.COLORS["bg"] == "#000000"
        # Pages hold references to these objects, so they must mutate in place.
        assert theme.COLORS is colors
        assert theme.ARCHETYPE_COLORS is archetypes
        assert theme.CHART_CYCLE[0] == theme.COLORS["accent_gold"] != original_cycle[0]
        assert theme.ARCHETYPE_COLORS["Strength"] == theme.COLORS["accent_gold"]

        template = theme.pio.templates["irontrail"]
        assert template.layout.font.color == theme.COLORS["text_primary"]
    finally:
        theme.apply_palette(theme.DEFAULT_PALETTE)

    assert theme.COLORS == original_colors
    assert theme.CHART_CYCLE == original_cycle


def test_apply_palette_falls_back_to_the_default_for_unknown_names() -> None:
    assert theme.apply_palette("neon-hotdog") == theme.DEFAULT_PALETTE
    assert theme.COLORS["bg"] == theme.PALETTES[theme.DEFAULT_PALETTE]["bg"]


def _simulate(hex_colour: str, kind: str) -> tuple[float, float, float]:
    """Brettel-style LMS approximation of dichromatic vision."""
    channels = [int(hex_colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    r, g, b = (
        value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    )
    long = 0.31399 * r + 0.63951 * g + 0.04649 * b
    medium = 0.15537 * r + 0.75789 * g + 0.08670 * b
    short = 0.01775 * r + 0.10945 * g + 0.87262 * b
    if kind == "protan":
        long = 1.05118294 * medium - 0.05116099 * short
    elif kind == "deutan":
        medium = 0.9513092 * long + 0.04866992 * short
    return (
        5.47221206 * long - 4.6419601 * medium + 0.16963708 * short,
        -1.1252419 * long + 2.29317094 * medium - 0.1678952 * short,
        0.02980165 * long - 0.19318073 * medium + 1.16364789 * short,
    )


CHART_KEYS = (
    "accent_gold",
    "accent_blue",
    "accent_lavender",
    "accent_red",
    "accent_mint",
    "accent_peach",
)


@pytest.mark.parametrize("name", sorted(theme.PALETTES))
def test_chart_series_are_not_separable_by_colour_alone(name: str) -> None:
    """Documents *why* CHART_PATTERNS exists rather than asserting a floor that
    no six-colour palette can meet. Measured worst pairs collapse to ~0.02
    under protanopia, and the tightest greyscale gap is ~0.001."""
    palette = theme.PALETTES[name]
    worst = min(
        sum(
            (first - second) ** 2
            for first, second in zip(
                _simulate(palette[a], kind), _simulate(palette[b], kind)
            )
        )
        ** 0.5
        for kind in ("deutan", "protan")
        for index, a in enumerate(CHART_KEYS)
        for jndex, b in enumerate(CHART_KEYS)
        if index < jndex
    )

    if worst < 0.20:
        assert len(theme.CHART_PATTERNS) >= len(CHART_KEYS), (
            f"{name} has a {worst:.3f} worst dichromatic pair, so every chart "
            "series needs a distinct pattern to fall back on"
        )


def test_chart_patterns_cover_the_whole_colour_cycle() -> None:
    assert len(theme.CHART_PATTERNS) >= len(theme.CHART_CYCLE)
    assert len(set(theme.CHART_PATTERNS)) == len(theme.CHART_PATTERNS)


@pytest.mark.parametrize("name", sorted(theme.PALETTES))
def test_surfaces_sit_the_right_way_round_for_the_background(name: str) -> None:
    """Glass washes are drawn as rgba(overlay, low alpha). On a light theme the
    overlay has to be dark or every panel becomes a glare patch."""
    palette = theme.PALETTES[name]
    background_is_light = _luminance(palette["bg"]) > 0.5
    overlay_is_light = _luminance(palette["overlay"]) > 0.5

    assert background_is_light != overlay_is_light, (
        f"{name}: overlay {palette['overlay']} does not contrast its "
        f"background {palette['bg']}"
    )


def test_the_theme_ships_a_light_option() -> None:
    assert any(_luminance(p["bg"]) > 0.5 for p in theme.PALETTES.values())
