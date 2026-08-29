## A note from Sankalp

I like ambitious ideas, simple systems, and software that feels obvious. Do not preserve complexity just because it already exists. Do not introduce machinery because it looks architecturally impressive. Understand the real constraint, then fight for the smallest model that makes the correct behavior unsurprising.

## Workflow

- **Push clean code to GitHub after each subphase** — never leave work unpushed across a subphase boundary.

## Available tooling

- **GitHub** — hosting, commits, PRs, and review comments (CodeRabbit + Copilot feedback arrives here).
- **Entire CLI** — enabled in this repo; tracks agent sessions as checkpoints with extra context and timing.
  - Run an `entire` command when you need to know what happened earlier or how much time was spent.

## Taste

- Complexity belongs at the adapter boundary. Orchestration stays pure, UI stays dumb.
- Comments describe how a thing is used, and move when the code moves. To be used mostly to describe functions, not to annotate every line of behavior.
- If a rule here fights the task in front of you, say so loudly and get a human sign-off before breaking it.
