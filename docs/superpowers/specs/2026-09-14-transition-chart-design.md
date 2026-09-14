# Graphique de la transition (onglet FX)

Date : 2026-09-14. Décisions validées avec l'utilisateur : zoom sur la transition choisie (A), vraies formes
d'onde (1), « ok go ».

## Affichage

En haut de l'onglet FX, séparé des colonnes par un séparateur réglable, un graphique matplotlib sur un axe en
temps de la jonction (J, -4, +4…, lignes épaisses = mesures) :

1. **A (out)** : forme d'onde de A atténuée par son fondu (pâle derrière : le signal complet) et la courbe de
   volume (cos depuis la jonction, 0 après « A ends »).
2. **B (in)** : forme d'onde de B calée sur la jonction, atténuée par son fondu (sin) et la courbe de volume.
3. **Une ligne par effet actif, dans l'ordre de la pile** : freeze (partie capturée, répétitions, traîne),
   filtre (balayage « start → end Hz », maintien sur A ou retour au son sec sur B), écho (partie traitée et
   queue estimée : répétitions jusqu'à -60 dB, 16 temps au plus), sample (une case par répétition, selon
   l'ancre, le calage au tempo et la limite de 64 s).
4. **Result** : forme d'onde de la preview rendue, si elle correspond aux réglages actuels.

Repères : trait de jonction, « A ends » en tirets, jonction prévue en pointillés quand un freeze l'a déplacée,
premier avertissement dans le titre.

## Calcul

- `transition_fx.transition_layout(a_beats, b_beats, a_outro_start, a_outro_end, b_intro_start, effects,
  nudge_ms, sample_seconds, length)` : positions sans audio, avec les mêmes règles que `apply_effects`
  (freeze d'abord, qui déplace jonction et fin de A) et `preview_mix` (fondu = fin de A − jonction, fenêtre
  short/long, `preview_start`).
- `transition_fx.peak_envelope(data, sr, t0)` : crête toutes les 10 ms.
- `fx_render.transition_beats` / `transition_layout_for` : grilles de temps et calcul pour deux profils planifiés.
- `charts.transition_detail(layout, a_env, b_env, result_env)`.

## Onglet FX

- Au choix d'une transition, A (outro − 90 s … outro end + 40 s) et B (intro − 10 s … intro + 110 s) sont lus
  en arrière-plan et réduits en enveloppes, gardées par couple de fichiers (copies pré-masterisées comprises).
- Chaque changement (effet, réglage, nudge, longueur) redessine le graphique après 150 ms, sans relire l'audio.
- La preview calcule l'enveloppe de son rendu ; la ligne Result n'est montrée que si la transition, les
  réglages et la longueur n'ont pas changé depuis.

## Tests

- `tests/test_transition_layout.py` : sans effet, freeze comparé au moteur, ordre de la pile, filtres des deux
  côtés et courbe, écho et queue, sample (ancres, tempo, répétitions, limite, sans fichier), enveloppe,
  graphique avec et sans formes d'onde.
- `tests/gui_smoke.py` : graphique dessiné au choix d'une transition, une ligne par effet, résultat ajouté après
  la preview.
