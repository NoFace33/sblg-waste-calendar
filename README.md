# Collectes et dépôts — Saint-Basile-le-Grand

Calendrier des collectes et dépôts de la Ville de Saint-Basile-le-Grand,
généré automatiquement et importable dans Google Calendar (ou tout autre
calendrier supportant le format iCalendar).

## Abonnement Google Calendar

1. Dans Google Calendar, cliquez sur **+** à côté de *Autres agendas*
2. Choisissez **À partir d'une URL**
3. Collez l'URL suivante :

```
https://raw.githubusercontent.com/NoFace33/sblg-waste-calendar/main/collectes-sblg.ics
```

Google Calendar rafraîchit les abonnements ICS toutes les 24 à 48 heures.

## Collectes incluses

| Collecte | Fréquence |
|---|---|
| Ordures ménagères | Aux 3 semaines environ |
| Matières récupérables | Aux 2 semaines |
| Résidus alimentaires | Aux 2 semaines (jan–mars, nov–déc) / hebdomadaire (avr–oct) |
| Résidus verts | Aux 2 semaines (avr–nov) |
| Encombrants | Mensuel |
| Dépôt de rebuts encombrants et récupérables | Garage municipal Léon-Taillon |
| Dépôt de résidus domestiques dangereux (RDD) | Ponctuel |

## Mise à jour automatique

Un workflow GitHub Actions tourne le **1er de chaque mois à 6h UTC**.
Il refait une collecte complète depuis le site de la ville et remet à jour
`collectes-sblg.ics` si des changements ont eu lieu.

Vous pouvez aussi déclencher une mise à jour manuellement depuis l'onglet
**Actions** → *Refresh calendar* → **Run workflow**.

## Fenêtre de dates

À chaque exécution, le script couvre :

- **Début** : aujourd'hui − 60 jours
- **Fin** : 31 décembre de l'année en cours

À partir du 1er novembre, la fenêtre s'étend automatiquement jusqu'au
31 décembre de l'année suivante, pour que le calendrier ne soit jamais vide
en fin d'année.

## Source des données

`https://www.villesblg.ca/calendrier-categories/collectes-et-depots/`

Le script utilise l'endpoint AJAX interne du site (`admin-ajax.php`, action
`eventChangeDate`, catégorie 14) pour récupérer les événements par fenêtres
de 30 jours. C'est la même source que le calendrier interactif sur le site.
Un nonce WordPress est extrait de la page à chaque exécution.
