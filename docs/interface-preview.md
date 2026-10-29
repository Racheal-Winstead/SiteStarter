# Local interface and real validation

```sh
python3 -m sitestarter.web
```

Open http://127.0.0.1:4173/. The approved ’50s design now has a three-step form
that posts to the Coordinator input gate. A valid submission gets an accepted
message and request ID. An invalid submission gets field-specific errors, with
other answers preserved. No AI credentials or additional packages are needed.

This is a loopback-only development server, not a production deployment.
It binds to 127.0.0.1 and requires same-origin JSON POSTs. It does not persist
briefs, set cookies, or run agents. Accepted means input validation passed;
there is no generated website, preview, download, or simulated generation.

Use sample details for review. Business text is not written to console logs.
Google Fonts receives font requests but no submitted brief; the illustration
is served locally. Input limits are enforced server-side; browser maxlength
attributes provide additional convenience. Stop the server with Ctrl+C.

This branch depends on the Coordinator input-gate PR. The interface is new
local work; no public Site or production server has been created.
