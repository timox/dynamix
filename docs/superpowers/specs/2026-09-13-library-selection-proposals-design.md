# Bibliothèque, sélection, propositions de set, réinitialisation et journal

**Date :** 2026-09-13
**Statut :** design validé, en attente de relecture de la spec
**Chantier :** 1 sur 2 (le chantier 2, « FX de transition », est hors périmètre, voir la fin)

## Objectif

Aujourd'hui, chaque projet commence par copier un dossier audio dans `source/`, puis « Propose » choisit parmi tous les morceaux importés. Le nouveau flux part de la réalité : tous les morceaux que l'utilisateur a mixés sont rangés dans **un seul dossier bibliothèque**.

1. La bibliothèque est scannée sur place, sans copie.
2. L'utilisateur sélectionne quelques morceaux.
3. L'algorithme propose **plusieurs variantes de set** pour la durée voulue, **uniquement à partir de la sélection**.
4. Une variante choisie devient la set list, retouchable à la main. Les étapes suivantes (transitions, pré-master, Mixxx) ne changent pas.

S'ajoutent :

- **Deux actions de remise à zéro** : « Reset project… » et « Clear analysis cache… ».
- **Un onglet Journal** qui affiche la sortie et les erreurs. L'app est lancée avec `pythonw.exe`, donc aujourd'hui tous les `print` sont perdus.

Les libellés de l'interface restent en anglais, comme le reste de l'app.

## 1. Fonctionnement et interface

### Bibliothèque

- Nouvelle clé de configuration `library_folder` (défaut : vide), réglable dans l'onglet Configuration, section « Paths », avec un bouton Browse.
- Si elle est vide, la colonne Bibliothèque affiche : « Set the library folder in the Configuration tab ».
- Le projet enregistre des **chemins absolus** vers les fichiers de la bibliothèque. Aucune copie n'est faite pour les nouveaux projets.
- « New project… » ne demande plus de dossier source et ne crée plus `source/`.
- « Import audio… » est retiré de la barre du haut. Les anciens projets qui ont un `source/` restent lisibles (voir la migration).

### Onglet Tracks (Set Builder), en trois colonnes

1. **Library**
   - Colonnes : Filename, Dur, BPM, Key, Energy, Sel (coche si le morceau est sélectionné).
   - Un champ de filtre au-dessus : sous-chaîne du nom, sans tenir compte de la casse.
   - Dur vient des métadonnées du fichier. BPM, Key et Energy viennent du cache d'analyse s'il est à jour, sinon « — ».
   - Sélection multiple (Ctrl et Maj), puis bouton « Add to selection → ». Un double-clic ajoute le morceau.
   - Bouton « Rescan » pour relire le dossier.
2. **Selection**
   - Colonnes : Filename, Dur, BPM, Key, Energy, State. State vaut `analysed`, `pending`, `failed` ou `missing`.
   - Légende au-dessus : « 14 tracks · 1:12:30 ».
   - Boutons : « ← Remove », « Analyze selection » (remplace « Analyze »).
3. **Proposals + Set list**
   - Réglages : durée (min), courbe (`build`, `wave`, `peak_middle`, `constant`, `all`), bouton « Propose ».
   - Une liste de variantes, une ligne par variante : courbe, durée effective / cible (par exemple `58:40 / 60:00`), score global, pire transition (par exemple `3→4 · 52`).
   - Un clic sur une variante affiche son ordre dans la table Set list, en aperçu grisé et non enregistré, et trace sa courbe dans l'onglet Overview.
   - Bouton « Use this proposal » : copie l'ordre dans la set list.
   - La table Set list et ses boutons (Up, Down, Remove) restent comme aujourd'hui.

### Barre du haut

Project (combobox), « New project… », « Project summary », puis deux nouveaux boutons : « Reset project… » et « Clear analysis cache… » (voir la section 3).

### Workflow

- L'étape `analyze` garde sa clé et devient « Select and analyze the tracks ».
- Nouvel indice : « Pick tracks in the Library, add them to the Selection, then 'Analyze selection' (cached tracks are instant). »
- L'indice de `setlist` devient : « Click 'Propose', compare the variants, then 'Use this proposal' and adjust the order. »

## 2. Données et algorithme

### `project.json`, version 3

Nouveaux champs :

```json
{
  "version": 3,
  "selection": ["C:/Music/Mixes/track a.wav", "..."],
  "proposals": {
    "params": {"duration_min": 60, "curve": "all", "mix_bars": 8},
    "created": "2026-09-13T21:04:00",
    "variants": [
      {
        "curve": "build",
        "order": ["C:/Music/Mixes/track a.wav", "..."],
        "effective_seconds": 3520.4,
        "target_seconds": 3600,
        "cost": 1.84,
        "score": 81,
        "transition_scores": [88, 74, 52, "..."],
        "worst": {"index": 2, "score": 52}
      }
    ]
  }
}
```

- `tracks` : les fiches d'analyse des morceaux de la **sélection** uniquement (format de `PlaylistManager.track_record`).
- `proposals` vaut `null` quand il n'existe aucune proposition.
- `set_list` ne change pas de forme.

Règles `SetProject` :

- `add_to_selection(paths)` ajoute les chemins sans doublons, dans l'ordre reçu. Il met `proposals` à `null` et invalide depuis `analyze`.
- `remove_from_selection(paths)` retire les chemins de `selection`, de `tracks` et de `set_list`, met `proposals` à `null` et invalide depuis `analyze`.
- `set_proposals(data)` enregistre les propositions.
- `use_proposal(index)` fait `set_order(variants[index].order)` : il marque l'étape `setlist` comme faite, avec `curve` et `score` dans ses détails, et invalide ce qui suit.
- `selection_files()` remplace `source_files()` pour l'analyse. `source_files()` est conservé pour la migration.

### Migration v2 → v3

Elle se fait au `load()`, puis est enregistrée au prochain `save()`. Si la version est inférieure à 3, que `selection` est absent ou vide et que `source/` contient des fichiers audio :

- `selection = source_files()` ;
- `proposals = null` ;
- `version = 3`.

Tout le reste est conservé : `tracks`, `set_list`, les étapes et les résultats.

### Nouveau module `set_proposer.py`

Fonctions pures, sans Tkinter ni fichiers audio.

```python
def propose(tracks: List[Dict], target_seconds: float, curve: str = "build",
            mix_bars: int = 8, variants: int = 3, beam_width: int = 50,
            tolerance: float = 0.03) -> List[Dict]
def energy_target(position: float, curve: str) -> float   # position 0..1 -> 0..1
def transition_cost(a: Dict, b: Dict) -> float
def overlap_seconds(track: Dict, mix_bars: int) -> float
```

**Courbe fonction du temps.** Soient `lo` et `hi` les énergies min et max de la sélection (`PlaylistManager._energy_value`). L'énergie visée pour un morceau est `lo + (hi - lo) * energy_target(p, curve)`, où `p` est la position de son milieu temporel dans le set divisée par la durée de référence. La durée de référence est la plus petite des deux valeurs entre la cible et la durée effective de toute la sélection.

| courbe | `energy_target(p)` |
|---|---|
| `build` | `p` |
| `peak_middle` | `1 - abs(2p - 1)` |
| `wave` | `0.5 - 0.5 * cos(4πp)` (2 vagues, départ bas) |
| `constant` | `0.5` |

Coût d'énergie d'un morceau : `abs(énergie - visée) / (hi - lo)`. Il vaut 0 si `hi == lo`.

**Coût de transition.** `transition_cost` reprend exactement les pénalités actuelles de `suggest_playlist_order` :

- `0.03 × max(0, |ΔBPM| - 3)` si les deux morceaux ont un beat et un BPM ;
- `+ (100 - key_compatibility_score) / 100 × 0.5`.

`suggest_playlist_order` est refactorisé pour appeler cette fonction. Son comportement ne change pas, et ses tests existants doivent continuer de passer.

**Chevauchement.** `overlap_seconds(t, mix_bars) = mix_bars × 4 × 60 / bpm`, avec une valeur par défaut de 120 BPM si le BPM est absent ou nul. La durée effective d'une séquence est la somme des durées moins le chevauchement de chaque transition, calculé sur le morceau entrant.

**Recherche en faisceau.**

1. Un état est une séquence partielle, avec son coût cumulé (énergie + transitions) et sa durée effective.
2. Initialisation : un état par morceau. On garde les `beam_width` meilleurs.
3. Extension : on ajoute chaque morceau non utilisé dont l'ajout garde la durée effective ≤ `target × (1 + tolerance)`.
4. Un état qui ne peut plus être étendu est **terminé**. Son coût final est le coût cumulé plus `2.0 × |cible - effective| / cible`. Cette pénalité n'est pas appliquée quand la sélection entière est plus courte que la cible et que l'état utilise tous les morceaux.
5. À chaque profondeur, on garde les `beam_width` meilleurs états non terminés. Pour comparer des états de longueurs différentes, le tri se fait sur le coût moyen par morceau. Les états terminés vont dans un pool.
6. Si deux coûts sont égaux, on départage par l'ordre des chemins, pour rester déterministe.

**Diversité.** On parcourt le pool trié par coût final. Une séquence est retenue si, pour chaque variante déjà retenue, la part de ses enchaînements (paires ordonnées A→B) déjà présents dans cette variante est inférieure à 70 %. On s'arrête à `variants` séquences. S'il n'y en a pas assez, on complète avec les meilleures restantes, sans contrainte.

**Score affiché.**

- `transition_scores[i]` vaut `compatibility_from_features(ordre[i], ordre[i+1])["score"]`, arrondi.
- `score` est la moyenne des transitions, arrondie. Il vaut 100 s'il n'y a qu'un morceau.
- `worst` est la transition au score minimal.

**Courbe `all`.** Le GUI appelle `propose(..., curve=c, variants=1)` pour chacune des 4 courbes, puis affiche les 4 variantes triées par score.

**Cas limites.**

| cas | comportement |
|---|---|
| sélection vide | `ValueError("No analysed tracks in the selection")`, affichée en message et au Journal |
| 1 morceau | une variante de ce morceau |
| morceaux `pending`, `failed` ou `missing` | exclus, avec un avertissement au Journal qui donne le nombre et les noms |
| sélection plus courte que la cible | tous les morceaux utilisés, écart visible dans la durée affichée |

**Remplacement.** `_select_for_duration` est supprimé. `PlaylistManager.create_set_list(duration_minutes, energy_curve)` garde sa signature, car les CLI l'utilisent (`mixxx_export.py`, `mix_enhanced.py`). Il devient une enveloppe qui appelle `set_proposer.propose(self.tracks, duration_minutes * 60, energy_curve, variants=1)` et renvoie la première variante sous forme de liste de fiches. L'ancien nom de courbe `build_up` est traduit en `build`. `create_energy_based_set` passe par `create_set_list` sans changement. Le calcul tourne dans un thread, comme l'analyse.

### Nouveau module `library.py`

```python
def scan(folder: str, progress: Optional[Callable[[int, int, str], None]] = None) -> List[Dict]
def read_duration(path: str) -> Optional[float]
```

- `scan` utilise `set_project.audio_files_in(folder, recursive=True)`. Chaque entrée contient `file_path`, `filename`, `duration`, `bpm`, `key`, `energy_level` et `analysed`.
- La durée vient des features en cache si elles existent. Sinon elle vient de `read_duration` : `soundfile.info(path).duration`, qui renvoie `None` en cas d'erreur, y compris un format non supporté.
- BPM, tonalité et énergie viennent de `get_store().get(path, "features")`.
- Le GUI lance `scan` dans un thread et remplit la table par lots de 50.

## 3. Réinitialisation, cache et journal

### « Reset project… » : `SetProject.reset(delete_imported: bool = False) -> Dict[str, int]`

- Remet à zéro `selection`, `tracks`, `set_list` (listes vides), `proposals`, `transitions`, `premaster` (`null`) et toutes les étapes (non faites).
- Supprime le contenu de `premaster/` et `exports/`, en gardant les dossiers.
- Si `delete_imported` est vrai, supprime aussi le contenu de `source/` et vide `imported`.
- Conserve `name`, `created`, `options`, `notes`, `source_folder`, ainsi que le cache d'analyse.
- Renvoie `{"files_deleted": n, "bytes_deleted": b}`.
- `SetProject.reset_preview()` renvoie les mêmes compteurs sans rien supprimer. Il les donne séparément pour premaster/exports et pour source/.

**Confirmation GUI.** Elle affiche ce qui sera effacé et ce qui sera conservé, avec le nombre de fichiers et la taille. Une case « Also delete imported copies in source/ (n files, x MB) » n'apparaît que si `source/` contient des fichiers.

### « Clear analysis cache… »

- Nouvelle méthode `AnalysisStore.clear_paths(paths: List[str]) -> int`, qui supprime toutes les entrées de ces chemins, tous types confondus, et renvoie le nombre de lignes supprimées.
- Le GUI l'appelle sur la sélection, puis `invalidate_from("analyze")` et `mark("analyze", done=False)`. Les propositions sont mises à `null`, et les fiches `tracks` repassent en `pending`.
- La confirmation annonce le nombre de morceaux concernés. Après l'opération, le nombre d'entrées supprimées est affiché et journalisé.
- Dans l'onglet Configuration, le bouton « Clear whole cache… » appelle `AnalysisStore.clear()` après confirmation, puis rafraîchit les statistiques.

### Onglet « Log » : nouveau module `app_log.py`

```python
def install(log_dir: str, max_lines: int = 5000) -> "LogBuffer"
def uninstall() -> None   # restores stdout/stderr, hooks, removes handlers (tests)
class LogBuffer(logging.Handler):
    def records(self, min_level: int = logging.DEBUG) -> List[logging.LogRecord]
    def drain(self) -> List[logging.LogRecord]   # new records since last drain
    def clear(self) -> None
```

**Capture.** `install` :

- attache au logger racine `dynamix` un `LogBuffer`, en mémoire avec une deque de `max_lines`, et un `RotatingFileHandler` vers `<DynaMix home>/logs/dynamix.log` (1 Mo × 5) ;
- remplace `sys.stdout` et `sys.stderr` par des flux qui découpent par ligne et journalisent (INFO pour stdout, ERROR pour stderr). Ils écrivent aussi dans le flux d'origine s'il existe (`pythonw` : `None`) ;
- pose `threading.excepthook` et `sys.excepthook`, qui journalisent en ERROR avec la trace complète.

Le GUI pose `root.report_callback_exception`, qui fait de même. Les nouveaux modules utilisent `logging.getLogger("dynamix.<module>")` plutôt que `print`. Les `print` existants restent capturés via stdout.

**Onglet** (dernier onglet principal, créé dans `gui.py`) :

- zone `Text` en lecture seule, lignes au format `HH:MM:SS LEVEL message`, tags de couleur pour WARNING (orange) et ERROR/CRITICAL (rouge) ;
- filtre de niveau : « All », « Warnings and errors », « Errors » ;
- boutons « Copy » (tout le texte filtré vers le presse-papier), « Clear view » (`LogBuffer.clear`) et « Open log folder » (`os.startfile` sous Windows) ;
- un `after(200)` appelle `drain()`, ajoute les lignes et fait défiler vers le bas si la vue était déjà en bas ;
- tant que l'onglet n'est pas affiché, chaque WARNING ou ERROR incrémente le compteur du titre, « Log (3 ⚠) ». Le compteur revient à zéro à l'affichage de l'onglet ;
- messages explicites pour : scan de la bibliothèque (nombre de fichiers, durée), analyse (`cached / analysed / failed` avec le nom et l'erreur de chaque échec), propositions (paramètres, nombre de variantes, meilleur score), reset et vidage du cache (compteurs).

## 4. Tests

`unittest`, lancés par `python -m pytest tests/ -v`. L'interface n'a pas de tests automatisés : elle est vérifiée en lançant l'app.

- **`tests/test_set_proposer.py`** (fiches synthétiques) :
  - durée effective ≤ cible × 1,03, chevauchements compris ;
  - sélection plus courte que la cible : tous les morceaux sont utilisés ;
  - `build` donne une énergie croissante sur des morceaux compatibles ;
  - `peak_middle` place l'énergie max dans le tiers central ;
  - deux morceaux à tonalités incompatibles ne sont pas adjacents quand une alternative de même énergie existe ;
  - les variantes respectent le seuil de 70 % de paires communes ;
  - deux appels identiques donnent le même résultat ;
  - sélection vide → `ValueError`, 1 morceau → 1 variante ;
  - `overlap_seconds` utilise 120 BPM par défaut ;
  - valeurs de `energy_target` aux positions 0, 0,5 et 1.
- **`tests/test_playlist_manager.py`** : les tests de `suggest_playlist_order`, `create_set_list` et `create_energy_based_set` doivent continuer de passer. Si une assertion dépendait du comportement exact de l'ancienne sélection par durée, elle est réécrite pour vérifier les propriétés : durée respectée et courbe suivie.
- **`tests/test_set_project.py`** :
  - ajout et retrait dans la sélection, avec leurs effets sur `tracks`, `set_list`, `proposals` et les étapes ;
  - `use_proposal` ;
  - migration v2 → v3 ;
  - `reset()` et `reset_preview()` : fichiers supprimés, dossiers conservés, `source/` intact sauf si `delete_imported` est vrai, champs conservés.
- **`tests/test_library.py`** :
  - dossier temporaire avec deux petits WAV générés par `soundfile`, dont un dans un sous-dossier, et un fichier `.txt` ignoré ;
  - durées lues ;
  - fusion avec un cache factice (`DYNAMIX_HOME` temporaire) ;
  - fichier illisible → durée `None`.
- **`tests/test_analysis_store.py`** : `clear_paths` supprime seulement les chemins donnés, tous types confondus.
- **`tests/test_app_log.py`** :
  - le buffer garde au plus `max_lines` lignes ;
  - `drain` ne renvoie que les nouvelles lignes ;
  - stdout donne INFO et stderr donne ERROR ;
  - une exception levée dans un thread est journalisée avec sa trace ;
  - le fichier de log est écrit ;
  - les flux et hooks d'origine sont restaurés en fin de test (`uninstall()`).

## Fichiers touchés

| fichier | changement |
|---|---|
| `set_proposer.py` | nouveau |
| `library.py` | nouveau |
| `app_log.py` | nouveau |
| `set_project.py` | schéma v3, sélection, propositions, migration, `reset`, `reset_preview`, libellés et indices |
| `playlist_manager.py` | extraction de `transition_cost`, suppression de `_select_for_duration`, `create_set_list` délègue à `set_proposer` |
| `analysis_store.py` | `clear_paths` |
| `config.py` | clé `library_folder` |
| `set_builder.py` | onglet Tracks en 3 colonnes, propositions, boutons reset et cache, champ bibliothèque et « Clear whole cache… » en Configuration |
| `gui.py` | `app_log.install` au démarrage, `report_callback_exception`, onglet Log |
| `README.md`, `GUI_README.md` | nouveau flux |
| `tests/…` | voir la section 4 |

## Hors périmètre : chantier 2, FX de transition

L'idée à concevoir séparément :

- un dossier de samples FX, souvent atonaux, pour adoucir une transition abrupte ;
- des effets « freeze » : boucler 1, 2 ou 4 temps de la fin du morceau sortant avec un effet ;
- des effets cutoff/résonance.

Question ouverte avant de le concevoir : faut-il des recommandations dans la fiche de transitions et en cues Mixxx, des effets incrustés dans l'audio pré-masterisé, ou un rendu du mix complet ?
