# FireSync Sahel

**Un calendrier des feux harmonisé sur 25 ans, pour n'importe quelle zone.**

FireSync Sahel fusionne les détections de feux actifs MODIS (Terra 2000→, Aqua 2002→) et VIIRS 375 m
(S-NPP 2012→, NOAA-20, NOAA-21) en une série unique exprimée en **détections VIIRS S-NPP équivalentes**,
puis calcule à la volée, pour un département, une forêt classée, un parcours ou un polygone dessiné :
calendrier années × semaines, saison type, dates de début / pic / fin, semaines critiques, années
anormales et position de la saison en cours, avec une incertitude à 90 % **validée**.

**Nouveau — Prévision IA à 4 semaines** (projet NASA Space Apps Challenge · Dakar) : un modèle
d'apprentissage automatique, entraîné sur les 25 ans de série harmonisée, prévoit l'activité de feu des
4 prochaines semaines pour chaque département du Sénégal et de la Gambie, classe les zones « où agir en
priorité » et génère un message d'alerte SMS / WhatsApp prêt à transmettre aux comités de lutte. La
saison 2026-27 est suivie en direct (FIRMS temps quasi réel), avec la relève NOAA-20 / NOAA-21 depuis
l'arrêt de Suomi NPP le 1er novembre 2026.

Plateforme bilingue FR / EN, trois espaces :

| Espace | Accès | Contenu |
|---|---|---|
| **Public** (navigation dans l'en-tête) | libre | accueil, explorateur de zones (carte, unités administratives, dessin, import GeoJSON), saison en cours par région, **prévisions IA**, méthode & validation, données & partenaires, demande d'accès pro, bulletins PDF |
| **Pro** | compte `pro` | tableau de bord des zones suivies avec seuil d'alerte, gestion des zones, analyse détaillée (série naïve vs harmonisée, séries brutes par capteur), exports CSV / GeoJSON, bulletins FR / EN, compte |
| **Admin** | compte `admin` | vue d'ensemble, lancement des traitements de données avec journaux, modèle & validation, utilisateurs & demandes d'accès, zones de référence publiques (forêts classées…), paramètres (clé FIRMS, partenaires), journal d'audit |

## Démarrage rapide

```powershell
python -m venv .venv
# tout (plateforme + pipeline de données + tests) ; requirements.txt seul = plateforme web
.\.venv\Scripts\python.exe -m pip install -r requirements-pipeline.txt

# 1. données + modèle (≈ 1 h la première fois, principalement la validation)
.\.venv\Scripts\python.exe -m firesync build

# 2. compte administrateur (mot de passe généré et affiché une seule fois)
.\.venv\Scripts\python.exe -m firesync create-user vous@exemple.org --role admin --name "Votre nom" --generate

# 3. plateforme web → http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m firesync serve
```

Commandes disponibles (`python -m firesync <commande>`) :

| Commande | Rôle |
|---|---|
| `download` | archives annuelles FIRMS par pays (sans clé) |
| `nrt` | saison en cours + NOAA-21 via l'API FIRMS (`FIRMS_MAP_KEY`) |
| `process` | CSV → détections propres + agrégats hexagonaux H3 |
| `landcover` | fractions d'occupation du sol MCD12Q1 (Earthdata) ou ESA CCI en repli |
| `burned` | surfaces brûlées MCD64A1 (validation indépendante) |
| `ndvi` | combustible de fin d'hivernage : NDVI MODIS MOD13A1, maximum août–octobre par cellule (à relancer chaque année en novembre) |
| `boundaries` | limites administratives geoBoundaries |
| `validate [--no-fit]` | validation croisée par années retirées (+ réentraînement) |
| `recalibrate` | recalcule la calibration κ depuis les prédictions en cache (quelques secondes) |
| `fit` | réentraîne les modèles finaux sans revalider |
| `refresh` | cycle temps réel : FIRMS NRT → détections → tables de service → prévision IA (sans réentraîner le modèle MODIS) |
| `forecast` | réentraîne et valide la prévision IA |
| `ndvi` | combustible de fin d'hivernage (NDVI MODIS) |
| `serve [--port 8000]` | serveur web |
| `create-user EMAIL --role admin|pro [--generate]` | création de compte |
| `hash-password` | empreinte scrypt d'un mot de passe (lu sur l'entrée standard) pour `FIRESYNC_ADMIN_PASSWORD_HASH` |

### Variables d'environnement

| Variable | Usage |
|---|---|
| `FIRESYNC_COUNTRIES` | pays FIRMS, ex. `Senegal,The_Gambia,Mali` (défaut : Sénégal + Gambie) |
| `FIRESYNC_ADMIN_ISO3` | codes ISO3 pour les limites administratives |
| `FIRESYNC_DATA` | dossier de données (utile pour le sortir de OneDrive) |
| `FIRMS_MAP_KEY` | clé API FIRMS gratuite — nécessaire pour la saison 2026-27 et NOAA-21 (aussi réglable dans Admin › Paramètres) |
| `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD` ou `EARTHDATA_TOKEN` | téléchargement MCD12Q1 (sinon `~/.netrc`) ; jamais écrits sur disque par FireSync |

## Déploiement sur Vercel

Le dépôt se déploie tel quel (point d'entrée `app.py`, dépendances `requirements.txt`, réglages
`vercel.json`). La plateforme y tourne en fonction serverless : elle sert l'**instantané de données**
versionné (`data/models/` et les tables de `data/processed/` non ignorées) ; les traitements longs
(téléchargements, modèle, prévision IA) se lancent sur un poste puis se publient par `git push`, ce qui
redéploie le site.

Variables d'environnement du projet Vercel (Settings › Environment Variables) :

| Variable | Rôle |
|---|---|
| `FIRESYNC_SECRET` | clé de signature des sessions — **obligatoire** (64 caractères aléatoires) |
| `FIRESYNC_ADMIN_EMAIL` | compte administrateur créé au démarrage |
| `FIRESYNC_ADMIN_PASSWORD_HASH` | son mot de passe, sous forme d'empreinte : `python -m firesync hash-password` |
| `FIRESYNC_ADMIN_NAME` | nom affiché (facultatif) |
| `DATABASE_URL` | Postgres (Vercel › Storage › Neon) : rend persistants comptes pro, zones, paramètres, demandes d'accès |
| `FIRMS_MAP_KEY` | clé FIRMS (affichage de l'état du quota dans l'admin) |

Sans `DATABASE_URL`, la base SQLite vit dans `/tmp` : l'administrateur ci-dessus est recréé à chaque
démarrage, mais les comptes, zones et réglages saisis en ligne ne sont pas conservés.

Mise à jour hebdomadaire de la saison :

```powershell
.\.venv\Scripts\python.exe -m firesync refresh
git add data/ ; git commit -m "Données FIRMS au JJ/MM" ; git push   # Vercel redéploie
```

## Architecture

```
firesync/
  ingest/       firms_country (archives), firms_api (NRT), landcover (MCD12Q1/ESA CCI),
                burned_area (MCD64A1), ndvi (MOD13A1), boundaries (geoBoundaries), earthdata (auth)
  processing.py détections propres → H3 res-7 (requêtes) et res-5 (modèle), semaines 0..51
  harmonize/    availability (pannes capteurs), pairing (passages ±60 min), models
                (naïf, ratio unique, ratio stratifié Bayes empirique, gradient boosting ensemble),
                uncertainty (membres + binomiale négative, κ calibré), validate, pipeline
  series.py     moteur de zone : polygone → H3 → série harmonisée + intervalles
  forecast.py   prévision IA 1–4 semaines, validation par saison retirée, ablation, calibration
  indicators.py début/pic/fin, semaines critiques, percentiles, tendances Theil-Sen
  report/       bulletin PDF bilingue (reportlab + matplotlib)
  api/          FastAPI, authentification (scrypt + jeton signé, cookie HttpOnly), SQLite
web/            SPA sans build : MapLibre GL, deck.gl (points), Observable Plot, i18n FR/EN
tests/          tests unitaires (pytest)
```

## Méthode (résumé)

1. **Cible** : équivalent VIIRS S-NPP — la série du futur est VIIRS ; le passé MODIS y est converti.
2. **Disponibilité** : détection des pannes de capteurs, correction des semaines partielles.
3. **Appariement** des passages Aqua / S-NPP et NOAA-20 / S-NPP (±60 min, voisinage co-observé).
4. **Modèle** : gradient boosting de Poisson par cellule H3 (~250 km²) × semaine, variantes Terra+Aqua,
   Terra seul (2000–2002), Aqua seul ; covariables MODIS (comptes, FRP, jour/nuit, semaines et cellules
   voisines), saison, occupation du sol MCD12Q1, a priori par cellule dont le rapport instantané apparié.
   Ensemble bootstrap sur les années → incertitude du modèle.
5. **Incertitude** : membres + bruit binomial négatif, intervalle log-normal calibré (κ) pour 90 % de
   couverture réelle **à chaque échelle** (cellule → pays, semaine et année).
6. **Continuité** NOAA-20 / NOAA-21 → S-NPP par cellule et saison (arrêt S-NPP le 1er novembre 2026).
7. **Allocation fine** : la valeur d'une cellule modèle est répartie dans le polygone selon les détections
   MODIS qu'il contient (ou la climatologie VIIRS quand MODIS ne voit rien).

### Résultats de validation (Sénégal + Gambie, années de feu 2012–2020 retirées une à une)

| Modèle | Erreur zone × semaine | Biais région × année | Couverture 90 % |
|---|---|---|---|
| Collage naïf | 72,7 % | −72,5 % | – |
| Ratio unique | 26,4 % | 0,0 % | – |
| Ratio stratifié (Bayes empirique) | 23,4 % | −0,4 % | 90 % |
| **Gradient boosting (FireSync)** | **21,0 %** | **+0,5 %** | **90 %** |

Test indépendant MCD64A1 : le rapport détections / surface brûlée saute de **×3,32** en 2012 avec le
collage naïf, contre **×1,04** avec la série harmonisée. Hors fenêtre (2021–2024, dérive orbitale de
Terra/Aqua) : erreur 21,7 %, biais −6,3 %.

## Prévision IA (alerte précoce)

- **Cible** : activité harmonisée de chaque cellule H3 (~250 km²) pour les semaines t+1 … t+4.
- **Variables** (toutes connues à la date d'émission) : normale saisonnière de la semaine visée (hors année
  prévue), activité de la dernière semaine et des 4 dernières, rapport à la normale, cumul de la saison
  (combustible déjà brûlé), bilan de la saison précédente, voisinage H3 res-3, occupation du sol MCD12Q1,
  position, saison et horizon.
- **Modèle** : gradient boosting de Poisson (scikit-learn), entraîné sur les cibles observées par VIIRS (2012 →).
- **Validation** : chaque saison 2013–2024 retirée à tour de rôle ; comparaison à la climatologie et à la
  persistance de l'anomalie ; score de compétence sur les totaux 4 semaines, score de Brier et AUC pour
  « au-dessus de la normale » (> 75e percentile), diagramme de fiabilité, intervalles 90 % calibrés.
- **Sorties** : prévisions par département / région / zone quelconque, niveau (risque élevé, risque modéré,
  normal ou inférieur, activité faible), classement « où agir en priorité », message d'alerte SMS FR / EN,
  encadré dans le bulletin PDF. Un niveau « élevé » ou « modéré » exige à la fois une anomalie (probabilité
  calibrée ou rapport à la normale) **et** un nombre de feux significatif (≥ 10 attendus, excédent absolu) :
  5 feux face à une normale de 1 ne déclenchent pas d'alerte.

## Logos et mentions

La plateforme affiche le logo du **NASA Space Apps Challenge** (cadre du projet, Dakar) et celui de
**SENSAT — Projet Spatial du Sénégal** (partenaire) : bandeau d'accueil, bloc « Cadre du projet &
partenaires », pied de page et en-tête des bulletins PDF. Les organisations fournisseurs de données (NASA
LANCE FIRMS, NASA LP DAAC / Earthdata, NOAA · NASA JPSS, Microsoft Planetary Computer, geoBoundaries,
OpenStreetMap · CARTO) sont citées en toutes lettres, sans reproduire leurs logos.

Les logos se gèrent dans Admin › Paramètres (une ligne par logo : `Nom | URL | /assets/partners/fichier.png |
challenge|partner|data | dark`), les fichiers étant déposés dans `web/assets/partners/`. FireSync Sahel n'est
pas un produit officiel de la NASA ; l'insigne NASA (« meatball ») et le logotype (« worm ») ne sont pas
utilisés.

> We acknowledge the use of data and imagery from LANCE FIRMS operated by NASA's Goddard Space Flight
> Center Earth Science Data and Information System (ESDIS) with funding provided by NASA Headquarters.

## Limites connues

- Sans `FIRMS_MAP_KEY`, les données s'arrêtent au 31/12/2025 (archives annuelles). Avec la clé, lancer
  `refresh` (ou Admin › Données & traitements) chaque semaine pour suivre la saison et réémettre la prévision.
- La prévision IA ne voit pas encore la météo (pluies de l'hivernage, vent, humidité) : c'est la prochaine
  étape (CHIRPS, ERA5).
- MCD12Q1 est utilisé pour une seule année (2016) : les changements d'occupation du sol ne sont pas suivis.
- Les détections satellitaires ne voient pas les feux sous nuages ou trop petits ; la série décrit l'activité
  de feu détectée, pas les surfaces brûlées.
- Sous Windows dans un dossier OneDrive, évitez `serve --reload` (la synchronisation perturbe le rechargement).
