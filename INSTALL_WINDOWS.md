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

## 6. Dépannage

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
