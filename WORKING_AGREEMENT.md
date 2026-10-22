# Working agreement — draft for both partners to confirm

Owners: Racheal Winstead (@Racheal-Winstead) and Sam H. (@ibtisamhossain-netizen).

These are proposed project rules, not a claim that Sam has accepted them.

- Agree on scope and task ownership before implementation. Announce overlapping file edits.
- Discuss changes in direction before replacing or setting aside a partner's work. Review their findings first.
- Use Slack for routine coordination; talk live for blockers, unclear requirements, or disagreements. Record the resulting decision in writing.
- Agree on check-in times that support remote/off-campus work. Set realistic response expectations together; off-hours replies are not assumed.
- Each partner works on their own branch and opens small pull requests. Target `develop`; the other partner reviews before integration. Promote checked work from `develop` to `main` through a separate reviewed pull request.
- Avoid direct pushes, force pushes, and deletion of main or develop. If GitHub cannot enforce protection for this private repository, follow the review rule manually.
- Validate shared interfaces and tool outputs before integrating agents. Keep responsibilities and stop conditions explicit.
- Each partner should be able to explain the architecture, tool access, and demonstrated loop.
- Use synthetic test inputs and personal authorized API credentials. Never commit secrets or private learner data.

At the first planning session, jointly confirm or revise these rules and record specific responsibilities, check-in times, and the run/test commands.
