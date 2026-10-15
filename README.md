# Atelier portal — public source candidate

A React/TypeScript frontend and a Python standard-library API for account-owned
website conversations, brief decisions, prototype requests and explicit support.
This is a sanitized, independent source snapshot with no inherited Git history.
It contains no running service, production access, customer records or credentials.

## Start locally

Requires Node >=20.19 (use a current supported release), npm and Python >=3.11.

```sh
npm ci
python -m unittest discover -s tests -v
npm run build
```

Run `python server/app.py --origin http://127.0.0.1:5173` and `npm run dev` in
separate terminals. Open `http://127.0.0.1:5173/portal/`.
The local database in `.data/` is ignored. Use fictional accounts and projects.
Local guided answers and concept previews work without external integrations.

## Configure integrations

Read [integration templates](integrations/n8n/README.md). The templates include
Drive source reading, image manifests, Jev evidence/decision and a prototype
builder adapter. Example domains are deliberately unresolvable. Workflow and
credential references are deterministic placeholders, not access grants.
Replace them through operator-owned private configuration before any connection.
Do not import, activate or execute these templates blindly against production.
No Google account connection, hosting account or n8n permission is bundled.

`server/integration.py` supports the older protocol and the candidate v2 protocol.
`server/pipeline.py` owns the web context and artifact checks;
`server/pipeline_review.py` is an operator-only delivery approval command.
The runtime integration JSON, TLS trust and token files must stay outside Git.
The public copy contains no operational mapping back to the private installation.

## Tests and limits

```sh
python tests/e2e_portal.py
node integrations/n8n/workflow.test.mjs
node integrations/n8n/support-workflow.test.mjs
node --test integrations/n8n/web-adapter.test.cjs
node --test integrations/n8n/mail-core/engine.test.cjs
```

Tests use temporary data and doubles. They do not prove external model, Drive,
mail delivery or hosting access. An actual deployment requires its own private
configuration, target reservation, human approvals and independent review.
The v2 integration is a source candidate, not an attested live deployment.

## Collaboration

Start with [AGENTS.md](AGENTS.md). Explain the existing frontend, API, context,
workflow and tests to the project maintainer before implementing a new change.
The canonical development repository and deployed application belong on the
project's approved server; a Windows-only demo is not a deployed release.
Public source access never grants access to that server or customer data.
