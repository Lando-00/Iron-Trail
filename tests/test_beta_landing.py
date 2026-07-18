from __future__ import annotations

from datetime import UTC, datetime, timedelta

from iron_trail import beta_landing


NOW = datetime(2026, 7, 18, 15, 0, tzinfo=UTC)


def test_target_is_deterministic_and_private_seeded() -> None:
    first = beta_landing.resolve_target({"IRONTRAIL_BETA_REVEAL_SEED": "first"})
    repeated = beta_landing.resolve_target({"IRONTRAIL_BETA_REVEAL_SEED": "first"})
    second = beta_landing.resolve_target({"IRONTRAIL_BETA_REVEAL_SEED": "second"})

    assert first == repeated
    assert first != second
    assert 0 <= first.emoji_index < len(beta_landing.EMOJIS)
    assert first.control_key in beta_landing.CONTROL_KEYS


def test_emoji_changes_on_every_activation_and_resets_hits() -> None:
    state = beta_landing.RevealState(emoji_index=4, control_hits=3)

    changed = beta_landing.cycle_emoji(state, NOW)

    assert changed.emoji_index == 0
    assert changed.control_hits == 0
    assert changed.updated_at == NOW


def test_reveal_requires_target_emoji_and_five_target_control_hits() -> None:
    target = beta_landing.RevealTarget(emoji_index=2, control_key="orbit")
    state = beta_landing.RevealState(emoji_index=2)

    for expected_hits in range(1, beta_landing.REQUIRED_CONTROL_HITS + 1):
        state = beta_landing.activate_control(state, "orbit", target, NOW)
        assert state.control_hits == expected_hits
        assert state.revealed is (
            expected_hits >= beta_landing.REQUIRED_CONTROL_HITS
        )


def test_wrong_control_or_emoji_resets_progress() -> None:
    target = beta_landing.RevealTarget(emoji_index=2, control_key="orbit")
    state = beta_landing.RevealState(emoji_index=2, control_hits=4)

    wrong_control = beta_landing.activate_control(state, "signal", target, NOW)
    wrong_emoji = beta_landing.activate_control(
        beta_landing.RevealState(emoji_index=1, control_hits=4),
        "orbit",
        target,
        NOW,
    )

    assert wrong_control.control_hits == 0
    assert not wrong_control.revealed
    assert wrong_emoji.control_hits == 0
    assert not wrong_emoji.revealed


def test_expired_sequence_resets_before_next_action() -> None:
    target = beta_landing.RevealTarget(emoji_index=2, control_key="orbit")
    expired = beta_landing.RevealState(
        emoji_index=2,
        control_hits=4,
        updated_at=NOW - beta_landing.REVEAL_TIMEOUT - timedelta(seconds=1),
    )

    next_state = beta_landing.activate_control(expired, "orbit", target, NOW)

    assert next_state.emoji_index == 0
    assert next_state.control_hits == 0
    assert not next_state.revealed


def test_reset_removes_only_reveal_widget_state() -> None:
    session_state = {
        "beta_reveal_state": beta_landing.RevealState(revealed=True),
        "beta_reveal_emoji_button": True,
        "beta_reveal_control_signal": True,
        "other": "preserve",
    }

    beta_landing.reset_session_state(session_state)

    assert session_state == {"other": "preserve"}
