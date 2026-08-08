from __future__ import annotations

from copy import deepcopy
import unittest

from planning.roadmap.roadmap import RoadmapError, build_roadmap, render_html


def issue(number, sequence, blockers, *, lane="Platform/deployment"):
    blocked = "- None — can start immediately." if not blockers else "\n".join(
        f"- #{blocker}" for blocker in blockers
    )
    body = f"""## Parent

- #7

## What to build

Deliver ticket {sequence} through the complete user-facing seam.

## Acceptance criteria

- [ ] It works.

## Execution metadata

- Sequence: {sequence}
- Primary lane: {lane}
- Target start: 2026-08-07T1{sequence}:00:00-05:00
- Target end: 2026-08-07T1{sequence}:30:00-05:00
- Integration gate: Test gate
- Contingency classification: Never cut
- Recommended model: `gpt-5.6-luna`
- Reasoning effort: `xhigh`

## Blocked by

{blocked}
"""
    return {
        "number": number,
        "title": f"Ticket {sequence}",
        "body": body,
        "state": "OPEN",
        "assignees": [],
        "labels": [{"name": "ready-for-agent"}],
        "url": f"https://github.com/example/project/issues/{number}",
    }


def build(issues, blockers):
    return build_roadmap(
        issues,
        blockers,
        spec_number=7,
        repository="example/project",
        generated_at="2026-08-07T17:00:00+00:00",
    )


class RoadmapTests(unittest.TestCase):
    def test_build_roadmap_is_deterministic_and_computes_frontier_and_dependents(self):
        issues = [issue(8, 1, []), issue(9, 2, [8], lane="Spark/data")]
        blockers = {8: [], 9: [8]}

        first = build(issues, blockers)
        second = build(deepcopy(issues), deepcopy(blockers))

        self.assertEqual(first, second)
        self.assertEqual(first["frontier"], [8])
        self.assertEqual(first["critical_path"], [8, 9])
        self.assertEqual(first["tickets"][0]["dependents"], [9])
        self.assertEqual(first["tickets"][1]["blockers"], [8])

    def test_build_roadmap_rejects_missing_metadata(self):
        broken = issue(8, 1, [])
        broken["body"] = broken["body"].replace(
            "- Recommended model: `gpt-5.6-luna`\n", ""
        )

        with self.assertRaisesRegex(RoadmapError, "recommended model"):
            build([broken], {8: []})

    def test_build_roadmap_rejects_text_and_native_dependency_mismatch(self):
        with self.assertRaisesRegex(RoadmapError, "dependency mismatch"):
            build([issue(8, 1, []), issue(9, 2, [8])], {8: [], 9: []})

    def test_build_roadmap_rejects_dependency_cycles(self):
        first = issue(8, 1, [9])
        second = issue(9, 2, [8])

        with self.assertRaisesRegex(RoadmapError, "cycle"):
            build([first, second], {8: [9], 9: [8]})

    def test_render_html_embeds_snapshot_without_live_fetch(self):
        roadmap = build([issue(8, 1, [])], {8: []})
        rendered = render_html(
            '<script id="roadmap-data" type="application/json">{{ROADMAP_JSON}}</script>',
            roadmap,
        )

        self.assertIn('"frontier":[8]', rendered)
        self.assertNotIn("{{ROADMAP_JSON}}", rendered)
        self.assertNotIn("fetch(", rendered)


if __name__ == "__main__":
    unittest.main()
