# Installer DynaMix sous Windows

Ce guide décrit l'installation de DynaMix sur Windows 10 ou 11. Aucune
connaissance particulière de Python n'est nécessaire.

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
git clone https://github.com/<votre-compte>/dynamix.git
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

Le README d'origine présente FFmpeg comme requis. Ce n'est plus le cas pour
les MP3 : le paquet `soundfile` embarque `libsndfile` 1.1+, qui décode
nativement **MP3, WAV, FLAC et OGG**. `check_install.py` le confirme sur la
ligne « MP3 decoding via soundfile ».

FFmpeg reste nécessaire uniquement pour les fichiers **M4A/AAC**. Pour
l'installer :

```powershell
winget install Gyan.FFmpeg
```

ou via Chocolatey (`choco install ffmpeg`), puis rouvrez le terminal.

## 5. Utiliser DynaMix

Dans le dossier du projet, activez l'environnement à chaque nouvelle session
de terminal :

```bat
venv\Scripts\activate
```

Puis, par exemple :

```bat
:: Interface graphique (ou double-cliquez sur run_gui.bat)
python gui.py

:: Analyse de transition entre deux morceaux
python mix_enhanced.py "C:\Musique\track1.mp3" "C:\Musique\track2.mp3" --visualize

:: Analyse d'un dossier complet et proposition de set de 60 minutes
python mix_enhanced.py --playlist "C:\Musique\Set" --set-duration 60

:: Notes DJ pour un morceau, ou pour tout un dossier
python dj_tools.py "C:\Musique\track1.mp3" --export notes.txt
python dj_tools.py --batch "C:\Musique\Set" --output-dir "C:\Musique\Notes"
```

Mettez les chemins entre guillemets s'ils contiennent des espaces.

## 6. Musiques mal masterisées : contrôle et pré-mastering

Si vos fichiers ont des niveaux très différents, du clipping, un grave en
opposition de phase ou une couleur sonore incohérente, ReplayGain ne suffira
pas : il n'aligne que le volume moyen. DynaMix propose deux outils, dans
l'onglet **Playlist Manager**, cadre *Mastering* :

- **Mastering Report** : mesure chaque morceau (sonie en LUFS, plage de sonie,
  crête vraie, clipping, offset DC, équilibre spectral, corrélation stéréo,
  phase du grave, compatibilité mono, filtrage en peigne) et signale en clair
  ce qui cloche, avec un score sur 100. Les écarts sont jugés par rapport au
  reste du set.
- **Pre-master Set...** : écrit des **copies corrigées** dans un autre dossier,
  jamais les originaux : sonie ramenée à la cible choisie (par défaut
  −14 LUFS), limiteur de crête à −1 dBTP, suppression de l'offset DC,
  correction de polarité et mise en mono du grave si nécessaire, et
  optionnellement un rapprochement doux de la couleur sonore vers la médiane
  du set (case *Match tone*).

Le filtrage en peigne, lui, n'est que signalé : il ne se répare pas sans les
pistes d'origine.

Ensuite, ajoutez le dossier corrigé dans la bibliothèque Mixxx et lancez
**Plan Transitions** sur ce dossier. En ligne de commande :

```bat
python mastering.py check "C:\Musique\Set"
python mastering.py fix "C:\Musique\Set" --out "C:\Musique\Set_premaster" --tone
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
3. Dans DynaMix, onglet **Playlist Manager** : choisissez le dossier, créez
   éventuellement une set list, puis cliquez sur **Plan Transitions**. Une
   fenêtre affiche la feuille de transitions. Cliquez sur **Export to Mixxx**,
   confirmez l'emplacement de `mixxxdb.sqlite` (détecté automatiquement dans
   `%LOCALAPPDATA%\Mixxx`) et le nom de la playlist.

   En ligne de commande, l'équivalent en une seule étape :

   ```bat
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
