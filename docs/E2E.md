# Vérifications de la copie publique

Les tests locaux et les modèles SDK ne démontrent pas à eux seuls un déploiement,
une lecture réelle de Drive, un appel de modèle ou une construction distante.
Les configurations et journaux réels restent dans l'exploitation privée.

## Contrôles de la candidate

```sh
node --test integrations/n8n/source-scan.test.cjs integrations/n8n/web-adapter.test.cjs integrations/n8n/web-decision.test.cjs
python3 integrations/n8n/build_web_workflows.py --output .generated/workflows --child-ids integrations/n8n/web/child-ids.json
npm ci
npm run build
```

Le générateur ne contacte aucun service. Les tests utilisent des données fictives,
les VM locales et des enveloppes simulées. Ils couvrent admission stricte et
projection sandbox reconnue, refus des capacités propres, absence de getters et
hooks exécutés, conservation exacte du texte, nouveau scan et contexte détaché.
Les images JPEG/WebP nécessitant une revue doivent être bloquées avant Jev.
Les réponses conversationnelles natives ou JSON restent soumises au schéma fermé.

## Relevé antérieur, à ne pas lire comme le dernier bilan

Le libellé historique «79 Python /100 Node» décrit une étape antérieure.
Il ne constitue pas le dernier relevé de cette candidate et n'est pas additionné
aux autres séries. Les compteurs d'une source privée peuvent inclure un test
statique du wrapper d'exploitation volontairement absent de cette copie publique.
Le détail du contrôle public courant est consigné dans `PUBLIC-EXPORT.json`.

Les 79 tests Python publics et les autres vérifications précédemment attestées
restent distincts des contrôles ciblés de ce correctif. Les rejouer si les fichiers
ou contrats qu'ils couvrent changent :

```sh
python3 -m unittest discover -s tests -v
python3 tests/e2e_portal.py
node integrations/n8n/mail-core/engine.test.cjs
node integrations/n8n/workflow.test.mjs
node integrations/n8n/support-workflow.test.mjs
```

Une sonde d'intégration n8n isolée a été rapportée par le mainteneur : fixtures
bénignes/hostiles, nouveau scan, texte exact, réponses structurées, contexte
détaché et revue d'images, sans identifiant ni appel externe. Cette attestation
est distincte des tests que ce dépôt permet de rejouer et ne prouve aucune
publication de workflow ou réussite d'un parcours client complet.

La version réellement exécutée et ses droits se vérifient uniquement avec
l'opérateur autorisé. Ne pas activer un modèle ou lancer un parcours de production
pour tester cette copie publique. La livraison d'un artefact réel conserve son
approbation opérateur exacte ; un test ne fabrique jamais un accord humain.
