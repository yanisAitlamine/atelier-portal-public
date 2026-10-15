# Limite de déploiement

Les recettes, chemins, groupes, wrappers et permissions de l'exploitation privée
sont volontairement exclus. Préparer une recette propre à l'outil pour le
serveur approuvé et la release exacte ; conserver code canonique et service sur
ce serveur, secrets et données durables hors release, service en loopback derrière
HTTPS privé. Ne pas lancer d'anciens rôles réservés ni accéder à une machine
personnelle de contrôle. Un commit public n'autorise aucun déploiement, accès aux
journaux réels ou ajout d'un compte à un groupe privilégié.
