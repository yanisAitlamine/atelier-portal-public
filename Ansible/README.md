# Deployment boundary

The private installation-specific playbook, paths, account mappings and proxy
recipe are intentionally excluded. Prepare a separate tool-specific deployment
recipe for the maintainer's approved server and exact release. Keep the canonical
Git repository and runtime there, secrets and durable data outside releases,
and bind the application to loopback behind approved private HTTPS.
Do not run unrelated reserved roles, access a personal control machine, or
infer deployment authorization from a source commit or this public export.
