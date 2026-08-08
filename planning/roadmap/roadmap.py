from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


LANES = [
    "Platform/deployment",
    "Spark/data",
    "Retrieval/agent",
    "Domain/repository/tests",
    "Frontend",
    "Documentation/demo readiness",
]

REQUIRED_METADATA = {
    "sequence",
    "primary lane",
    "target start",
    "target end",
    "integration gate",
    "contingency classification",
    "recommended model",
    "reasoning effort",
}

ALLOWED_MODELS = {
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
}

ALLOWED_REASONING = {"low", "medium", "high", "xhigh", "max"}

GATES = [
    {
        "label": "Friday platform verification",
        "at": "2026-08-07T18:30:00-05:00",
        "kind": "gate",
    },
    {
        "label": "Saturday integrated slice",
        "at": "2026-08-08T23:00:00-05:00",
        "kind": "gate",
    },
    {
        "label": "Sunday complete frontend",
        "at": "2026-08-09T12:00:00-05:00",
        "kind": "gate",
    },
    {
        "label": "Feature freeze",
        "at": "2026-08-09T13:00:00-05:00",
        "kind": "freeze",
    },
    {
        "label": "Internal submission target",
        "at": "2026-08-09T20:00:00-05:00",
        "kind": "target",
    },
    {
        "label": "Official deadline · 10 PM PT",
        "at": "2026-08-10T00:00:00-05:00",
        "kind": "deadline",
    },
]

CONTINGENCY_CUTS = [
    "Remove the negative notice from the live demo; retain its automated test.",
    "Remove simulated-failure UI controls; retain real failure handling and tests.",
    "Collapse expanded Analysis & Action History; retain persisted audit events.",
    "Remove the read-only Sourcing Reviews index; retain direct Review detail.",
    "Use generated confirmation defaults instead of editable objective and owner.",
    "Remove live USITC ingestion and broad notice coverage; retain pinned classifications and one live Federal Register path.",
    "Remove successor-analysis UI; retain immutable snapshot records.",
]

PARENT_PATTERN = re.compile(r"(?m)^-\s+#(?P<number>\d+)\s*$")
ISSUE_REF_PATTERN = re.compile(r"#(?P<number>\d+)")
METADATA_PATTERN = re.compile(r"(?m)^-\s+([^:]+):\s*(.+?)\s*$")


class RoadmapError(ValueError):
    """Raised when issue data cannot form a safe roadmap."""


def section(body: str, heading: str) -> str:
    pattern = re.compile(
        rf"(?ms)^##\s+{re.escape(heading)}\s*\n(?P<content>.*?)(?=^##\s+|\Z)"
    )
    match = pattern.search(body)
    return match.group("content").strip() if match else ""


def parse_parent(body: str) -> int | None:
    content = section(body, "Parent")
    match = PARENT_PATTERN.search(content)
    return int(match.group("number")) if match else None


def parse_metadata(body: str) -> dict[str, str]:
    content = section(body, "Execution metadata")
    metadata = {
        key.strip().lower(): value.strip().strip("`")
        for key, value in METADATA_PATTERN.findall(content)
    }
    missing = sorted(REQUIRED_METADATA - metadata.keys())
    if missing:
        raise RoadmapError(f"Missing execution metadata: {', '.join(missing)}")
    return metadata


def parse_blocker_references(body: str) -> list[int]:
    content = section(body, "Blocked by")
    if not content or "None — can start immediately" in content:
        return []
    return sorted({int(match.group("number")) for match in ISSUE_REF_PATTERN.finditer(content)})


def acceptance_summary(body: str) -> str:
    content = section(body, "What to build")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    if not paragraphs:
        raise RoadmapError("Missing What to build summary")
    return re.sub(r"\s+", " ", paragraphs[0])


def parse_datetime(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise RoadmapError(f"Invalid {label}: {value}") from error
    if parsed.tzinfo is None:
        raise RoadmapError(f"{label} must include a timezone: {value}")
    return parsed


def normalize_issue(
    issue: Mapping[str, Any],
    native_blockers: Sequence[int],
) -> dict[str, Any]:
    body = str(issue.get("body") or "")
    metadata = parse_metadata(body)
    number = int(issue["number"])
    text_blockers = parse_blocker_references(body)
    native_blockers = sorted({int(value) for value in native_blockers})
    if text_blockers != native_blockers:
        raise RoadmapError(
            f"Issue #{number} dependency mismatch: body={text_blockers}, native={native_blockers}"
        )

    lane = metadata["primary lane"]
    if lane not in LANES:
        raise RoadmapError(f"Issue #{number} has unsupported lane: {lane}")
    model = metadata["recommended model"]
    if model not in ALLOWED_MODELS:
        raise RoadmapError(f"Issue #{number} has unsupported model: {model}")
    reasoning = metadata["reasoning effort"].lower()
    if reasoning not in ALLOWED_REASONING:
        raise RoadmapError(f"Issue #{number} has unsupported reasoning effort: {reasoning}")

    start = parse_datetime(metadata["target start"], "target start")
    end = parse_datetime(metadata["target end"], "target end")
    if start >= end:
        raise RoadmapError(f"Issue #{number} target start must precede target end")

    assignees = issue.get("assignees") or []
    labels = issue.get("labels") or []
    return {
        "number": number,
        "sequence": int(metadata["sequence"]),
        "title": str(issue["title"]),
        "url": str(issue["url"]),
        "state": str(issue["state"]).lower(),
        "assignees": sorted(
            item.get("login", "") if isinstance(item, Mapping) else str(item)
            for item in assignees
            if item
        ),
        "labels": sorted(
            item.get("name", "") if isinstance(item, Mapping) else str(item)
            for item in labels
            if item
        ),
        "lane": lane,
        "target_start": start.isoformat(),
        "target_end": end.isoformat(),
        "gate": metadata["integration gate"],
        "contingency": metadata["contingency classification"],
        "model": model,
        "reasoning_effort": reasoning,
        "prior_art": metadata.get("prior art", ""),
        "parallel_safe_with": metadata.get("parallel-safe with", ""),
        "summary": acceptance_summary(body),
        "blockers": native_blockers,
        "dependents": [],
    }


def validate_sequences(tickets: Sequence[Mapping[str, Any]]) -> None:
    sequences = sorted(int(ticket["sequence"]) for ticket in tickets)
    expected = list(range(1, len(tickets) + 1))
    if sequences != expected:
        raise RoadmapError(f"Ticket sequences must be contiguous: {sequences}")


def topological_order(tickets: Sequence[Mapping[str, Any]]) -> list[int]:
    ticket_numbers = {int(ticket["number"]) for ticket in tickets}
    indegree = {number: 0 for number in ticket_numbers}
    children: dict[int, list[int]] = defaultdict(list)
    sequence = {int(ticket["number"]): int(ticket["sequence"]) for ticket in tickets}

    for ticket in tickets:
        child = int(ticket["number"])
        for blocker in ticket["blockers"]:
            if blocker not in ticket_numbers:
                raise RoadmapError(f"Issue #{child} references unknown blocker #{blocker}")
            children[blocker].append(child)
            indegree[child] += 1

    ready = deque(sorted((number for number, degree in indegree.items() if degree == 0), key=sequence.get))
    ordered: list[int] = []
    while ready:
        number = ready.popleft()
        ordered.append(number)
        for child in sorted(children[number], key=sequence.get):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)

    if len(ordered) != len(ticket_numbers):
        raise RoadmapError("Ticket dependency graph contains a cycle")
    return ordered


def critical_path(tickets: Sequence[Mapping[str, Any]], ordered: Sequence[int]) -> list[int]:
    by_number = {int(ticket["number"]): ticket for ticket in tickets}
    children: dict[int, list[int]] = defaultdict(list)
    for ticket in tickets:
        for blocker in ticket["blockers"]:
            children[int(blocker)].append(int(ticket["number"]))

    best_score: dict[int, float] = {}
    best_path: dict[int, list[int]] = {}
    for number in reversed(ordered):
        ticket = by_number[number]
        duration = (
            datetime.fromisoformat(ticket["target_end"])
            - datetime.fromisoformat(ticket["target_start"])
        ).total_seconds() / 3600
        options = sorted(children[number], key=lambda child: by_number[child]["sequence"])
        if not options:
            best_score[number] = duration
            best_path[number] = [number]
            continue
        selected = max(options, key=lambda child: (best_score[child], -by_number[child]["sequence"]))
        best_score[number] = duration + best_score[selected]
        best_path[number] = [number, *best_path[selected]]

    source = max(
        ordered,
        key=lambda number: (best_score[number], -by_number[number]["sequence"]),
    )
    return best_path[source]


def parallel_fronts(tickets: Sequence[Mapping[str, Any]]) -> list[list[int]]:
    grouped: dict[tuple[int, ...], list[int]] = defaultdict(list)
    for ticket in tickets:
        blockers = tuple(sorted(int(value) for value in ticket["blockers"]))
        if blockers:
            grouped[blockers].append(int(ticket["number"]))
    fronts = [
        sorted(numbers)
        for numbers in grouped.values()
        if len(numbers) > 1
    ]
    return sorted(fronts, key=lambda group: min(group))


def build_roadmap(
    raw_issues: Sequence[Mapping[str, Any]],
    blockers_by_issue: Mapping[int, Sequence[int]],
    *,
    spec_number: int,
    repository: str,
    generated_at: str,
) -> dict[str, Any]:
    generated = parse_datetime(generated_at, "generated at")
    selected = [
        issue for issue in raw_issues if parse_parent(str(issue.get("body") or "")) == spec_number
    ]
    if not selected:
        raise RoadmapError(f"No implementation tickets found for parent #{spec_number}")

    tickets = [
        normalize_issue(issue, blockers_by_issue.get(int(issue["number"]), []))
        for issue in selected
    ]
    tickets.sort(key=lambda ticket: ticket["sequence"])
    validate_sequences(tickets)
    ordered = topological_order(tickets)

    by_number = {ticket["number"]: ticket for ticket in tickets}
    for ticket in tickets:
        for blocker in ticket["blockers"]:
            by_number[blocker]["dependents"].append(ticket["number"])
    for ticket in tickets:
        ticket["dependents"].sort(key=lambda number: by_number[number]["sequence"])

    frontier = [
        ticket["number"]
        for ticket in tickets
        if ticket["state"] == "open"
        and all(by_number[blocker]["state"] == "closed" for blocker in ticket["blockers"])
    ]
    path = critical_path(tickets, ordered)

    return {
        "repository": repository,
        "spec": {
            "number": spec_number,
            "title": "Build the Tariff & Trade-Policy Exposure Copilot",
            "url": f"https://github.com/{repository}/issues/{spec_number}",
        },
        "generated_at": generated.astimezone(timezone.utc).isoformat(),
        "timezone": "America/Chicago",
        "lanes": LANES,
        "gates": GATES,
        "contingency_cuts": CONTINGENCY_CUTS,
        "tickets": tickets,
        "frontier": frontier,
        "critical_path": path,
        "parallel_fronts": parallel_fronts(tickets),
        "timeline": {
            "start": min(ticket["target_start"] for ticket in tickets),
            "end": GATES[-1]["at"],
        },
        "model_policy": {
            "default": "Use the ticket's recommended model and reasoning effort.",
            "luna_to_terra": "Escalate only for unresolved cross-system behavior, architectural misunderstanding, or repeated contract violations.",
            "terra_to_sol": "Escalate only when evidence-driven debugging cannot isolate a platform or integration failure.",
        },
    }


def run_gh(args: Sequence[str]) -> Any:
    completed = subprocess.run(
        ["gh", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def load_github_issues(repository: str) -> list[dict[str, Any]]:
    return run_gh(
        [
            "issue",
            "list",
            "--repo",
            repository,
            "--state",
            "all",
            "--label",
            "ready-for-agent",
            "--limit",
            "100",
            "--json",
            "number,title,body,state,assignees,url,labels",
        ]
    )


def load_native_blockers(repository: str, issue_numbers: Iterable[int]) -> dict[int, list[int]]:
    blockers: dict[int, list[int]] = {}
    for number in issue_numbers:
        rows = run_gh(
            ["api", f"repos/{repository}/issues/{number}/dependencies/blocked_by"]
        )
        blockers[number] = sorted(int(row["number"]) for row in rows)
    return blockers


def render_html(template: str, roadmap: Mapping[str, Any]) -> str:
    marker = "{{ROADMAP_JSON}}"
    if marker not in template:
        raise RoadmapError("Roadmap template is missing the data marker")
    encoded = json.dumps(roadmap, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    return template.replace(marker, encoded)


def write_outputs(
    output_directory: Path,
    template_path: Path,
    roadmap: Mapping[str, Any],
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(roadmap, indent=2, ensure_ascii=False) + "\n"
    template = template_path.read_text(encoding="utf-8")
    html_text = render_html(template, roadmap)
    (output_directory / "roadmap.json").write_text(json_text, encoding="utf-8")
    (output_directory / "index.html").write_text(html_text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate the Tariff Copilot delivery roadmap")
    parser.add_argument("--repo", default="cookx775/tariff-copilot")
    parser.add_argument("--spec", type=int, default=7)
    parser.add_argument(
        "--generated-at",
        default=datetime.now(timezone.utc).isoformat(),
        help="ISO timestamp; provide a fixed value for deterministic output",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(__file__).resolve().parent / "template.html",
    )
    args = parser.parse_args(argv)

    issues = load_github_issues(args.repo)
    child_numbers = [
        int(issue["number"])
        for issue in issues
        if parse_parent(str(issue.get("body") or "")) == args.spec
    ]
    blockers = load_native_blockers(args.repo, child_numbers)
    roadmap = build_roadmap(
        issues,
        blockers,
        spec_number=args.spec,
        repository=args.repo,
        generated_at=args.generated_at,
    )
    write_outputs(args.output_dir, args.template, roadmap)
    print(
        json.dumps(
            {
                "tickets": len(roadmap["tickets"]),
                "frontier": roadmap["frontier"],
                "critical_path": roadmap["critical_path"],
                "output": str(args.output_dir),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
