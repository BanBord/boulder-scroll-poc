import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.balance import PhysicsState

PANEL_CX = 270
PANEL_HALF = 220


def test_initial_positions_at_center():
    state = PhysicsState(panel_cx=PANEL_CX, panel_half=PANEL_HALF)
    pos = state.get_positions()
    assert pos["arm"] == float(PANEL_CX)
    assert pos["leg"] == float(PANEL_CX)
    assert pos["com"] == float(PANEL_CX)


def test_stable_state_moves_toward_target():
    state = PhysicsState(panel_cx=PANEL_CX, panel_half=PANEL_HALF)
    target = float(PANEL_CX + 50)
    for _ in range(60):
        state.update(arm_target=target, leg_target=target, com_target=target)
    pos = state.get_positions()
    assert abs(pos["arm"] - target) < 5.0, f"arm {pos['arm']:.1f} should be near {target}"


def test_fallen_state_does_not_pull_to_target():
    state = PhysicsState(panel_cx=PANEL_CX, panel_half=PANEL_HALF)
    for _ in range(10):
        state.update(arm_target=float(PANEL_CX + 80), leg_target=float(PANEL_CX),
                     com_target=float(PANEL_CX))
    arm_before = state.get_positions()["arm"]
    for _ in range(5):
        state.update(arm_target=float(PANEL_CX), leg_target=float(PANEL_CX),
                     com_target=float(PANEL_CX), is_fallen=True)
    arm_after = state.get_positions()["arm"]
    assert arm_after > PANEL_CX + 5, f"arm {arm_after:.1f} should still be right of center"


def test_state_transitions():
    state = PhysicsState(panel_cx=PANEL_CX, panel_half=PANEL_HALF)
    pos = state.get_positions()
    assert pos["state"] == "stable"

    import random
    random.seed(42)
    for _ in range(35):
        noisy = float(PANEL_CX + random.uniform(-30, 30))
        state.update(arm_target=noisy, leg_target=noisy, com_target=noisy)
    pos = state.get_positions()
    assert pos["state"] in ("unstable", "stable")

    state.update(arm_target=float(PANEL_CX), leg_target=float(PANEL_CX),
                 com_target=float(PANEL_CX), is_fallen=True)
    assert state.get_positions()["state"] == "fallen"
