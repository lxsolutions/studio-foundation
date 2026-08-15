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
        budget = plan["budget"]

        self.assertEqual(budget["sheet_px"], [2048, 2048])
        self.assertEqual(budget["pixel_work"], sprite_budget.MAX_PIXEL_WORK)
        self.assertEqual(budget["save_buffer_bytes"], 416 * 1024 * 1024)
        self.assertEqual(budget["save_phase_bytes"], 456 * 1024 * 1024)
        self.assertEqual(budget["working_set_bytes"], budget["save_phase_bytes"])
        self.assertLessEqual(
            budget["working_set_bytes"],
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

    def test_adjacent_frame_sizes_straddle_the_memory_cap(self):
        accepted = sprite_budget.plan_sprite_request(
            size=560,
            supersample=1,
            views=16,
            samples=8,
        )
        self.assertEqual(accepted["budget"]["working_set_bytes"], 535_314_432)
        self.assertLessEqual(
            accepted["budget"]["working_set_bytes"],
            sprite_budget.MAX_WORKING_SET_BYTES,
        )

        with self.assertRaisesRegex(
            sprite_budget.SpriteBudgetError,
            r"estimated working set 512\.2 MiB exceed 512 MiB",
        ):
            sprite_budget.plan_sprite_request(
                size=561,
                supersample=1,
                views=16,
                samples=8,
            )


if __name__ == "__main__":
    unittest.main()
