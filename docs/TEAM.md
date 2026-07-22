# How this project is built

This project is developed by a human orchestrator directing a set of **AI
coding agents**, each with a defined role, working a normal software team's
workflow: feature branches, pull requests, code review, and issue tracking.

This is stated openly. The agents are AI, not people. Nothing here impersonates
a real person, backdates history, or hides how the work was produced. The point
is the opposite — to show a real, reviewable engineering process.

## Roles

| Agent | Responsibility |
|-------|----------------|
| **agentapp-backend** | FastAPI service, agent pipeline stages, data model, migrations |
| **agentapp-frontend** | Next.js app, UI, API client |
| **agentapp-reviewer** | Reviews each pull request before merge, flags correctness and security issues |
| **Orchestrator** (human) | Sets direction, decides scope, reviews and merges, owns product decisions |

Each commit names the agent that produced the work in a `Co-Authored-By`
trailer. The human orchestrator is the commit author and merges the pull
requests.

## Workflow

1. A stage of work gets a GitHub issue describing the goal.
2. Work happens on a `feat/<stage>` branch, committed with the responsible
   agent as co-author.
3. A pull request opens against `main`, linked to the issue.
4. The reviewer agent posts a review; the orchestrator addresses feedback.
5. The orchestrator merges once the review passes and checks are green.

## Why this way

Code review and small, scoped pull requests catch defects earlier than one
large drop, and leave a clear record of why each change was made. Running AI
agents inside that same discipline keeps the speed of AI assistance without
giving up the review trail a real team relies on.
