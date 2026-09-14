# Interface en français

Date : 2026-09-14. Décisions validées avec l'utilisateur : tout traduire (C) en deux étapes, langue choisie dans
Configuration et appliquée au prochain démarrage (A), catalogue JSON corrigeable à la main, jargon DJ gardé en
anglais (B).

## Mécanisme (`i18n.py`)

- L'anglais reste le texte de référence dans le code : `tr("Analysing {name} ...", name=...)`. Jamais de `tr()` au
  chargement d'un module (constantes) : on traduit au moment d'afficher.
- Catalogue français : `locales/fr/*.json` (un fichier par partie de l'application), clé = texte anglais exact,
  valeur = traduction avec les mêmes `{champs}`. Les clés commençant par `_` sont des commentaires.
- Corrections de l'utilisateur, même dans la version compilée : `<DynaMix home>/locales/fr.json` (ou
  `locales/fr/*.json`), qui remplacent les entrées livrées.
- Traduction absente ou `{champ}` incohérent : le texte anglais s'affiche, l'interface ne plante jamais.
- Langue : réglage `language` (`auto` = langue de Windows, `en`, `fr`) dans Configuration, appliqué au prochain
  démarrage ; la variable d'environnement `DYNAMIX_LANGUAGE` l'impose (le test de l'interface utilise `en`).
- Le catalogue est inclus dans la version compilée (`packaging/dynamix.spec`).

## Vocabulaire

Jargon gardé en anglais : set list, cue, intro / outro, pre-master, freeze, FX, BPM, LUFS, dBTP, Q, Auto DJ, Mixxx,
snapshot. Tout le reste est traduit (« Planifier les transitions », « Appliquer tous les FX »).

## Étapes

1. Interface et graphiques : onglets, boutons, libellés, colonnes, dialogues, barre d'état, Tasks, Log (titres et
   boutons, pas les lignes du log), titres, légendes et annotations des graphiques, étapes et conseils du workflow.
2. Rapports : alertes de mastering, analyse par bande, notes et feuille de transitions, résumé du projet, rapports
   Pre-master, Playlist et Mixxx Export. Le fil du Log (messages techniques et tracebacks) reste en anglais.

## Tests

- `tests/test_i18n.py` : `tr()`, repli sur l'anglais, corrections utilisateur, et complétude : chaque `tr("…")`
  littéral du code a une entrée française avec les mêmes `{champs}`.
