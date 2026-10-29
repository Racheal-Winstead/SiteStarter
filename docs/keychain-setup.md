# Anthropic Keychain loader (macOS)

Each developer privately creates a generic/application password in the login
keychain using Keychain Access:

- Item/service name: `SiteStarter-Anthropic`
- Account: `sitestarter`
- Password: the institution-authorized API key

Keep normal access restrictions; do not allow all applications to access the
item. Never paste the secret into chat, commands, source code, or screenshots.
Only share institutional credentials as permitted by the issuer.

Backend Python can call `load_anthropic_key()` from `sitestarter.credentials`.
It returns a redacted `Secret`. A future provider adapter may call `.reveal()`
only to authenticate its client. This wrapper prevents accidental printing;
it does not encrypt or reliably erase Python process memory.

An explicitly set `ANTHROPIC_API_KEY` takes precedence. Without it, macOS reads
the exact service/account using `/usr/bin/security`, capturing stdout/stderr in
memory. It writes no file and does not export the credential. A missing item,
denial, timeout, or malformed value produces a fixed diagnostic with no secret.
The loader never changes Keychain permissions or tries another item on failure.

## Optional private verification

When both partners are ready to witness the check, run in the project folder:

```sh
python3 -m sitestarter.credentials
```

This command actually reads the credential, so macOS may show an access prompt.
If prompted, review the requesting program and choose Allow for this request
if expected; do not grant unrestricted access. The Mac's account password, if
requested, is different from the Anthropic key. Cancel if the request is unexpected.

Success prints only: `Credential loaded; value hidden. No API call was made.`
This checks local retrieval, not provider validity, model access, credits, or
institutional authorization. If an environment key is present, this checks that
instead of Keychain; use a terminal without that override to verify Keychain.

The current recorded workflow never calls this loader and remains key-free.
Live provider wiring and model configuration are still separate work. macOS
may ask again on future access depending on the item's access settings.

Tests mock the Keychain subprocess with fake values. Running the automated test
suite neither reads real Keychain secrets nor sends requests to Anthropic.
