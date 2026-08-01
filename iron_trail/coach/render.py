"""Markdown rendering for weekly / monthly reviews.

The renderer composes:

1. YAML frontmatter (programmatic, queryable)
2. A "Stats" section with numbers from the summary dict (never the LLM)
3. The LLM-written "Reflections" body
4. A small footer with provenance

This separation is the hallucination guard — numeric facts always come
from the structured summary, the LLM only writes prose around them.
"""
from __future__ import annotations

import html
from datetime import datetime
from typing import Any


def _safe(value: Any) -> str:
    """Neutralise raw HTML in a user-controlled string.

    Exercise and workout names come straight from an uploaded CSV. They land in
    Markdown that is rendered to a PDF (python-markdown passes raw HTML
    through), written into vault notes, and shown in the app, so a name like
    ``<img src="http://attacker/x">`` would otherwise become a live tag.
    Escaping here keeps it visible as text everywhere.
    """
    return html.escape(str(value), quote=False)


def _yaml_frontmatter(data: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in data.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        elif isinstance(v, str):
            if any(ch in v for ch in ":#"):
                lines.append(f'{k}: "{v}"')
            else:
                lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _fmt_kg(v: float) -> str:
    return f"{v:,.0f} kg"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def _fmt_delta_kg(v: float | None) -> str:
    if v is None:
        return "n/a"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f} kg"


def _stats_block_weekly(summary: dict) -> str:
    lines = ["## Stats", ""]
    lines.append(f"- **Week:** {summary['week_label']} "
                 f"({summary['week_start']} → {summary['week_end']})")
    lines.append(f"- **Sessions:** {summary['session_count']}")
    lines.append(f"- **Total tonnage:** {_fmt_kg(summary['total_volume_kg'])}"
                 + (f"  ({_fmt_pct(summary['volume_delta_pct'])} vs prior week)"
                    if summary.get("volume_delta_pct") is not None else ""))
    hours = summary["training_minutes"] / 60
    lines.append(f"- **Training time:** {hours:.1f} h")
    lines.append(f"- **Current streak:** {summary['current_streak_days']} d "
                 f"(longest ever: {summary['longest_streak_days']} d)")
    if summary.get("push_pull_ratio") is not None:
        lines.append(f"- **Push:Pull ratio:** {summary['push_pull_ratio']:.2f}")
    if summary.get("archetype_mix"):
        mix = " · ".join(f"{k} {v}" for k, v in summary["archetype_mix"].items())
        lines.append(f"- **Archetype mix:** {mix}")

    # Top lifts
    if summary.get("exercise_top_e1rm"):
        lines.append("")
        lines.append("**Top lifts this week (e1RM):**")
        lines.append("")
        for entry in summary["exercise_top_e1rm"][:8]:
            line = f"- {_safe(entry['exercise'])} — {entry['e1rm_kg']:.1f} kg"
            if entry.get("delta_kg") is not None:
                line += f"  ({_fmt_delta_kg(entry['delta_kg'])} vs prior week)"
            lines.append(line)

    # Plateau callouts (max 5 to keep the block tidy)
    plateaus = summary.get("plateau_callouts") or []
    if plateaus:
        lines.append("")
        lines.append("**Plateau watch:**")
        lines.append("")
        for p in plateaus[:5]:
            lines.append(
                f"- _{_safe(p['status'])}_ — {_safe(p['exercise'])} "
                f"(current {p['current_e1rm_kg']:.1f} kg / peak {p['peak_e1rm_kg']:.1f} kg, "
                f"{p['days_since_pr']} d since PR)"
            )

    return "\n".join(lines)


def _stats_block_monthly(summary: dict) -> str:
    lines = ["## Stats", ""]
    lines.append(f"- **Month:** {summary['month_label']} "
                 f"({summary['month_start']} → {summary['month_end']})")
    lines.append(f"- **Sessions:** {summary['session_count']}")
    lines.append(f"- **Total tonnage:** {_fmt_kg(summary['total_volume_kg'])}")
    hours = summary["training_minutes"] / 60
    lines.append(f"- **Training time:** {hours:.1f} h")
    if summary.get("archetype_mix"):
        mix = " · ".join(f"{k} {v}" for k, v in summary["archetype_mix"].items())
        lines.append(f"- **Archetype mix:** {mix}")

    if summary.get("trajectory"):
        lines.append("")
        lines.append("**Strength trajectory (4-week change):**")
        lines.append("")
        for t in summary["trajectory"][:10]:
            ch = t["change_kg"]
            sign = "+" if ch >= 0 else ""
            lines.append(
                f"- {_safe(t['exercise'])} — {t['start_e1rm_kg']:.1f} kg → "
                f"{t['end_e1rm_kg']:.1f} kg  ({sign}{ch:.1f} kg)"
            )

    plateaus = summary.get("plateau_callouts") or []
    if plateaus:
        lines.append("")
        lines.append("**Plateau watch:**")
        lines.append("")
        for p in plateaus[:5]:
            lines.append(
                f"- _{_safe(p['status'])}_ — {_safe(p['exercise'])} "
                f"(current {p['current_e1rm_kg']:.1f} kg / peak {p['peak_e1rm_kg']:.1f} kg)"
            )

    return "\n".join(lines)


def weekly_review_md(summary: dict, llm_body: str, *, personality: str = "default") -> str:
    fm = _yaml_frontmatter({
        "title": f"\"Weekly Review · {summary['week_label']}\"",
        "kind": "weekly",
        "week_label": summary["week_label"],
        "week_start": summary["week_start"],
        "week_end": summary["week_end"],
        "session_count": summary["session_count"],
        "total_volume_kg": int(summary["total_volume_kg"]),
        "push_pull_ratio": (
            f"{summary['push_pull_ratio']:.2f}"
            if summary.get("push_pull_ratio") is not None else "null"
        ),
        "personality": personality,
        "tags": ["hevy/review", "hevy/weekly"],
    })
    parts = [
        fm,
        "",
        f"# Weekly Review — {summary['week_label']}",
        "",
        f"_{summary['week_start']} → {summary['week_end']}_",
        "",
        _stats_block_weekly(summary),
        "",
        "## Reflections",
        "",
        llm_body.strip(),
        "",
        "---",
        f"*Generated by IronTrail on {datetime.now():%Y-%m-%d %H:%M} · personality `{personality}`*",
        "",
    ]
    return "\n".join(parts)


def monthly_review_md(summary: dict, llm_body: str, *, personality: str = "default") -> str:
    fm = _yaml_frontmatter({
        "title": f"\"Monthly Recap · {summary['month_label']}\"",
        "kind": "monthly",
        "month_label": summary["month_label"],
        "month_start": summary["month_start"],
        "month_end": summary["month_end"],
        "session_count": summary["session_count"],
        "total_volume_kg": int(summary["total_volume_kg"]),
        "personality": personality,
        "tags": ["hevy/review", "hevy/monthly"],
    })
    parts = [
        fm,
        "",
        f"# Monthly Recap — {summary['month_label']}",
        "",
        f"_{summary['month_start']} → {summary['month_end']}_",
        "",
        _stats_block_monthly(summary),
        "",
        "## Reflections",
        "",
        llm_body.strip(),
        "",
        "---",
        f"*Generated by IronTrail on {datetime.now():%Y-%m-%d %H:%M} · personality `{personality}`*",
        "",
    ]
    return "\n".join(parts)
