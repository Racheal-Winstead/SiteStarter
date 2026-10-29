# Local interface and real validation

```sh
python3 -m sitestarter.web
```

Open http://127.0.0.1:4173/. The approved ’50s design now has a three-step form
that posts to the Coordinator and runs the real planning loop with recorded
response templates. A valid submission receives a session-owned request ID,
workflow events, and either a checked HTML result or a review-required state.
An invalid submission gets field-specific errors with other answers preserved.
No AI credentials or additional packages are needed. See
[recorded-wiring.md](recorded-wiring.md) for the output gate and test scenarios.

This is a loopback-only development server, not a production deployment.
It binds to 127.0.0.1 and requires same-origin JSON POSTs. A temporary HttpOnly
session cookie separates in-memory records; there is no disk persistence.
The recorded agent callbacks use submitted facts and a fixed design fixture.
The actual Builder produces the HTML preview/download. There are no live models.

Use sample details for review. Business text is not written to console logs.
Google Fonts receives font requests but no submitted brief; the illustration
is served locally. Input limits are enforced server-side; browser maxlength
attributes provide additional convenience. Stop the server with Ctrl+C.

The original interface and input gate are merged in develop. The recorded-run
integration is separate local work; no public Site or production server exists.
