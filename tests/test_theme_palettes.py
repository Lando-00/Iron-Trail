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
