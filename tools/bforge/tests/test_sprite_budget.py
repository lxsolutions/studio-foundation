"""Pure boundary tests for the render.sprite resource preflight."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
sys.path.insert(0, str(RUNTIME))

from lib import sprite_budget  # noqa: E402


class SpriteBudget(unittest.TestCase):
    def test_documented_exact_work_boundary_is_accepted(self):
        plan = sprite_budget.plan_sprite_request(
            size=512,
            supersample=2,
            views=16,
            samples=96,
        )

        self.assertEqual(plan["budget"]["sheet_px"], [2048, 2048])
        self.assertEqual(plan["budget"]["pixel_work"], sprite_budget.MAX_PIXEL_WORK)
        self.assertLessEqual(
            plan["budget"]["working_set_bytes"],
            sprite_budget.MAX_WORKING_SET_BYTES,
        )

    def test_one_sample_over_exact_work_boundary_is_rejected(self):
        with self.assertRaisesRegex(
            sprite_budget.SpriteBudgetError,
            r"aggregate work .* exceeds .* pixel-work units",
        ):
            sprite_budget.plan_sprite_request(
                size=512,
                supersample=2,
                views=16,
                samples=97,
            )

    def test_samples_are_bounded_to_eight_through_256(self):
        low = sprite_budget.plan_sprite_request(32, 1, 1, 1)
        high = sprite_budget.plan_sprite_request(32, 1, 1, 999_999)
        self.assertEqual(low["samples"], sprite_budget.MIN_SAMPLES)
        self.assertEqual(high["samples"], sprite_budget.MAX_SAMPLES)

    def test_frame_and_post_buffer_cap_is_enforced(self):
        with self.assertRaisesRegex(
            sprite_budget.SpriteBudgetError,
            r"estimated float buffers .* exceed 512 MiB",
        ):
            sprite_budget.plan_sprite_request(
                size=2048,
                supersample=1,
                views=1,
                samples=8,
            )


if __name__ == "__main__":
    unittest.main()
