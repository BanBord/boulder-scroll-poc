# src/balance.py
from collections import deque
import numpy as np
from typing import Dict

_VARIANCE_WINDOW = 30
_VARIANCE_UNSTABLE = 8.0
_FALLEN_SPEED = 40.0
_FALLEN_CONF = 0.15

_PARAMS = {
    "stable":   (0.08, 0.85),
    "unstable": (0.15, 0.55),
    "fallen":   (0.00, 0.97),
}


class PhysicsState:
    def __init__(self, panel_cx: int, panel_half: int):
        self._cx = float(panel_cx)
        self._half = float(panel_half)

        self.arm_pos = self._cx;  self.arm_vel = 0.0
        self.leg_pos = self._cx;  self.leg_vel = 0.0
        self.com_pos = self._cx;  self.com_vel = 0.0

        self._state = "stable"
        self._var_window: deque = deque(maxlen=_VARIANCE_WINDOW)

    def update(
        self,
        arm_target: float,
        leg_target: float,
        com_target: float,
        is_fallen: bool = False,
    ) -> None:
        self._var_window.append(com_target)
        variance = float(np.std(self._var_window)) if len(self._var_window) >= 5 else 0.0

        if is_fallen:
            self._state = "fallen"
        elif self._state != "fallen":
            self._state = "unstable" if variance >= _VARIANCE_UNSTABLE else "stable"

        stiffness, decay = _PARAMS[self._state]

        def _step(pos: float, vel: float, target: float):
            vel = vel * decay + (target - pos) * stiffness
            pos = pos + vel
            return pos, vel

        self.arm_pos, self.arm_vel = _step(self.arm_pos, self.arm_vel, arm_target)
        self.leg_pos, self.leg_vel = _step(self.leg_pos, self.leg_vel, leg_target)
        self.com_pos, self.com_vel = _step(self.com_pos, self.com_vel, com_target)

    def get_positions(self) -> Dict:
        return {
            "arm":   self.arm_pos,
            "leg":   self.leg_pos,
            "com":   self.com_pos,
            "state": self._state,
        }
