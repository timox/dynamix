# Comparaison audio du pré-master

## Intention

Permettre d’évaluer le pré-master d’un morceau sur sa durée complète, puis de comparer un même passage à l’écoute sans que l’écart de niveau masque les différences de timbre.

## Approches considérées

- **Graphiques sur l’extrait de 30 secondes** : rapides, mais ne montrent qu’une portion du morceau. Écartée après la préférence exprimée pour une analyse complète.
- **Analyse complète à la demande de l’original et de sa copie pré-master** : donne une vue globale, réutilise les résultats en cache et n’analyse que le morceau sélectionné. Approche retenue.

## Conception

- Dans l’onglet Corrections, afficher côte à côte les spectrogrammes complets de l’original et de la copie pré-master courante, avec la même échelle de temps, de fréquence et de couleur.
- Afficher une répartition des bandes avant/après, calculée sur les morceaux complets, sous les spectrogrammes.
- Afficher le gain de pré-master réellement appliqué et les sonies avant/après depuis le rapport de rendu du projet.
- Réutiliser les analyses complètes déjà en cache pour l’original. Calculer et mettre en cache les analyses manquantes de la copie pré-master lors de sa première comparaison.
- Limiter les grandes allocations : produire les données du spectrogramme par blocs et en résolution adaptée à l’affichage; ne pas conserver de tableau STFT pleine résolution pour toute la durée.
- Conserver le lecteur de pré-écoute de 30 secondes et son curseur commun. Ajouter une écoute A/B à niveau intégré compensé sur l’extrait, tout en affichant séparément le gain réel du pré-master.
- La comparaison graphique porte sur la copie pré-master effectivement enregistrée, y compris les corrections déjà intégrées. Une correction encore à l’état de proposition reste disponible dans la pré-écoute, puis apparaît dans les graphiques après validation et nouveau rendu du pré-master.

## Hors périmètre

- Pas de rendu ni d’analyse pleine durée d’une correction non validée.
- Pas de normalisation permanente des fichiers comparés : l’égalisation de sonie concerne uniquement la pré-écoute.

## Écran visé

```text
Original                                      Pré-master courant
[spectrogramme complet]                      [spectrogramme complet]
[répartition des bandes]                     [répartition des bandes]

Gain appliqué : +X dB   ·   Sonie : avant → après
Position : [curseur commun]   [A : original] [B : pré-master] [Stop]
Écoute A/B compensée en sonie sur le passage sélectionné
```
