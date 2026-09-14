# Chantier 3 — Réorganisation de l'interface : FX en onglet, rapports dans le Log

Date : 2026-09-14. Décisions validées avec l'utilisateur (A, B, A, « go »).

## Contexte

Les anciens onglets (Track Analysis, Two-Track, DJ Tools, Audio Effects, Export Tools) ont été retirés
(commit 273a986). Il reste Set Builder, Configuration et Log. La fenêtre Transition FX et les fenêtres de
texte (Project summary, Mastering Report, Band Analysis, Transition Plan, résumé Mixxx) s'ouvrent à part.

## 1. Sous-onglet FX du Set Builder

- `TransitionFxWindow(tk.Toplevel)` devient `TransitionFxPanel(ttk.Frame)`, placé dans un sous-onglet
  **FX** après Tracks, Overview, Track, Pre-master. Contenu et comportement inchangés.
- Le bouton de l'étape 5 (`open_fx_window`) sélectionne l'onglet (message « Plan the transitions first
  (step 3) » s'il n'y a pas de plan, l'onglet affiche alors ce texte).
- Le panneau est reconstruit (`_refresh_fx_tab`) quand le projet ouvert change ou quand la signature du plan
  (set list + cues planifiés) ne correspond plus : à l'ouverture d'un projet, à la fin de « Plan Transitions »
  et quand l'onglet FX devient visible. Un panneau qui rend (« Apply all FX ») n'est pas détruit : son rendu
  se termine et est écarté s'il est périmé (règle existante).
- La preview en boucle s'arrête dès que l'onglet FX n'est plus visible (changement de sous-onglet ou
  d'onglet principal) et quand le panneau est reconstruit.

## 2. Rapports dans l'onglet Log

- Module `reports.py` : `write_report(folder, title, text, now=None) -> path`,
  `list_reports(folder) -> [{"title", "time", "path"}]` (du plus ancien au plus récent),
  `read_report(path) -> str`. Fichier `<exports>/reports/YYYY-MM-DD HH-MM-SS <titre>.txt` ; caractères
  interdits du titre remplacés par `-` ; un nom déjà pris reçoit ` (2)`, ` (3)`…
- Onglet Log en deux zones : en haut la liste des rapports du projet ouvert (heure, titre) et le texte du
  rapport sélectionné, bouton *Open reports folder* ; en bas le fil du log inchangé.
- Filtre : *All / Reports / Warnings and errors / Errors* ; *Reports* masque le fil.
- `add_report(title, text, show=True)` : écrit le fichier, journalise `Report: <titre> (<chemin>)`,
  rafraîchit la liste ; avec `show`, sélectionne l'onglet Log et le rapport. La liste est relue à
  l'ouverture d'un projet ; *Reset project* l'efface avec `exports/`.
- Deviennent des rapports : Project summary, Mastering Report, Band Analysis, Transition Sheet (le JSON du
  plan est écrit dans `exports/transitions.json` en même temps), Pre-master (sans `show` : le sous-onglet
  Pre-master garde le graphique avant/après, sans le texte) et Mixxx Export (remplace la boîte finale ; la
  confirmation avant export reste).
- Supprimés : `_show_text_window`, `_show_transition_window`, `save_transition_sheet`,
  `save_transition_json`.

## 3. Tests

- `tests/test_reports.py` : nommage, collisions, titre nettoyé, ordre, lecture, dossier absent.
- `tests/gui_smoke.py` : le FX se pilote dans l'onglet ; quitter l'onglet arrête la preview ; un plan modifié
  reconstruit le panneau quand l'onglet redevient visible ; un rapport (Project summary) apparaît dans la
  liste du Log et son fichier existe ; le filtre *Reports* masque le fil.
