# Où intervenir et comment vérifier

Commencer par expliquer au responsable ce qui existe et ce qui reste préparé.
Aucun chemin d'exploitation ou droit d'accès réel n'est publié ici.

| Ressource | Fichiers utiles |
| --- | --- |
| Interface du chat unique et contexte Drive | `frontend/portal.tsx` |
| Contrats et limites de texte | `lib/contracts.ts`, `lib/limits.ts`, `server/domain.py` |
| API, propriété des sites et révisions | `server/app.py` |
| Demandes, contexte privé et résultats validés | `server/pipeline.py`, `server/integration.py` |
| Classification Jev de la demande active | `integrations/n8n/web-decision.cjs` |
| Citations et décision sur le brief | `integrations/n8n/mail-core/engine.cjs` |
| Contrôle heuristique des sources Drive | `integrations/n8n/source-scan.cjs`, `docs/SOURCE-SAFETY.md` |
| Consentement, lecture et preuves des sources | `integrations/n8n/mail-core/intake.cjs`, `integrations/n8n/web-adapter.cjs` |
| Modèles de workflows et génération locale | `integrations/n8n/build_web_workflows.py`, `integrations/n8n/web/` |
| Journal borné à métadonnées | `server/diagnostics.py`, `tests/test_diagnostics.py` |
| Validation opérateur exacte avant livraison | `server/pipeline_review.py` |
| Support explicite | `server/support.py`, `tests/test_support.py` |

## Vérifications sans effets externes

```sh
python3 -m unittest discover -s tests -v
python3 tests/e2e_portal.py
node --test integrations/n8n/web-adapter.test.cjs integrations/n8n/web-decision.test.cjs integrations/n8n/source-scan.test.cjs
node integrations/n8n/mail-core/engine.test.cjs
node integrations/n8n/workflow.test.mjs
node integrations/n8n/support-workflow.test.mjs
python3 integrations/n8n/build_web_workflows.py --output .generated/workflows
npm run build
```

Les tests emploient des données fictives et des transports simulés. Ils ne
prouvent aucune exécution de n8n, de modèle, de Drive ou de constructeur réel.
Les fichiers générés restent des modèles avec références d'exemple à configurer.

## Lire un journal local fictif

Après avoir créé des événements dans sa propre base de démonstration locale :

```sh
python3 server/diagnostics.py --db .data/demo.sqlite3 --limit 100
python3 server/diagnostics.py --db .data/demo.sqlite3 --event generation.failed --limit 50
```

Le lecteur est en lecture seule ; il ne crée ni ne migre une base inexistante.
Consulter son `--help` pour les filtres de période, projet, demande et statut.
Les événements relient connexions, décisions, sources, demandes de génération,
échecs et revue par identifiants, codes et instants. Aucun texte client, extrait
Drive, adresse, secret ou cookie ne doit y être ajouté. Les logs restent des
métadonnées privées ; leur export nécessite une revue et une anonymisation.

Les journaux réels, le lecteur développeur limité et les habilitations sont
décrits uniquement dans la documentation privée de l'opérateur. Demander cet
accès au responsable avec sa propre identité ; ne pas ouvrir la base brute ni
chercher un secret pour contourner un refus. L'accès au code GitHub n'accorde
pas l'accès aux traces ou aux comptes clients.

## Contrat canonique de la maquette

Le reçu vérifié du constructeur utilise une URL de répertoire canonique :
`https://mockups.example.invalid/maquettes/<job>/`. Le serveur et l'adaptateur
comparent strictement cette URL au job attendu. Ne pas ajouter `index.html`,
retirer la barre finale, ajouter une requête, un fragment ou un autre chemin :
ces variantes ne satisfont pas la preuve de livraison. Le domaine donné ici
est un exemple réservé ; la correspondance réelle reste privée.

Le succès exige aussi le bon projet, la bonne révision, l'empreinte et la revue
indépendante. Un lien accessible seul ne prouve jamais la validation. Les tests
`tests/test_pipeline.py` et `integrations/n8n/web-adapter.test.cjs` couvrent le
reçu canonique et les variantes refusées. Cette correction de source n'annonce
aucune installation du service ou activation du workflow.

## Décodage strict de la réponse conversationnelle

`W.replyText`, dans `integrations/n8n/web-adapter.cjs`, lit exactement un bloc
`output_text` de l'enveloppe de réponse. Selon le nœud fournisseur, son champ
`text` peut déjà être un objet décodé par `json_schema` ou encore un texte JSON.
Le décodeur analyse seulement le second cas, puis applique le même schéma aux
deux formes : objet non nul, hors tableau, avec la seule clé `reply`, chaîne de
3 à 8 000 unités de longueur JavaScript. Il n'accepte ni réponse multiple,
JSON mal formé, valeur primitive, clé ajoutée ou longueur hors limite.

Ce décodeur transporte une réponse de chat ; il n'autorise aucune décision,
construction, variation de prix ou publication. Les vérifications Jev, de
propriété, de révision, de consentement et de preuve restent séparées. Les tests
fictifs du module et la génération SDK couvrent le contrat ; ils ne prouvent
aucun appel réel du fournisseur ni installation du workflow corrigé.
