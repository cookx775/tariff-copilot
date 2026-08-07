# Issue tracker: GitHub

Issues and planning artifacts for this repository live in GitHub Issues for `cookx775/tariff-copilot`. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue:** `gh issue create --title "..." --body "..."`.
- **Read an issue:** `gh issue view <number> --comments`, including its labels.
- **List issues:** `gh issue list --state open --json number,title,body,labels,comments` with appropriate label and state filters.
- **Comment on an issue:** `gh issue comment <number> --body "..."`.
- **Apply or remove labels:** `gh issue edit <number> --add-label "..."` or `--remove-label "..."`.
- **Close an issue:** `gh issue close <number> --comment "..."`.

Run commands inside this repository so `gh` infers `cookx775/tariff-copilot` from the Git remote.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## Publishing and fetching

- When a skill says to publish to the issue tracker, create a GitHub issue.
- When a skill says to fetch a ticket, run `gh issue view <number> --comments`.

## Wayfinding operations

The map is one parent issue and its decision tickets are child issues.

- **Map:** Create one issue labelled `wayfinder:map`. Its body holds Destination, Notes, Decisions so far, Not yet specified, and Out of scope.
- **Child ticket:** Link each ticket to the map as a GitHub sub-issue using the GitHub API. If sub-issues are unavailable, add the child to a task list in the map and put `Part of #<map>` at the top of the child body.
- **Ticket labels:** Apply exactly one of `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task`.
- **Blocking:** Use GitHub's native issue dependencies. Add an edge with `gh api --method POST repos/cookx775/tariff-copilot/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-database-id>`. Obtain the blocker database ID with `gh api repos/cookx775/tariff-copilot/issues/<number> --jq .id`. If dependencies are unavailable, put `Blocked by: #<number>` at the top of the child body.
- **Frontier:** List the map's open children, then exclude tickets with an open blocker or an assignee. The first remaining ticket in map order is the next frontier ticket.
- **Claim:** Assign the ticket before doing any work with `gh issue edit <number> --add-assignee @me`.
- **Resolve:** Post the answer as a resolution comment, close the ticket, and append a linked one-line gist to the map's Decisions so far section.

GitHub issue and pull-request numbers share one number space. When a bare number is ambiguous, check whether it is a pull request before treating it as an issue.
