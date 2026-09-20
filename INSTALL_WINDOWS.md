# Installer DynaMix sous Windows

Ce guide décrit l'installation de DynaMix sur Windows 10 ou 11. Aucune
connaissance particulière de Python n'est nécessaire.

DynaMix sert à **créer des playlists avec des transitions soignées**. Son
premier usage est l'**Auto DJ de Mixxx** : DynaMix prépare la playlist, les
repères d'intro et d'outro et, si besoin, des copies pré-masterisées ou avec
FX, pour qu'Auto DJ enchaîne tout un set comme s'il était mixé. (Un
changement de nom, par exemple *DynaMixxx*, est envisagé plus tard.)

DynaMix est parti d'un fork de [makalin/dynamix](https://github.com/makalin/dynamix),
dont il s'est depuis dissocié : il est devenu un outil de préparation de sets
(projets, propositions de set, transitions, pré-mastering, FX, export Mixxx)
qui va très au-delà de correctifs. Voir « About this fork » dans le
[README](README.md).

## 1. Installer Python

1. Téléchargez **Python 3.11 ou 3.12** (64 bits) sur
   <https://www.python.org/downloads/windows/>.
   Évitez la toute dernière version majeure si elle vient de sortir : `numba`,
   une dépendance de `librosa`, met parfois plusieurs mois à la supporter.
2. Lancez l'installateur et cochez **« Add python.exe to PATH »**.
3. Cliquez sur **Customize installation** et vérifiez que
   **« tcl/tk and IDLE »** est coché. C'est indispensable pour l'interface
   graphique (`gui.py`), qui repose sur Tkinter.
4. Terminez l'installation, puis ouvrez un terminal (PowerShell ou
   l'Invite de commandes) et vérifiez :

   ```bat
   py -3 --version
   ```

## 2. Récupérer le dépôt

Avec Git pour Windows (<https://git-scm.com/download/win>) :

```bat
git clone https://github.com/timox/dynamix.git
cd dynamix
```

Sans Git : sur la page GitHub du dépôt, **Code → Download ZIP**, puis
décompressez l'archive et ouvrez un terminal dans le dossier obtenu.

## 3. Installation automatique (recommandée)

Double-cliquez sur **`install_windows.bat`**, ou lancez-le depuis le terminal :

```bat
install_windows.bat
```

Le script :

1. crée un environnement virtuel `venv` dans le dossier du projet ;
2. installe toutes les dépendances de `requirements.txt` ;
3. exécute `check_install.py`, qui vérifie Python, chaque paquet, Tkinter,
   le décodage MP3 et lance une courte analyse de test.

Si tout se termine par `All checks passed`, l'installation est terminée.

## 3 bis. Installation manuelle

```bat
py -3 -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python check_install.py
```

Sous PowerShell, si l'activation est refusée (« l'exécution de scripts est
désactivée »), lancez une fois :

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

puis réessayez `venv\Scripts\activate`.

## 4. FFmpeg : optionnel

Le projet d'origine présentait FFmpeg comme requis. Ce n'est plus le cas pour
les MP3 : le paquet `soundfile` embarque `libsndfile` 1.1+, qui décode
nativement **MP3, WAV, FLAC et OGG**. `check_install.py` le confirme sur la
ligne « MP3 decoding via soundfile ».

FFmpeg reste nécessaire uniquement pour les fichiers **M4A/AAC**. Le plus
simple : onglet **Configuration**, ligne « FFmpeg (facultatif) », bouton
**Télécharger**. DynaMix récupère FFmpeg auprès de ses auteurs dans
`%LOCALAPPDATA%\DynaMix\ffmpeg` et renseigne le chemin tout seul. Le
téléchargement pèse plusieurs dizaines de Mo et s'interrompt depuis l'onglet
Tâches.

FFmpeg n'est **pas** livré avec DynaMix : c'est un logiciel libre sous licence
GPL, alors que DynaMix est sous licence MIT. Il est donc téléchargé à votre
demande, jamais inclus.

Vous pouvez aussi l'installer vous-même :

```powershell
winget install Gyan.FFmpeg
```

ou via Chocolatey (`choco install ffmpeg`), puis rouvrez le terminal et
cliquez sur **Détecter**.

## 5. Utiliser DynaMix

Dans le dossier du projet, activez l'environnement à chaque nouvelle session
de terminal :

```bat
venv\Scripts\activate
```

Puis lancez l'interface graphique (ou double-cliquez sur `run_gui.bat`) :

```bat
python gui.py
```

Mettez les chemins entre guillemets s'ils contiennent des espaces.

## 5 bis. L'onglet Set Builder : le fil conducteur

Tous vos morceaux mixés sont rassemblés dans un seul **dossier de
bibliothèque**, indiqué dans l'onglet **Configuration** (avec le dossier des
samples FX). DynaMix le lit sans jamais le modifier.

Un set est un **projet**, c'est-à-dire un dossier créé par DynaMix dans le
dossier des projets (réglable dans l'onglet Configuration, par défaut
`DynaMix Projects` dans votre profil) :

```
DynaMix Projects\Samedi soir\
    project.json     options, sélection, morceaux analysés, set list, état des étapes, réglages FX
    premaster\       les copies corrigées du pré-mastering
    fx\              les copies avec les FX de transition
    exports\         playlists M3U, transitions.json, graphiques
    exports\reports\ les rapports (un fichier texte chacun)
```

**New project...** crée le projet, le menu déroulant rouvre n'importe quel
projet. **Snapshots...** enregistre l'état des réglages du projet sous un nom
(sélection, set list, transitions, réglages FX, options) et permet de le
restaurer plus tard ; l'état courant est d'abord sauvegardé (« before
restore »). La ligne *Audio used* du panneau Workflow indique si le set utilise
les copies FX, les copies pré-masterisées ou les originaux, et la case **Use
pre-mastered copies** des options permet de choisir. **Reset project...** repart d'une sélection vide, **Clear analysis
cache...** fait réanalyser les morceaux sélectionnés.

Le panneau *Workflow* liste les sept étapes avec leur état, leur date et un
rappel « Next : » :

1. **Select and analyze** : dans l'onglet *Tracks*, ajoutez des morceaux de la
   bibliothèque à la sélection, puis analysez-les (BPM, tonalité, énergie).
   Chaque fichier n'est analysé qu'une fois, le résultat est conservé dans
   `%LOCALAPPDATA%\DynaMix\analysis.sqlite`.
2. **Propose** : plusieurs set lists calculées sur la sélection selon la durée
   et la courbe d'énergie. Utilisez-en une, puis corrigez-la avec
   Up / Down / Remove.
3. **Plan Transitions** : repères d'intro et d'outro calés sur les temps ; la
   feuille de transitions est un rapport de l'onglet Log.
4. **Pre-master Set** (optionnel) : copies corrigées dans `premaster\`.
5. **Transition FX** (optionnel) : ouvre l'onglet *FX* (voir 6 bis).
6. **Create Playlist** (optionnel) : fichier M3U dans `exports\`.
7. **Export to Mixxx** : repères et playlist dans la base Mixxx indiquée dans
   l'onglet Configuration.

Les onglets de droite montrent les graphiques : courbe d'énergie du set face à
la cible, carte du set avec les zones d'intro et d'outro, détail d'un morceau
et, pour le pré-mastering, le volume et la crête vraie avant et après.

L'onglet **Log** réunit en haut les rapports du projet (résumé, mastering,
analyse par bande, feuille de transitions, pré-mastering, export Mixxx) et en
bas tous les messages et erreurs.

## 5 ter. L'onglet Configuration

Le bloc **Affichage** règle la taille des caractères (8 à 18 points) de toute la
fenêtre, des tableaux et des graphiques ; elle s'applique et s'enregistre
immédiatement. La **Langue** (Auto = langue de Windows, English, Français)
s'applique au prochain démarrage ; le jargon DJ (set list, cue, FX, BPM…) reste
en anglais. Pour corriger une traduction sans toucher au programme, créez
`%LOCALAPPDATA%\DynaMix\locales\fr.json` avec les entrées à changer, par exemple
`{"Plan Transitions": "Planifier"}` (la clé est le texte anglais, gardez les
`{…}` tels quels). Les rapports (mastering, analyse par bande, feuille de
transitions, résumé du projet) et les alertes sont traduits aussi, y compris
ceux des analyses déjà en cache ; seul le fil technique de l'onglet Log reste
en anglais.

Tout ce qui dépend de votre machine est réuni là : le dossier des projets, la
base Mixxx (bouton *Detect*, ou laissez vide pour la détection automatique),
les valeurs par défaut des nouveaux projets (durée, courbe, longueur de fondu,
sonie cible, timbre, phase, format de sortie) et un rapport d'environnement
qui indique ce que DynaMix a trouvé : Tkinter, libsndfile et son support MP3,
librosa, numba, FFmpeg, base Mixxx, cache d'analyses. Cliquez sur
**Save configuration** après modification.

## 6. Musiques mal masterisées : contrôle et pré-mastering

Si vos fichiers ont des niveaux très différents, du clipping, un grave en
opposition de phase ou une couleur sonore incohérente, ReplayGain ne suffira
pas : il n'aligne que le volume moyen. DynaMix propose deux outils dans
l'onglet **Set Builder** (bouton *Mastering Report* sous les options, et
étape 4) :

- **Mastering Report** : mesure chaque morceau (sonie en LUFS, plage de sonie,
  crête vraie, clipping, offset DC, équilibre spectral, corrélation stéréo,
  phase du grave, compatibilité mono, filtrage en peigne) et signale en clair
  ce qui cloche, avec un score sur 100. Les écarts sont jugés par rapport au
  reste du set.
- **Pre-master Set** : écrit des **copies corrigées** dans le dossier
  `premaster\` du projet, jamais les originaux : sonie ramenée à la cible choisie (par défaut
  −14 LUFS), limiteur de crête à −1 dBTP, suppression de l'offset DC,
  correction de polarité et mise en mono du grave si nécessaire, et
  optionnellement un rapprochement doux de la couleur sonore vers la médiane
  du set (case *Match tone*).

Le filtrage en peigne, lui, n'est que signalé : il ne se répare pas sans les
pistes d'origine.

**Analyse par bande** (bouton *Band Analysis*, et onglet *Track*) : suivi du
signal par bande dans le temps avec des constantes calées sur le tempo, carte
du masquage du 200–500 Hz par rapport à ses voisines, détection des résonances
persistantes entre 100 et 800 Hz avec suggestion de creux d'égalisation. Quand
ces défauts sont détectés, DynaMix indique **reprise du mix conseillée** : le
pré-mastering aligne les niveaux d'un set mais ne peut pas démasquer un
bas-médium encombré. En ligne de commande : `python mastering.py bands <dossier>`.

L'onglet **Pre-master** montre ensuite, morceau par morceau, le volume et la
crête vraie avant et après ; la liste des actions appliquées (gain, timbre,
polarité, grave en mono) est dans le rapport *Pre-master* de l'onglet Log.

## 6 bis. Les FX de transition

L'onglet **FX** du Set Builder (étape 5) règle chaque transition : choisissez
une transition, puis empilez des effets — **Freeze** (répète les derniers
temps du morceau sortant, par exemple 4×1 → 2×2 → 1×4), **Filter** (balayage
passe-haut, passe-bas ou passe-bande avec résonance), **Echo** (calé au tempo)
et **Sample** (un sample des dossiers de samples FX, calé au tempo du morceau
d'après le BPM écrit dans son nom, répétable).

Vous pouvez déclarer **plusieurs dossiers de samples** dans l'onglet
Configuration (**Ajouter…** / **Retirer**) : ils sont lus comme une seule
liste, et chaque ligne indique de quel dossier vient le sample, de sorte que
deux fichiers de même nom restent distinguables. Le champ **Filtre** cherche
aussi bien dans le nom du fichier que dans le nom du dossier — taper le nom
d'un dossier n'affiche que ses samples. Le bouton **Relire** relit les dossiers
sans quitter l'onglet. Un dossier devenu introuvable est simplement signalé
dans le Log, les autres restent utilisables.

Le graphique en haut de
l'onglet montre A et B avec leurs fondus et chaque effet sur un axe en temps ;
**▶ Preview (loop)** fait écouter la transition en boucle. **Apply all FX**
écrit des copies dans `fx\` ; la playlist et l'export Mixxx les utilisent.

**Fin de A (temps)** déplace le moment où le morceau sortant cesse de s'entendre.
Par défaut, DynaMix le déduit de l'outro détectée et de la longueur du morceau,
ce qui allonge souvent la transition et oblige les effets à s'étirer pour la
couvrir. Le champ compte en temps après la jonction ; le bouton **Prévu** à côté
remet la valeur du plan. C'est le repère d'outro sur lequel Mixxx fait son fondu :
le raccourcir raccourcit vraiment le fondu de l'Auto DJ, et l'intro exigée du
morceau entrant suit automatiquement. Le marqueur est gardé hors du plan, donc
replanifier les transitions ne le perd pas. La feuille de transitions, la carte
du set et les fichiers `exports\transitions.txt` et `.json` sont réécrits à
chaque déplacement : ce qu'ils décrivent est ce que le set jouera vraiment.

Ajoutez le dossier `premaster\` du projet dans la bibliothèque Mixxx : l'export
Mixxx et la playlist utilisent automatiquement les copies corrigées. En ligne de commande :

```bat
python mastering.py check "C:\Musique\Set"
python mastering.py fix "%USERPROFILE%\DynaMix Projects\Samedi soir" --tone
```

Aucun logiciel supplémentaire n'est nécessaire, FFmpeg compris.

## 7. Enchaîner un set automatiquement avec Mixxx

[Mixxx](https://mixxx.org) est gratuit et son **Auto DJ** enchaîne une playlist
avec un fondu calé au tempo. DynaMix peut lui fournir, pour chaque morceau,
les repères d'**intro** et d'**outro** qui pilotent ce fondu, ainsi que la
playlist dans le bon ordre. Il n'y a alors plus rien à préparer.

1. **Une seule fois dans Mixxx** : *Préférences → Bibliothèque*, ajoutez votre
   dossier de musique et lancez un balayage, pour que Mixxx connaisse les
   fichiers. Activez aussi la normalisation : *Préférences → Normalisation*,
   cochez **ReplayGain** (analyse et application). Mixxx analysera les morceaux
   et alignera leur volume à la lecture, sans modifier vos fichiers.
2. **Fermez Mixxx.** Il garde sa base ouverte et écraserait les modifications.
3. Dans DynaMix, onglet **Set Builder** : une fois les transitions planifiées
   (étape 3), cliquez sur **Export to Mixxx** (étape 7), confirmez
   l'emplacement de `mixxxdb.sqlite` (détecté automatiquement dans
   `%LOCALAPPDATA%\Mixxx`) et le nom de la playlist. Le compte rendu est un
   rapport de l'onglet Log. Si le projet utilise des copies, ajoutez aussi ses
   dossiers `fx\` et `premaster\` à la bibliothèque Mixxx.

   En ligne de commande, pour un projet ou en une seule étape depuis un dossier :

   ```bat
   python mixxx_export.py --project "%USERPROFILE%\DynaMix Projects\Samedi soir"
   python mixxx_export.py --playlist "C:\Musique\Set" --set-duration 60
   ```

   ou, pour garder l'ordre d'une playlist existante :

   ```bat
   python mixxx_export.py --m3u "C:\Musique\Set\Set.m3u"
   ```

4. Rouvrez Mixxx. Dans *Bibliothèque → Listes de lecture*, faites un clic droit
   sur la playlist `DynaMix - ...` → **Ajouter à la file Auto DJ**. Dans le
   panneau Auto DJ, choisissez le mode de transition **Intro + outro complets**
   et cliquez sur **Activer Auto DJ**.

Une sauvegarde horodatée de la base est créée à côté de `mixxxdb.sqlite` avant
chaque export. Les morceaux absents de la bibliothèque Mixxx sont listés dans
le rapport : ajoutez le dossier dans Mixxx, rebalayez, puis exportez à nouveau.

## 7 bis. Partager DynaMix sans installer Python

Pour donner DynaMix à quelqu'un qui n'a pas Python, lancez depuis le dossier du
projet (après `install_windows.bat`) :

```bat
packaging\build_windows.bat
```

Le script fabrique `dist\DynaMix` : un Python « gelé » avec uniquement les
bibliothèques utilisées par DynaMix (PyInstaller), lance son autotest, puis
produit deux fichiers à donner :

- **`dist\DynaMix-<version>-setup.exe`** — l'installateur. Il installe
  **pour l'utilisateur courant seulement**, dans
  `%LOCALAPPDATA%\Programs\DynaMix` : il ne demande donc jamais les droits
  administrateur, crée les raccourcis du menu Démarrer (et du bureau si on le
  coche) et se désinstalle depuis Paramètres > Applications.
- **`dist\DynaMix-<version>-windows-x64.zip`** — le même build en zip
  (environ 120 Mo), pour qui préfère ne rien installer : décompresser et
  double-cliquer sur `DynaMix.exe`.

Fabriquer l'installateur demande Inno Setup :

```powershell
winget install JRSoftware.InnoSetup
```

Sans lui, le script saute cette étape et livre quand même le dossier et le zip.
Le numéro de version vient de `version.py`, seul endroit où il est écrit.

- L'exécutable n'est pas signé : Windows affiche « Windows a protégé votre
  ordinateur » ; cliquez sur **Informations complémentaires → Exécuter quand
  même**. C'est vrai aussi pour l'installateur.
- La première analyse est plus lente (numba compile une fois, puis garde le
  résultat dans `%LOCALAPPDATA%\DynaMix\numba_cache`).
- Pour vérifier une copie sur une autre machine :
  `DynaMix.exe --self-test rapport.txt` (les données de l'utilisateur ne sont
  pas touchées).

## 8. Dépannage

| Symptôme | Cause probable | Solution |
| --- | --- | --- |
| `python` ouvre le Microsoft Store | Alias Windows | Utilisez `py -3`, ou désactivez l'alias dans *Paramètres → Applications → Alias d'exécution d'application* |
| `ModuleNotFoundError: No module named 'tkinter'` | Tcl/Tk non installé | Relancez l'installateur Python → *Modify* → cochez *tcl/tk and IDLE* |
| `pip install` échoue sur `numba` ou `llvmlite` | Version de Python trop récente | Installez Python 3.11 ou 3.12 et recréez le `venv` |
| `NoBackendError` à l'ouverture d'un fichier | Format non géré par libsndfile (M4A/AAC) | Installez FFmpeg (section 4) ou convertissez le fichier en MP3/WAV |
| Les graphiques ne s'affichent pas | Backend matplotlib | Installez Tkinter (voir ci-dessus) ; matplotlib utilise TkAgg sous Windows |
| Analyse très lente au premier lancement | Compilation JIT de `numba` | Normal la première fois, les exécutions suivantes sont plus rapides |

Pour rejouer le diagnostic à tout moment :

```bat
python check_install.py
```
