# Atelier — code public du portail

Ce dépôt fournit une copie assainie du frontend React/TypeScript et du serveur
Python du portail. Son histoire publique est indépendante de l'exploitation
privée. Les configurations, comptes clients, conversations et accès réels ne
font pas partie de ce dépôt.

## Fonctionnalités préparées dans le code

- Un seul chat par site, avec messages jusqu'à 20 000 caractères et limites
  explicites dans le contrat partagé.
- Classification Jev de la demande active : contenu, refonte visuelle, ajout de
  page, fonction avancée ou clarification. Le client n'a pas à choisir un sujet.
  Une classification n'accepte jamais un devis ni un paiement à sa place.
- Contexte Drive sur consentement : lien de dossier partagé en lecture au compte
  de service configuré. Il n'y a pas de connexion OAuth au Drive personnel du
  client ni de jeton Google fourni par cette copie publique.
- Contrôle heuristique des sources avant images, Jev et construction. Une
  suspicion ou une lecture incomplète bloque l'admission ; l'absence de motif
  connu ne certifie jamais qu'un document est sûr.
- Génération suivie, vérification de l'artefact et approbation opérateur distincte
  avant livraison. Support explicite et journal de diagnostic à métadonnées.

La présence de ces fonctionnalités dans Git décrit une préparation de code.
Elle ne prouve ni leur installation dans un service, ni une lecture Drive,
ni une génération réelle. L'état du service se vérifie dans l'exploitation
privée autorisée, séparément de ce dépôt.

## Développement local

Python >=3.11 et une version Node prise en charge sont requis (20.19+, 22.12+
ou version LTS plus récente ; éviter les versions intermédiaires non supportées).

```sh
npm ci
python3 -m unittest discover -s tests -v
npm run build
```

Dans deux terminaux :

```sh
python3 server/app.py --origin http://127.0.0.1:5173
npm run dev
```

Ouvrir `http://127.0.0.1:5173/portal/`. Utiliser uniquement des comptes et projets
fictifs. Le dossier `.data/` est ignoré. Le fonctionnement local sans intégration
utilise des réponses guidées et des aperçus de démonstration.

## Ressources pour les agents

Lire [AGENTS.md](AGENTS.md), puis le [guide des ressources](docs/RESSOURCES-AGENTS.md).
Il localise les contrats du chat, les décisions Jev, le contrôle des sources,
les traces et les tests. Le [contrôle des sources](docs/SOURCE-SAFETY.md) précise
les limites de la détection ; les [modèles n8n](integrations/n8n/README.md) sont
à configurer avec l'opérateur avant toute utilisation externe.

Les références EXAMPLE et domaines réservés sont volontairement inutilisables.
Le code public n'accorde aucun accès serveur, Drive, messagerie, hébergement ou
journal réel. Le dépôt canonique, le service et les données durables restent sur
le serveur approuvé du projet ; Windows peut servir de miroir de développement.
