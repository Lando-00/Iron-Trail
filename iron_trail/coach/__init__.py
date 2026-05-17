"""iron_trail.coach — the AI Training Coach module.

Public entry points:

- ``summary.build_weekly(df, week_end)`` — structured stats dict for a week
- ``summary.build_monthly(df, month_end)`` — structured stats dict for a month
- ``prompts.weekly_review_prompt(personality)`` / ``monthly_review_prompt``
- ``providers.copilot.CopilotProvider`` / ``providers.mock.MockProvider``
- ``render.weekly_review_md(summary, llm_body)`` / ``monthly_review_md``
- ``export.vault.save_review_to_vault(md, vault_dir, week_end)``
- ``export.pdf.markdown_to_pdf(md) -> bytes``

The provider abstraction lives in ``providers/base.py``. The mock provider
returns a deterministic stub so the Streamlit page can be built end-to-end
without hitting the real LLM.
"""
