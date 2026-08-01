"""Color palette, Plotly template, and named colour helpers for IronTrail.

Importing this module registers a Plotly template called ``irontrail`` and
makes it the global default. All charts created after import inherit the
custom dark + glassy theme automatically.
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

COLORS = {
    "bg": "#0a0a0c",
    "surface": "rgba(255,255,255,0.03)",
    "surface_strong": "rgba(255,255,255,0.06)",
    "border": "rgba(255,255,255,0.10)",
    "border_strong": "rgba(255,255,255,0.18)",
    "text_primary": "#e7e7e9",
    "text_secondary": "#8a8a93",
    # 4.85:1 on #0a0a0c — the previous #5b5b62 was 2.94:1 and failed WCAG AA
    # for body text, which showed up badly on phones in daylight.
    "text_muted": "#7d7d86",
    "text_soft": "#b5b5b9",
    "text_tab": "#b9b9c2",
    # Tinted overlays (surfaces, borders, glows) are drawn in this colour at low
    # alpha, so it is what decides whether panels sit above or below the page.
    "overlay": "#ffffff",
    "accent_gold": "#d4a843",
    "accent_blue": "#5b9cf0",
    "accent_red": "#e85a4f",
    "accent_green": "#5dc77c",
    "accent_lavender": "#9b87f5",
    "accent_peach": "#e8a05b",
    "accent_mint": "#5dc77c",
    # Readable text on top of a 6%-alpha accent wash — the accents themselves
    # are too saturated to read as body copy inside callouts.
    "tint_gold": "#e6c887",
    "tint_blue": "#a3c4f0",
    "tint_blue_soft": "#b5cef5",
    "tint_red": "#f4a99f",
    "tint_green": "#a6e3b8",
}

# Emitted as `--it-<name>` custom properties so the stylesheet in ui.py holds no
# colour literals of its own and a palette swap is a single :root rewrite.
CSS_COLOR_KEYS = (
    "bg",
    "text_primary",
    "text_secondary",
    "text_muted",
    "text_soft",
    "text_tab",
    "overlay",
    "accent_gold",
    "accent_blue",
    "accent_red",
    "accent_green",
    "accent_lavender",
    "accent_peach",
    "tint_gold",
    "tint_blue",
    "tint_blue_soft",
    "tint_red",
    "tint_green",
)

# Also emitted as bare `R, G, B` triples, because these are used through
# rgba(var(--it-x-rgb), <alpha>) for washes, borders and glows.
CSS_RGB_KEYS = (
    "bg",
    "overlay",
    "accent_gold",
    "accent_blue",
    "accent_red",
    "accent_green",
    "accent_lavender",
)


def _rgb_triple(hex_colour: str) -> str:
    value = hex_colour.lstrip("#")
    return ", ".join(str(int(value[index : index + 2], 16)) for index in (0, 2, 4))


def css_variables(colors: dict[str, str] | None = None) -> str:
    """Render the active palette as a `:root` block of `--it-*` properties."""
    palette = colors if colors is not None else COLORS
    lines = [f"    --it-{key.replace('_', '-')}: {palette[key]};" for key in CSS_COLOR_KEYS]
    lines += [
        f"    --it-{key.replace('_', '-')}-rgb: {_rgb_triple(palette[key])};"
        for key in CSS_RGB_KEYS
    ]
    body = "\n".join(lines)
    return f":root {{\n{body}\n}}"


CHART_CYCLE = [
    COLORS["accent_gold"],
    COLORS["accent_blue"],
    COLORS["accent_lavender"],
    COLORS["accent_red"],
    COLORS["accent_mint"],
    COLORS["accent_peach"],
]

ARCHETYPE_COLORS = {
    "Strength": COLORS["accent_gold"],
    "Hypertrophy": COLORS["accent_blue"],
    "Pump": COLORS["accent_lavender"],
    "Quick": COLORS["accent_peach"],
    "Mixed": COLORS["accent_mint"],
}

PLATEAU_COLORS = {
    "fresh_pr": COLORS["accent_gold"],
    "progressing": COLORS["accent_green"],
    "plateaued": COLORS["accent_peach"],
    "regressing": COLORS["accent_red"],
}


def _build_template() -> go.layout.Template:
    return go.layout.Template(
        layout=dict(
            font=dict(family="Inter Tight, system-ui, sans-serif", color=COLORS["text_primary"], size=13),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            colorway=CHART_CYCLE,
            xaxis=dict(
                gridcolor=COLORS["border"],
                linecolor=COLORS["border"],
                zerolinecolor=COLORS["border"],
                tickfont=dict(family="JetBrains Mono, monospace", size=11, color=COLORS["text_secondary"]),
                title=dict(font=dict(size=12, color=COLORS["text_secondary"])),
            ),
            yaxis=dict(
                gridcolor=COLORS["border"],
                linecolor=COLORS["border"],
                zerolinecolor=COLORS["border"],
                tickfont=dict(family="JetBrains Mono, monospace", size=11, color=COLORS["text_secondary"]),
                title=dict(font=dict(size=12, color=COLORS["text_secondary"])),
            ),
            margin=dict(l=24, r=24, t=48, b=48),
            hoverlabel=dict(
                bgcolor=COLORS["bg"],
                bordercolor=COLORS["border_strong"],
                font=dict(family="JetBrains Mono, monospace", color=COLORS["text_primary"], size=12),
            ),
            legend=dict(
                bgcolor="rgba(0,0,0,0)",
                font=dict(color=COLORS["text_secondary"], size=11),
                orientation="h",
                yanchor="bottom",
                y=-0.22,
            ),
            polar=dict(
                bgcolor="rgba(0,0,0,0)",
                radialaxis=dict(
                    gridcolor=COLORS["border"],
                    linecolor=COLORS["border"],
                    tickfont=dict(family="JetBrains Mono, monospace", size=10),
                ),
                angularaxis=dict(
                    gridcolor=COLORS["border"],
                    linecolor=COLORS["border"],
                    tickfont=dict(family="Inter Tight, sans-serif", size=11, color=COLORS["text_primary"]),
                ),
            ),
        )
    )


def register_template() -> None:
    pio.templates["irontrail"] = _build_template()
    pio.templates.default = "irontrail"


register_template()
