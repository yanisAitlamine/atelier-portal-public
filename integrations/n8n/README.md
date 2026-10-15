# Modèles n8n hors ligne

Ces sources sont des exemples assainis. Domaines réservés, compte lecteur et
références EXAMPLE ne donnent aucun accès réel. Configurer les correspondances
avec l'opérateur dans un espace privé, sans les reverser dans Git.

- `web-decision.cjs` : demande de classification Jev et validation du résultat.
- `source-scan.cjs` : contrôle heuristique avant admission des sources Drive.
- `mail-core/` : logique pure des citations, du lecteur et des images.
- `web-adapter.cjs` : identité web, consentement, décisions et preuve d'artefact.
- `mail-core/graphs.json` : exemples des nœuds utilisés par le générateur.
- `web/*.sdk.js` : modèles SDK à configurer ; `web/manifest.json` et
  `web/child-ids.json` décrivent uniquement des relations d'exemple.
- `workflow.json`, `support-workflow.json` : transports de dialogue et support.

```sh
python3 integrations/n8n/build_web_workflows.py --output .generated/workflows
```

La génération ne contacte pas n8n. Ne pas importer ni activer aveuglément ces
modèles en production. Les identifiants, callers, TLS, URLs, compte Drive et
cibles de construction doivent être vérifiés et configurés par l'opérateur.
Drive passe par le partage explicite d'un dossier en lecture au compte configuré,
pas par une connexion OAuth personnelle fournie dans ce dépôt. Garder sources,
jetons et historiques d'exécution privés. Modèles sans stockage fournisseur,
rétention d'exécution et retries automatiques doivent rester explicitement revus.

Une décision READY ne vaut ni construction autorisée ni livraison. Préserver
la réservation de cible, la queue, les verrous et la validation opérateur de
l'artefact exact. Les tests sont fictifs et n'attestent aucun service externe.
Lire [les ressources des agents](../../docs/RESSOURCES-AGENTS.md).
