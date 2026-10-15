# Offline n8n integration templates

This directory contains example source templates, not deployable operator
configuration. All installation-specific workflow IDs, credential references,
addresses and reader-account details were replaced by deterministic examples.
No secret value or credential can be recovered from those placeholders.

- `workflow.json`: original dialogue/prototype transport template.
- `support-workflow.json`: explicit support transport template.
- `mail-core/`: pinned pure evidence, source-intake and image-manifest logic.
- `web-adapter.cjs`: web identity, source consent, decision and proof adapter.
- `mail-core/graphs.json`: example node definitions used by the generator.
- `web/*.sdk.js`: example SDK sources, inactive until privately configured.
- `web/manifest.json` and `web/child-ids.json`: example relationships only.

Generate reviewable examples locally:

```sh
python integrations/n8n/build_web_workflows.py --output .generated/workflows
```

The generator does not contact n8n. Generated files are still examples and need
private operator-owned credentials, URLs, workflow IDs and caller restrictions.
Store the real mapping outside this repository. Keep OAuth read-only and ask
for explicit source consent. The client must own the project; Drive evidence
must match that project's actual client contribution and complete document read.

Prototype construction and artifact checks use an example reserved host and
root. Replace the target consistently in private configuration and adapters,
reserve the real target, and preserve queue/locking and human delivery approval.
A test stub or a READY decision alone does not attest a real build or delivery.
Never run a production integration merely to verify these source templates.
