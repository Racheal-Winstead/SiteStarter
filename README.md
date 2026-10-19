# Multi-agent_tool

Private Cycle 3 project shared by Racheal Winstead and Sam H. The product scope, architecture, and implementation stack will be agreed together before building.

## Branches

- `main`: shared reviewed work; keep it runnable once implementation begins.
- `sam-h`: Sam's working branch.
- `racheal-w`: Racheal's working branch.

Branch names identify work, not access restrictions. Collaborators can access repository branches. See WORKING_AGREEMENT.md for review and coordination rules.

## First-time setup

Each person uses their own GitHub account. Sam must accept the collaborator invitation before cloning.

```sh
git clone https://github.com/Racheal-Winstead/Multi-agent_tool.git
cd Multi-agent_tool
git fetch origin
```

Racheal: `git switch --track origin/racheal-w`

Sam: `git switch --track origin/sam-h`

If the local branch already exists, use `git switch racheal-w` or `git switch sam-h` instead.

## Daily workflow

1. Agree on the task and files before starting; create an issue for shared tracking.
2. With a clean working tree, fetch updates and merge `origin/main` into your own branch. Resolve conflicts together if they affect shared behavior.
3. Make a small coherent change and run the checks appropriate to it.
4. Inspect `git diff` and `git status` before staging specific files. Commit and push your branch.
5. Open a pull request from your branch into `main` and request your partner's review.
6. Merge only after approval and passing available checks. Keep the two working branches after merging.

Do not force-push shared history. Do not commit secrets, recordings, private user data, or dependency folders. Actual run and test commands will be added when the stack is chosen; none are established yet.

## Configuration

Store local credentials in ignored `.env` or `.env.local` files, using each person's own authorized credentials. Add an `.env.example` containing names and placeholders only when configuration is defined. Share secret values through an approved secret-sharing mechanism, never a commit or pull-request comment.

## Next joint decisions

- One user problem, project scope, and agent responsibilities.
- Agent communication contracts, tools, failure handling, and human checkpoints.
- Implementation stack, setup commands, and automated checks.
- Acknowledged working agreement, task ownership, and check-in schedule.
