# Comparaison audio du pré-master — plan d’implémentation

> **Pour les agents d’implémentation :** exécuter chaque tâche dans l’ordre, en conservant les cases à cocher.

**Objectif :** afficher une comparaison spectrale complète entre un morceau original et sa copie pré-master, et permettre leur écoute A/B à sonie égale sur l’extrait choisi.

**Architecture :** calculer spectrogramme et énergie par bande en flux, avec une matrice réduite à la résolution d’affichage. Construire un graphique côte à côte à partir des originaux et des copies pré-master réelles; piloter le lecteur A/B depuis l’onglet Corrections.

**Technologies :** Python, SoundFile, NumPy, SciPy, Matplotlib, Tkinter, cache SQLite existant.

**Spécification :** `docs/superpowers/specs/2026-11-15-premaster-audio-comparison-design.md`

## Contraintes globales

- Le calcul porte sur le morceau entier, mais lit l’audio par blocs et ne garde pas une STFT pleine résolution en mémoire.
- Les graphiques comparent l’original à la copie pré-master actuellement rendue, corrections validées incluses.
- L’égalisation de sonie ne touche qu’aux fichiers temporaires d’écoute; le gain réel de pré-master reste affiché séparément.
- Réutiliser les analyses existantes de l’original et celles mises en cache pour les copies pré-master.
- Une correction non validée n’est montrée dans les graphiques qu’après validation et nouveau rendu du pré-master.

## Points de revue

- Long morceau stéréo à fréquence d’échantillonnage élevée : mémoire bornée par les blocs.
- Fichier pré-master absent ou devenu obsolète : expliquer qu’il faut d’abord relancer le pré-master.
- Extrait presque silencieux : éviter une compensation de sonie excessive et signaler le cas.
- Cache après remplacement d’un fichier : détecter le changement de taille/date de modification.
- Changement de morceau pendant l’analyse : ne pas afficher des résultats périmés.

---

### Tâche 1 : analyse spectrale complète à mémoire bornée

**Fichiers :**
- Créer : `spectrogram.py`
- Modifier : `analysis_store.py` seulement si le cache existant permet d’ajouter un résultat de spectrogramme sans invalider les autres analyses.

**Interface :**
- Produit `analyze_spectrum(path: str, max_time_bins: int = 900, freq_bins: int = 256, check=None) -> Dict`, avec `duration_s`, `sample_rate`, `times_s`, `frequencies_hz`, `spectrogram_db` et `band_balance_db`.
- La lecture par blocs calcule une moyenne spectrale complète et un spectrogramme temps/fréquence réduit; les bandes reprennent les bandes de référence de `mastering.py`.

- [x] Ajouter un contrôle local de forme, valeurs finies et borne de dimensions sur un fichier audio temporaire créé par le self-test existant; ne pas ajouter une suite de tests dédiée.
- [x] Vérifier le contrôle sur WAV et sur un fichier plus long que la taille d’un bloc.
- [x] Implémenter l’analyse par blocs avec cache mémoire limité à la paire sélectionnée; ne pas changer la version globale des analyses déjà stockées.
- [x] Exécuter `py_compile` sur le nouveau module et les modules modifiés.

### Tâche 2 : graphiques avant/après côte à côte

**Fichiers :**
- Modifier : `charts.py`

**Interface :**
- Ajouter `premaster_spectral_comparison(before: Dict, after: Dict, gain_db: Optional[float], lufs_before: Optional[float], lufs_after: Optional[float]) -> Figure`.
- Afficher deux spectrogrammes avec axes et échelle de couleur partagés, puis la répartition des bandes avant/après.
- Annoter le gain de pré-master effectivement appliqué et les sonies mesurées.

- [x] Construire les panneaux sans recalcul audio dans `charts.py`.
- [x] Conserver une hauteur et une largeur compatibles avec l’onglet Corrections et ses contrôles de lecture.

### Tâche 3 : intégration dans Corrections et écoute A/B

**Fichiers :**
- Modifier : `set_builder.py`, `mastering.py`, `locales/fr/set_builder.json`

**Interface :**
- Le morceau sélectionné déclenche, si nécessaire, une analyse en tâche de fond de l’original et de son fichier pré-master courant.
- Le graphe ne s’affiche que si les deux sources sont disponibles; les erreurs de calcul restent visibles dans l’onglet.
- Ajouter une écoute A/B synchronisée sur le curseur existant, compensée à la sonie LUFS de l’extrait original, avec la valeur de compensation et le gain réel du pré-master affichés séparément.
- Abandonner les rendus/analyses de morceaux qui ne sont plus sélectionnés et garder le cache limité aux sources concernées.

- [x] Préparer les deux sources à partir du projet et des résultats de pré-master enregistrés.
- [x] Ajouter le rendu temporaire A/B compensé sans modifier les fichiers sources ou pré-master.
- [x] Remplacer proprement les figures existantes et garder le lecteur utilisable dans la zone basse.
- [x] Vérifier les textes français et les cas sans copie ou sans rapport de pré-master.

### Tâche 4 : vérification de livraison

**Fichiers :**
- Modifier : `version.py`
- Générer : `dist/DynaMix-<version>-setup.exe`

- [x] Lancer `git diff --check`, `py_compile`, puis l’auto-contrôle embarqué dans l’application empaquetée.
- [x] Construire l’installeur Windows, réinstaller DynaMix sur ce poste et vérifier l’auto-contrôle de la version installée.
- [ ] Créer et pousser des commits intermédiaires isolés sur `origin/main`, comme demandé; ne pas publier de release.
