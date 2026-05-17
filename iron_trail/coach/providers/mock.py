"""Deterministic mock provider for dev / tests.

Returns canned responses keyed on the first 60 characters of the system
prompt so different review-kinds produce noticeably different stubs.
"""
from __future__ import annotations

from . import Message


_WEEKLY_STUB = """\
## This Week

Solid week overall. Volume held steady and you didn't miss any planned
sessions — that's the first thing worth noting.

## What Stood Out

The bench session on Monday was the highlight. Your top set held form
through all working reps, and the overall session efficiency was a clear
step up from the previous week.

## Watchouts

A couple of pull-side movements drifted lower in volume. Not a red flag,
but worth a deliberate top-up next week if you're feeling the imbalance
in posture or shoulder mobility.

## Suggestions

- Aim for one extra rowing variant next week to top up the pull side.
- Keep the same heavy day for bench — momentum is good.
- Take an honest look at sleep, because the late-evening sessions often
  correlate with lower top sets the day after.

*(mock provider — install COACH_LLM=real for the actual Copilot response.)*
"""


_MONTHLY_STUB = """\
## The Month In One Line

A consistent month. The work was there. The shape of it shifted slightly
toward hypertrophy without you planning it that way.

## Trajectory

Estimated 1RM trends crept upward on the main lifts. Nothing dramatic,
but the curve is the right direction.

## Distribution

Push and pull volume held a healthy ratio. Single-leg and core work were
the soft spots — they often are; flagging them so you can decide if you
care.

## Looking Ahead

Pick one weak movement pattern, run it for four weeks at higher
frequency, then re-evaluate. The dashboard will catch the shift if it's
real.

*(mock provider — install COACH_LLM=real for the actual Copilot response.)*
"""


class MockProvider:
    name = "mock"

    def chat(self, messages: list[Message], *, timeout: float = 120.0) -> str:
        sys_prompt = next((m.content for m in messages if m.role == "system"), "")
        if "monthly" in sys_prompt.lower():
            return _MONTHLY_STUB
        return _WEEKLY_STUB
