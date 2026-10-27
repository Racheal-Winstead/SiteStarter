# SiteStarter

SiteStarter turns a short, everyday description from a small-business owner or individual with little or no coding experience into a single-page website draft: a content agent and a design agent plan at the same time, then a builder agent combines their plans into one page.

A shared multi-agent project for Racheal Winstead and Sam H. to build and test coordinated agent workflows.

The current Python prototype has a provider-independent design-agent loop and an offline HTML renderer. It uses only the standard library (Python 3.9+); no installation or API key is needed for the demo.

## Build and preview a draft

From the repository directory, run:

```sh
python3 -m unittest discover -s tests -v
python3 -m sitestarter --brief examples/bakery-brief.json --plan examples/bakery-design.json
python3 -m http.server 4173 --bind 127.0.0.1 --directory dist
```

Open **http://127.0.0.1:4173/**. Use About, Contact, and Get in touch to jump between sections. Resize below 600px to check the single-column layout. Keyboard users can press Tab for the skip link and navigate the links. Stop the local server with Ctrl+C.

The build writes `dist/index.html`, a self-contained file you can open or share. Output folders are created automatically; an existing output file is never replaced. For another build, choose a fresh path with `--output dist/another-draft.html`. Generated output is ignored by Git.

The bakery files are explicitly fictional sample data. To use your own facts, copy both JSON files and supply `request_id`, `name`, `purpose`, `about`, and `contact` in the brief. The design plan must use the same request ID and pass the design validator. Missing information, malformed JSON, incomplete plans, low contrast, and unsupported design values stop the build before an output file is created. Business text is escaped, contact details stay as supplied text, and the page loads no scripts, fonts, or other external assets.

## Run the design-to-builder handoff

```sh
python3 -m sitestarter.handoff_demo --brief examples/bakery-brief.json --model-response examples/bakery-design.json
```

This passes the brief to the design agent, sends its accepted plan to the builder, and runs final checks on the built page before writing `dist/handoff.html`. There is no live model yet: `--model-response` is a recorded design-agent reply that stands in for the model call, and it goes through the same validation and one retry. Repeat `--model-response` to replay a rejected reply followed by a retry. A rejected plan, a plan for a different request, a `needs_input` reply, or a page that fails final checks stops the run without writing a file.

## Run the content-design review loop

```sh
python3 -m sitestarter.loop_demo --brief examples/bakery-brief.json --replies examples/bakery-loop-replies.json
```

The content agent and design agent each write a plan, then review each other's plan for up to three rounds before a final plan gate and the builder. In the recorded example the design agent asks for a shorter heading, the content agent revises it, and both agree in round 2. The replies are hand-written stand-ins for model output, not live AI. See `docs/content-design-loop.md` for the data contracts and stop rules.

## What is implemented

- `sitestarter/design_agent.py`: call an injected model function, validate its JSON, and retry once on an error. Tests use scripted responses.
- `sitestarter/builder.py`: turn explicit brief facts and an accepted complete plan into responsive HTML. This is a deterministic offline renderer, not an AI Builder agent.
- `sitestarter/handoff.py`: design agent → builder handoff. Only an accepted plan reaches the builder, and HTML is returned only after final checks pass.
- `sitestarter/final_checks.py`: checks on the finished page: no scripts, embeds, forms, event handlers, outside links, or resource-loading CSS; the content security policy is present; sections are in order; and the approved name and contact appear exactly as supplied.
- `sitestarter/planning_loop.py`: content ↔ design review loop with handoff checks, a three-round cap, a deadline, and a final plan gate before the builder.
- `python3 -m sitestarter --help`: build command with bounded JSON input and output overwrite protection.
- GitHub Actions: run the tests and sample build on Python 3.9 and 3.12 for pushes and pull requests.

A live provider, Content Agent, Coordinator, AI Builder loop, enforced execution deadlines, session state, and isolated preview service remain integration work. The local preview server is for inspecting your generated file; it is not the production preview isolation described in the architecture. This change does not deploy or publish a site.

## Branches

```text
main (stable, checked releases)
└── develop (shared integration)
    ├── racheal-w (Racheal's current work)
    └── sam-h (Sam's current work)
```

Partner work goes into `develop` through reviewed pull requests. After integration is checked, open a pull request from `develop` into `main`.

The existing partner branches are the initial working branches. For each new task, start a descriptive branch from updated `develop`, for example `codex/dispute-intake` or `codex/compliance-review`.

Branch names identify work, not access restrictions. Collaborators can access repository branches. See WORKING_AGREEMENT.md for review and coordination rules.

## First-time setup

Each person uses their own GitHub account. Sam must accept the collaborator invitation before cloning.

```sh
git clone https://github.com/Racheal-Winstead/SiteStarter.git
cd SiteStarter
git fetch origin
```

Racheal: `git switch --track origin/racheal-w`

Sam: `git switch --track origin/sam-h`

If the local branch already exists, use `git switch racheal-w` or `git switch sam-h` instead.

## Daily workflow

1. Agree on the task and files before starting; create an issue for shared tracking.
2. With a clean working tree, fetch updates and merge `origin/develop` into your own branch. Resolve conflicts together if they affect shared behavior.
3. Make a small coherent change and run the checks appropriate to it.
4. Inspect `git diff` and `git status` before staging specific files. Commit and push your branch.
5. Open a pull request from your branch into `develop` and request your partner's review.
6. Merge only after approval and passing available checks. Keep the two initial working branches after merging. Promote checked integration work with a separate `develop` → `main` pull request.

Do not force-push shared history. Do not commit secrets, recordings, private user data, or dependency folders. Run the test and sample-build commands above before opening or updating a pull request.

## Configuration

Store local credentials in ignored `.env` or `.env.local` files, using each person's own authorized credentials. Add an `.env.example` containing names and placeholders only when configuration is defined. Share secret values through an approved secret-sharing mechanism, never a commit or pull-request comment.

## Next joint decisions

- One user problem, project scope, and agent responsibilities.
- Agent communication contracts, tools, failure handling, and human checkpoints.
- Implementation stack, setup commands, and automated checks.
- Acknowledged working agreement, task ownership, and check-in schedule.
