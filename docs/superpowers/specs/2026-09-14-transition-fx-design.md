# FX de transition : freeze/roll, filtres, écho, samples, pré-écoute en boucle

**Date :** 2026-09-14
**Statut :** design validé, en attente de relecture de la spec
**Chantier :** 2 (suite de `2026-09-13-library-selection-proposals-design.md`)

## Objectif

Adoucir les transitions abruptes d'un set en ajoutant des FX calés sur le rythme :
- un **freeze / roll** qui boucle la fin du morceau sortant ;
- des **balayages de filtre** passe-haut, passe-bas ou passe-bande, avec résonance ;
- un **écho** synchronisé au tempo ;
- des **samples FX** pris dans un dossier dédié (risers, impacts, sweeps, souvent atonaux).

Principes décidés :
1. **Recommandation puis application.** L'utilisateur choisit et règle les FX de chaque transition, les écoute en boucle dans DynaMix, puis les **incruste dans des copies**. Les fichiers de la bibliothèque et du pré-master ne sont jamais modifiés.
2. **Choix manuel.** Aucune suggestion automatique : l'utilisateur choisit, DynaMix calcule le placement et la synchronisation.
3. **Recettes non destructives.** Les FX sont stockés comme des réglages dans `project.json`. Le rendu repart toujours d'une base propre, donc on peut empiler, désactiver, modifier ou retirer un FX et recalculer.
4. **Plusieurs FX par transition.** Ils s'empilent dans l'ordre choisi et peuvent déborder sur le début du morceau entrant.

Les libellés de l'interface restent en anglais, comme le reste de l'app.

## 1. Modèle de transition, données et rendu

### Repères temporels

Pour une transition entre le morceau sortant A et le morceau entrant B, la fiche de transitions existante (`TransitionPlanner`) donne `A.outro_start`, `A.outro_end`, `B.intro_start` et `B.intro_end`. L'Auto DJ de Mixxx superpose ces deux zones.

- **Jonction** : le moment où B entre. Elle vaut `A.outro_start` dans le temps de A et `B.intro_start` dans le temps de B. Elle est calée sur le temps le plus proche de la grille de chaque morceau, et un réglage `nudge_ms` (±50 ms, par transition) permet de la corriger à l'oreille.
- **Positions des FX** : toutes sont exprimées **en temps musicaux par rapport à la jonction**, en s'appuyant sur les vraies grilles de temps de A et de B.
- **Règle de débordement** : un FX est écrit dans la copie de A tant que A est audible, c'est-à-dire jusqu'à la fin de A (`A.outro_end`, ou la fin du freeze s'il y en a un). Tout ce qui dépasse la fin de A est ajouté à la copie de B au même instant musical, à `B.intro_start + (t − jonction_A)`. Rien n'est ainsi joué en double pendant le crossfade.
- **Freeze** : il remplace la fin de A à partir du point de capture. Les repères de la copie de A sont recalculés : `outro_start` = point de capture et `outro_end` = fin du freeze, traîne comprise.
- **Durée de l'intro de B** : la paire rendue garde l'intro de B au moins aussi longue que l'outro de A (`B.intro_end ≥ jonction_B + (A.outro_end − jonction_A)`), pour que Mixxx, qui termine la transition à `A.outro_end`, fasse entrer B sur la jonction.

### Données (`project.json`, bloc `fx`)

```json
"fx": {
  "transitions": {
    "C:/Music/Mixes/a.wav|C:/Music/Mixes/b.wav": {
      "nudge_ms": 0,
      "effects": [
        {"type": "freeze", "enabled": true, "...": "réglages, section 2"},
        {"type": "sample", "enabled": true, "...": "..."}
      ]
    }
  },
  "render": {
    "at": "2026-09-14T21:00:00",
    "results": [
      {"input": "C:/.../premaster/a.wav", "source": "C:/Music/Mixes/a.wav",
       "output": "C:/.../fx/a.wav",
       "intro_start": 0.0, "intro_end": 12.0, "outro_start": 231.5, "outro_end": 247.5,
       "limiter_reduction_db": 1.2}
    ]
  }
}
```

- **Clé d'une transition** : `"<chemin A>|<chemin B>"`, avec les chemins originaux de la set list. Si l'utilisateur réordonne le set et que A et B restent voisins, leurs FX sont conservés.
- **Recettes inactives** : les recettes d'une paire qui n'est plus voisine restent stockées, sont marquées **inactives** dans la fenêtre et ne sont pas rendues. Un bouton permet de les supprimer.
- **`render`** vaut `null` tant que rien n'a été rendu, ou dès que le rendu n'est plus valide.
- **`SetProject`** (nouvelles méthodes) :
  - `fx_key(a, b)` ;
  - `fx_transition(a, b)` (crée l'entrée vide si besoin) ;
  - `set_fx_effects(a, b, effects)` ;
  - `set_fx_nudge(a, b, ms)` ;
  - `active_fx_pairs()` (paires voisines de la set list qui ont au moins un FX activé) ;
  - `inactive_fx_pairs()` ;
  - `remove_fx(a, b)` ;
  - `set_fx_render(results)` ;
  - `fx_map()` (chemin original → résultat de rendu dont la copie existe sur le disque).
  - Modifier une recette met `render` à `null` et remet l'étape `fx` à « non faite ».

### Étape du workflow

- Nouvelle entrée dans `STEPS`, insérée après `premaster` : `("fx", "Add transition FX (optional)", False)`.
- Nouvel indice : « Optional: 'Transition FX' adds freezes, filter sweeps, echoes and samples on chosen transitions, rendered into the project's fx folder. »
- `invalidate_from("setlist" | "transitions" | "premaster")` met aussi `fx.render` à `null` et invalide l'étape `fx`. **Les recettes sont conservées.**
- `invalidate_from("analyze")` suit la même règle, puisque `setlist` suit `analyze`.
- Les anciens projets sans bloc `fx` le reçoivent au chargement, avec `{"transitions": {}, "render": null}`.

### Rendu (« Apply all FX »)

1. **Base** : pour chaque morceau de la set list, la copie `premaster/` si elle existe (`premaster_map()`), sinon l'original. La base est lue, jamais écrite.
2. **Morceaux concernés** : seuls ceux qui ont au moins un FX actif, comme sortant ou comme entrant, reçoivent une copie.
3. **FX appliqués** : sur chaque copie, d'abord les **FX côté entrant** de la transition précédente (y compris le débordement de cette transition), puis les **FX côté sortant** de la transition suivante. Dans une transition, les FX s'enchaînent dans l'ordre de la pile.
4. **Traitement par région** : seules les zones autour des jonctions sont traitées (depuis le point le plus tôt touché par un FX sortant jusqu'à la fin de A ; depuis le début de B jusqu'au dernier point touché par un FX entrant ou un débordement). Elles sont ensuite recollées dans le morceau entier.
5. **Limiteur final** : passe `mastering.true_peak_limiter(x, fs, ceiling_db=-1.0)` à −1 dBTP, sans renormalisation, donc le LUFS du pré-master est conservé. Cette fonction ne renvoie que le signal : le rendu calcule `limiter_reduction_db = max(0, crête avant − crête après)` en dB, sur les échantillons (pas en true peak). Si la réduction dépasse 3 dB, un avertissement est journalisé.
6. **Écriture** dans `<projet>/fx/`, au format de sortie configuré (`output_format`, mêmes règles que le pré-master pour les formats non encodables), en conservant la fréquence d'échantillonnage. Les repères intro/outro recalculés sont enregistrés dans `fx.render.results`, et l'étape `fx` est marquée faite avec `count`.

### Utilisation des copies

- **`SetBuilderMixin._with_premastered`** devient `_with_rendered(tracks)`. Pour chaque morceau, il prend dans l'ordre la copie `fx/` (`fx_map()`), sinon `premaster/`, sinon l'original. Il renvoie les fiches modifiées et le nombre de copies de chaque sorte.
- **Playlist M3U** : utilise ces fiches.
- **Export Mixxx (GUI)** : utilise ces fiches, et pour les copies `fx/`, les repères intro/outro **issus de `fx.render.results`** au lieu de ceux du planificateur.
- **`mixxx_export.py --project`** : même ordre de priorité et mêmes repères. `--originals` ignore toujours les copies.
- **Reset project…** : vide aussi le contenu de `fx/`, et remet `fx` à `{"transitions": {}, "render": null}`. `reset_preview()` compte les fichiers de `fx/` dans `outputs`.

## 2. Moteur DSP (`transition_fx.py`)

Le module est fait de fonctions pures en numpy et scipy, sans Tkinter : chaque fonction reçoit des tableaux et en renvoie. L'audio est traité en `float32` stéréo (`(n, 2)`, un fichier mono est dupliqué), à la fréquence d'échantillonnage native de chaque fichier.

### Grille rythmique

- `beat_grid(path) -> Dict` renvoie `{"beats": [s…], "bpm": float, "has_beat": bool}`. Il est mis en cache dans `AnalysisStore`, nouveau type `beats`, calculé avec `AudioAnalyzer.analyze_beat_grid()`.
- `snap_to_beat(beats, t)` renvoie le temps de grille le plus proche.
- `beat_time(beats, anchor_index, offset_beats)` convertit un nombre de temps (négatif, positif ou fractionnaire) en secondes : il suit la grille réelle et interpole à l'intérieur d'un temps. Au-delà des bords de la grille, il extrapole avec la durée médiane d'un temps.
- **Repli** quand la grille est vide ou que le morceau n'a pas de rythme : grille régulière à 60/BPM (BPM de l'analyse, sinon 120). Un avertissement est journalisé et affiché dans la fenêtre.

### Contexte de transition

```python
@dataclass
class TransitionContext:
    a: np.ndarray            # outgoing region (n, 2), starts at a_offset seconds in track A
    a_sr: int
    a_offset: float
    a_beats: List[float]     # beat times of track A (absolute seconds)
    junction_a: float        # absolute seconds in A (snapped + nudge)
    a_end: float             # absolute seconds where A stops being audible (updated by freeze)
    b: np.ndarray            # incoming region (n, 2), starts at b_offset seconds in track B
    b_sr: int
    b_offset: float
    b_beats: List[float]
    junction_b: float
    overflow: np.ndarray     # (n, 2) at a_sr, sample 0 = a_end; mixed into B at the same musical instant
    warnings: List[str]
```

- `apply_effects(ctx, effects, samples_root) -> ctx` applique les FX activés, dans l'ordre.
- `mix_overflow(ctx) -> ctx` rééchantillonne le débordement à `b_sr` (`scipy.signal.resample_poly`) et l'ajoute à `b` à `junction_b + (a_end − junction_a)`.
- Chaque raccord (coupe, boucle, collage) reçoit un fondu de 5 ms.

### FX et réglages

**`freeze`** (sortant)
| clé | type | valeurs, défaut |
|---|---|---|
| `capture_offset_beats` | int | −16..0, défaut 0 (point de capture = jonction) |
| `steps` | liste de `{"beats": 4 \| 2 \| 1 \| 0.5, "repeats": int ≥ 1}` | défaut `[{"beats": 1, "repeats": 4}]` |
| `loop_filter` | objet filtre (mêmes clés que `filter`, sans `side`) ou `null` | `null` |
| `loop_echo` | objet écho (`delay_beats`, `feedback`, `mix`, `damping_hz`) ou `null` | `null` |
| `fade_db` | float | −60..0, défaut 0 (gain à la fin du freeze, rampe linéaire en dB) |
| `tail_beats` | int | 0..8, défaut 0 |
| `gain_db` | float | −24..+6, défaut 0 |

- **Boucle** : chaque étape répète `repeats` fois le segment des `beats` derniers temps avant le point de capture, bornes prises sur la grille de A.
- **Assemblage** : A est coupé au point de capture, puis reçoit la succession des étapes et la traîne.
- **Effets sur la boucle** : `loop_filter`, `loop_echo` et `fade_db` couvrent toute la durée du freeze. La traîne prolonge les effets sur un signal d'entrée silencieux.
- **Limite** : la durée totale ne dépasse pas 64 temps.
- **Repères** : `a_end` devient la fin du freeze.

**`filter`** (sortant ou entrant)
| clé | type | valeurs, défaut |
|---|---|---|
| `side` | str | `outgoing` \| `incoming` |
| `kind` | str | `highpass` \| `lowpass` \| `bandpass` |
| `start_hz`, `end_hz` | float | 20..20000 (passe-bande : fréquence centrale) |
| `width_octaves` | float | passe-bande uniquement, 0.3..4, défaut 1 |
| `resonance` | float | Q de 0.7 à 12, défaut 0.707 |
| `beats` | int | 2 \| 4 \| 8 \| 16, défaut 8 |
| `curve` | str | `exponential` (interpolation log de la fréquence) \| `linear`, défaut `exponential` |

- **Sortant** : le balayage va de `start_hz` à `end_hz` pendant les `beats` temps qui précèdent la jonction. Le filtre reste ensuite à `end_hz` jusqu'à `a_end`.
- **Entrant** : le filtre est à `start_hz` sur la jonction de B et va à `end_hz` pendant les `beats` temps suivants.
- **Implémentation** :
  - biquad RBJ (cookbook) en forme directe II transposée, coefficients recalculés tous les 256 échantillons, état conservé par canal ;
  - fréquence limitée à `0.45 × sr` ;
  - passe-bande en « constant 0 dB peak gain », avec le Q dérivé de `width_octaves` puis multiplié par `resonance / 0.707`.

**`echo`** (sortant)
| clé | type | valeurs, défaut |
|---|---|---|
| `start_offset_beats` | int | −16..0, défaut −4 |
| `delay_beats` | float | 0.25 \| 0.5 \| 0.75 \| 1, défaut 0.5 |
| `feedback` | float | 0..0.85, défaut 0.5 |
| `mix` | float | 0..1, défaut 0.5 |
| `damping_hz` | float | 1000..20000, défaut 6000 (coupe-haut à un pôle dans la réinjection) |

- **Zone** : l'écho s'applique de `jonction + start_offset_beats` jusqu'à `a_end`.
- **Délai** : `delay_beats × durée médiane d'un temps` autour de la jonction.
- **Traîne** : elle continue après `a_end` jusqu'à passer sous −60 dB, 16 temps au maximum, et part dans le débordement.

**`sample`**
| clé | type | valeurs, défaut |
|---|---|---|
| `file` | str | chemin absolu dans le dossier des samples FX |
| `anchor` | str | `end_at_junction` \| `start_at_junction` \| `center_on_junction` |
| `offset_beats` | float | −16..16, défaut 0 |
| `gain_db` | float | −24..+6, défaut −3 |
| `fade_in_ms`, `fade_out_ms` | int | 0..2000, défaut 5 |

- **Lecture** : fichier lu avec soundfile, mono dupliqué en stéréo, rééchantillonné à `a_sr` si besoin. La durée maximale est de 30 s, au-delà le fichier est refusé avec un message.
- **Tempo** (ajout du 2026-09-14) : réglages `tempo` (`varispeed` par défaut, `stretch`, `off`) et `sample_bpm` (40..250, sinon lu dans le nom du fichier, par exemple « 143BPM »). Le rapport tempo local de A autour de la jonction ÷ BPM du sample est appliqué par rééchantillonnage (la hauteur suit) ou par `librosa.effects.time_stretch` (hauteur conservée). Sans BPM connu, le sample est joué tel quel ; un rapport hors 0,5..2 est signalé et le sample est joué tel quel.
- **Répétitions** (ajout du 2026-09-14) : réglage `repeats` (1..16, défaut 1). Le sample calé au tempo est répété bout à bout ; les fondus s'appliquent au début et à la fin de l'ensemble, l'ancre porte sur l'ensemble (avec `end_at_junction`, la dernière répétition finit sur la jonction). Au-delà de 64 s au total, le nombre de répétitions est réduit avec un avertissement.
- **Placement** : il se fait dans le temps de A, puis la règle de débordement s'applique.

### Validation et erreurs

- `validate_effect(effect) -> List[str]` renvoie des messages lisibles : clé inconnue, valeur hors bornes, fichier introuvable.
- Le rendu et la pré-écoute refusent un FX invalide, en affichant le message et en le journalisant, sans arrêter les autres transitions pendant « Apply all ».

## 3. Interface

### Accès

- **Workflow** : bouton « Transition FX » pour l'étape `fx`.
- **Fenêtre de la fiche de transitions** : bouton « Transition FX... ».
- **Prérequis** : il faut que `project.data["transitions"]` existe. Sinon, le message « Plan the transitions first (step 3) » s'affiche.

### Fenêtre « Transition FX » (`fx_window.py`, classe `TransitionFxWindow(tk.Toplevel)`)

- **Liste des transitions** : colonnes `#`, `A → B`, `Score`, `FX`, `State`. `State` vaut `✓` (rendu à jour), `*` (modifié depuis le rendu) ou vide (aucun FX).
  - Sous la liste : jonction A et B en m:ss, BPM A → B, tonalités, durée d'un temps, avertissements de grille.
  - Réglage « Nudge (ms) » de −50 à +50.
  - Section repliable « Inactive FX », avec le bouton « Remove ».
- **Pile de FX** : liste (case activé, type, résumé) et boutons « Add ▾ » (Freeze, Filter, Echo, Sample), « Remove », « ▲ », « ▼ », « Duplicate ».
- **Panneau de réglages** : champs propres au type de FX, avec les clés de la section 2.
  - **Freeze** : tableau des étapes (Beats, Repeats) avec « + » et « − », et deux sous-cadres « Loop filter » et « Loop echo », chacun avec une case pour l'activer.
  - **Sample** : liste des samples du dossier configuré, avec un filtre par nom, la durée de chaque fichier et un bouton « ▶ Sample » pour l'écouter seul.
- **Enregistrement** : chaque modification enregistre aussitôt la recette (`set_fx_effects`, puis `project.save()`) et relance la pré-écoute si elle est en cours.
- **Barre du bas** :
  - « ▶ Preview (loop) » ;
  - « ■ Stop » ;
  - « Length: » `short` | `long` ;
  - « Apply all FX » ;
  - un libellé d'état.

### Pré-écoute

- **Extrait** :
  - `short` : de 8 temps avant la jonction à 8 temps après `a_end` ;
  - `long` : de 20 s avant la jonction à 10 s après la jonction de B.
- **Contenu** :
  - région de A avec ses FX ;
  - région de B avec ses FX entrants et le débordement ;
  - superposition sur la zone de crossfade, avec un fondu à puissance constante (cosinus/sinus) de `jonction_A` à `a_end` pour A et de `jonction_B` à `B.intro_end` pour B, comme dans Mixxx ;
  - limiteur.
- **Calcul et lecture** : l'extrait est calculé dans un thread (résultat appliqué avec `root.after`), puis écrit alternativement dans `<DynaMix home>/tmp/preview_a.wav` et `preview_b.wav`, pour ne jamais réécrire le fichier en cours de lecture.
- **Lecture en boucle** : `winsound.PlaySound(path, SND_FILENAME | SND_ASYNC | SND_LOOP)`.
  - « Stop », la fermeture de la fenêtre ou un nouvel extrait appellent `PlaySound(None, 0)`.
  - Une modification pendant la lecture relance le calcul après 400 ms sans nouveau changement.
- **Hors Windows** : `os.startfile` ou `open` / `xdg-open`, sans boucle, avec un message.
- **Lecteur remplaçable** : la lecture passe par une petite interface `Player` (`play_loop(path)`, `stop()`), que le test GUI remplace par un bouchon.

### Apply all FX

- **Calcul** : le rendu (section 1) tourne dans un thread, la progression s'affiche dans la barre d'état et le Journal, et les erreurs passent par `_report_error`.
- **Garde** : le résultat ne s'applique qu'au projet d'origine (même garde que les autres workers).
- **Fin du rendu** :
  - appel de `set_fx_render(results)` et `mark("fx", count=...)` ;
  - l'état de la liste passe à `✓` ;
  - mise à jour de l'Overview et de la Set map.

### Configuration

- **Nouvelle clé** `fx_samples_folder`, vide par défaut, avec la ligne « FX samples folder: » et un bouton « Browse ».
- **Scan** : `library.scan`, déjà récursif et limité aux extensions audio, est réutilisé sur ce dossier. Les fichiers de plus de 30 s sont listés mais grisés.

### Set map

- `charts.set_timeline(profiles, transitions, fx_labels=None)` : `fx_labels` associe l'indice d'une transition à un texte court (par exemple « freeze · sample »), affiché en petit au-dessus de la ligne de jonction.
- Le GUI passe les FX actifs de chaque transition.

## 4. Hors périmètre et risques

**Hors périmètre**
- Time-stretch ou pitch-shift des samples.
- Rendu du mix complet en un seul fichier.
- Suggestion automatique de FX.
- Hotcues ou effets Mixxx en live.
- Détection des premiers temps de mesure ou des phrases.
- Réverb.
- Pré-écoute en boucle hors Windows.

**Risques et traitements**

| risque | traitement |
|---|---|
| grille imprécise (freeze qui boite, tempo détecté du simple au double) | boucles calées sur la grille réelle, fondus de 5 ms, BPM et durée d'un temps affichés, `nudge_ms` |
| clics aux raccords et pendant les balayages | fondus, filtre recalculé tous les 256 échantillons avec état conservé, tests de continuité |
| saturation quand des FX se superposent | limiteur à −1 dBTP, gain par FX, avertissement si la réduction dépasse 3 dB |
| rendu lent | traitement par région, morceaux sans FX non recopiés |
| cues Mixxx décalées après un freeze | repères recalculés, enregistrés et utilisés par l'export, avec un test de cohérence |
| recettes orphelines après une modification de la set list | clé par paire, section « Inactive FX » |

## 5. Tests

Tous les tests sont `unittest`, lancés avec `venv/Scripts/python.exe -m unittest discover -s tests -p "<fichier>"`.

- **`tests/test_transition_fx.py`** (signaux synthétiques, 44,1 kHz, grille régulière à 120 BPM) :
  - `beat_time` : interpolation, extrapolation, repli sans grille ;
  - **freeze** : durée exacte des étapes (`4×1 → 2×2 → 1×4`), boucle identique au segment capturé (hors fondus), aucun saut d'échantillon au-delà d'un seuil aux raccords, `a_end` mis à jour, `fade_db` appliqué ;
  - **filtre passe-haut sortant** : sinus à 100 Hz atténué de plus de 20 dB après la jonction, niveau inchangé avant le début du balayage ;
  - **filtre passe-bas entrant** : ouverture progressive ;
  - **passe-bande** : un sinus à la fréquence centrale passe, une octave au-dessus il est atténué ;
  - **résonance** : Q = 8 produit un gain supérieur à 6 dB à la coupure ;
  - **écho** : une impulsion donne des répétitions espacées du délai, décroissantes, avec une traîne envoyée dans le débordement ;
  - **sample** : les trois ancrages placent le début ou la fin au bon échantillon, la découpe à `a_end` est exacte, et le débordement est rééchantillonné quand `b_sr` est différent de `a_sr` ;
  - `validate_effect` : messages attendus sur des valeurs hors bornes ;
  - **limiteur** : le signal final reste sous −1 dBTP.
- **`tests/test_fx_render.py`** : rendu complet sur 3 petits WAV générés dans un dossier temporaire, avec `DYNAMIX_HOME` isolé :
  - seules les copies concernées sont écrites dans `fx/` ;
  - les originaux et `premaster/` sont inchangés (taille et empreinte) ;
  - les repères recalculés sont cohérents avec la durée de la copie ;
  - le débordement est présent au début de la copie de B.
- **`tests/test_set_project_fx.py`** :
  - clé par paire, recettes conservées lors d'un réordonnancement ;
  - paires inactives ;
  - modifier une recette invalide le rendu ;
  - `invalidate_from("setlist")` garde les recettes et met le rendu à `null` ;
  - reset qui vide `fx/` et les recettes ;
  - `fx_map` ;
  - chargement d'un projet sans bloc `fx`.
- **`tests/test_mixxx_export.py`** (nouveau) : l'ordre de priorité `fx/` > `premaster/` > original et les repères issus de `fx.render` sont bien ceux transmis à l'exporteur (exporteur remplacé par un bouchon, sans base Mixxx réelle).
- **`tests/gui_smoke.py`** :
  - ouvrir la fenêtre « Transition FX » sur un projet avec transitions factices ;
  - ajouter un freeze et un sample ;
  - générer un extrait de pré-écoute (lecteur remplacé par un bouchon, qui vérifie qu'on lui passe un fichier WAV existant) ;
  - « Apply all FX » écrit une copie dans `fx/` ;
  - l'original est intact.

## Fichiers touchés

| fichier | changement |
|---|---|
| `transition_fx.py` | nouveau : grille, contexte, FX, validation, rendu d'une région, extrait de pré-écoute |
| `fx_render.py` | nouveau : rendu d'un set (bases, régions, limiteur, écriture `fx/`, repères) |
| `fx_window.py` | nouveau : fenêtre « Transition FX », lecteur (`Player`) |
| `set_project.py` | bloc `fx`, méthodes FX, étape `fx`, invalidation, reset, `reset_preview` |
| `set_builder.py` | bouton d'étape, ouverture de la fenêtre, `_with_rendered`, export M3U/Mixxx, étiquettes Set map |
| `mixxx_export.py` | `--project` : copies `fx/` et repères du rendu |
| `charts.py` | `set_timeline(..., fx_labels=None)` |
| `config.py` | clé `fx_samples_folder` |
| `README.md`, `GUI_README.md` | FX de transition |
| `tests/…` | voir section 5 |
