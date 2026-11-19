# Ninja NIN sandbox test

This isolated localhost app tests Ninja's NIN `verify` mode without spending money or returning
the person's full registry record. It accepts sandbox keys only.

Official links:

- [Create a Ninja account](https://www.ninja.ng/user/register/)
- [Ninja API documentation](https://www.ninja.ng/docs/)

## Setup

Copy `.env.example` to `.env`, then add the sandbox secret key from Ninja's dashboard. The `.env`
file is ignored by Git.

```bash
set -a
source test_ninja/.env
set +a
.venv/bin/uvicorn test_ninja.app:app --host 127.0.0.1 --port 8766
```

Open <http://127.0.0.1:8766>. The form is prefilled with Ninja's documented passing sandbox case:

- NIN: `77777777777`
- First name: `James`
- Last name: `Bond`
- Date of birth: `1975-01-01`

Ninja also documents `55555555555` as a sandbox `not_found` case. No webhook or public URL is
needed for this direct server-to-server verification test.

The app does not write submitted identity details to disk or intentionally echo them in its result.
Do not use a real NIN with the sandbox harness.
