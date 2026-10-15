# Admission des sources Drive

`integrations/n8n/source-scan.cjs` est un module pur et local. Le graphe généré
l'insère après le lecteur Drive, avant dépôt des images, Jev et construction.
Il recalcule son propre reçu au lieu de croire un champ fourni par le navigateur.
Une erreur, lecture incomplète ou suspicion doit bloquer cette branche, sans
repli trompeur vers une conversation annoncée « sans sources ».

Le module examine le texte et les métadonnées, les pages/fragments reconstruits,
les contrôles Unicode et des motifs forts français/anglais : changement de rôle,
ignorance des consignes, divulgation, commandes ou décision forcée. Les sources
originales ne sont pas retouchées pour fabriquer une copie prétendument sûre.
Le reçu ne contient que des codes, compteurs, limites et positions bornées ;
le contenu original ne doit jamais rejoindre les logs ou l'API publique.

C'est une défense heuristique, avec faux positifs et faux négatifs possibles.
L'absence de motif connu ne certifie aucune source. Les documents restent des
données non fiables, citées et rattachées au client/projet ; ils ne commandent
ni outils, ni permissions, ni prix, ni validations. Le module n'est ni antivirus,
ni OCR, ni analyse visuelle des pixels ; aucun support Office n'est ajouté.
Les images n'acquièrent pas le statut de texte contrôlé. Une future extraction
OCR/vision doit admettre séparément son texte avant de le fournir au modèle.

Consulter le code pour ses budgets et le [guide des ressources](RESSOURCES-AGENTS.md)
pour les contrats et tests. Ne pas assouplir les seuils ni créer de bouton
permettant d'ignorer automatiquement le contrôle. Déboguer un refus par son code
dans l'environnement privé autorisé, sans publier les documents concernés.

```sh
node --test integrations/n8n/source-scan.test.cjs
```

Ces tests locaux ne démontrent pas que la version du service réellement installée
exécute ce contrôle. Vérifier la release et le graphe dans l'exploitation privée.

## Frontières entre contextes JavaScript

L'admission accepte des données JSON ordinaires venant d'un autre contexte VM.
En mode `STRICT_JSON_RECORDS`, les prototypes doivent correspondre aux
constructeurs natifs attendus ; classes et prototypes personnalisés sont refusés.
Dans le runner n8n pris en charge, les API de prototype sont explicitement
anonymisées. Le mode `SANDBOX_OWN_DATA_COPY` reconnaît ce comportement précis et
copie seulement les descripteurs propres de données vers des records sans
prototype et des tableaux neufs. Il ne récupère pas les prototypes cachés.

Une introspection autrement remplacée est refusée. Dans les deux modes, les
capacités propres dangereuses, accesseurs, symboles, cycles, hooks de
sérialisation et tableaux enrichis sont refusés. Aucun getter ou hook de la
source ne doit être appelé. Les propriétés héritées sont éliminées par la copie
sandbox ; leur identité n'est pas certifiée. Une instance ne contenant que des
données inertes peut être projetée dans ce mode : ce n'est pas une preuve de
refus de toutes les classes ni un bac à sable pour du JavaScript arbitraire ou
un Proxy exécutant des traps.

Le consommateur doit utiliser le clone retourné, détaché de la source, et refaire
l'admission avant le contexte fournisseur. Un reçu ancien ne dispense jamais
d'un nouveau contrôle. Chaînes, guillemets, Unicode et retours de ligne restent
exacts. JPEG/WebP nécessitant une revue doivent produire un état `BLOCKED` lié au
projet, sans passage à Jev ni erreur générique dissimulant ce motif.
