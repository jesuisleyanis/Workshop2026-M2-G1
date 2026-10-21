# Prompt Claude Design — App bancaire « Banque Résilience »

> À coller dans Claude Design **avec la maquette jointe** (3 écrans noir & blanc : accueil « Hello », « States », « Send money »).
> Suivi : epic GitHub #52, une tâche D* = un ticket.

---

Tu conçois l'UI complète d'une **application bancaire mobile fictive** (démonstrateur pédagogique, toutes les données sont fictives). Tu es **autonome sur tous les choix visuels** : la maquette jointe donne la direction (noir & blanc, cartes de compte noires, grands rayons, ombres douces, beaucoup d'espace). Étends ce langage à tous les écrans ci-dessous.

## Cadre technique (à respecter)

- React + TypeScript + Tailwind CSS v4 (jetons dans `@theme`), pas de librairie UI ni de graphique lourde (SVG/CSS).
- **Aucune ressource externe** : la CSP interdit CDN, polices distantes, scripts et styles inline. Polices via `@fontsource`, icônes en SVG inline dans des composants.
- Mobile-first ; sur desktop, l'app s'affiche dans une colonne centrée.
- Langue : **français**, montants en euros (`1 234,56 €`), dates au format français.
- Chaque écran prévoit les états **chargement (squelette), vide, erreur + Réessayer**.
- Accessibilité : contraste AA, focus visible, cibles ≥ 44 px, curseurs et interrupteurs utilisables au clavier, graphiques avec alternative textuelle.
- IBAN et numéros de carte toujours **masqués** (`•••• 8160`) sauf écran RIB.

## Données disponibles (pour des maquettes réalistes)

- Utilisateur : nom d'utilisateur (ex. `alice`), session de 15 min (compte à rebours existant).
- Compte : `id`, `iban` fictif, `balance`, `currency`.
- Transaction : `id`, compte source, compte destination, `amount`, `status` (`created` | `rejected`), `createdAt`, `label` (facultatif), `category` (food, shopping, transport, subscriptions, health, leisure, housing, transfer, other), `requestId`.
- Bénéficiaire : `displayName`, `iban`.
- Plafond : plafond mensuel, consommé, restant, fin de période.
- Carte : 4 derniers chiffres, titulaire, expiration, statut (active / gelée), plafond de paiement, sans contact on/off, paiement en ligne on/off.
- Virement programmé : comptes, montant, fréquence (une fois / hebdo / mensuel), prochaine exécution, date de fin, statut (actif / en pause / annulé).
- Notification : type, titre, texte, date, lue / non lue.

## Tâches

**D1 — Design system et shell.** Jetons (couleurs, rayons, ombres, typo, espacements), composants de base (bouton principal/secondaire, champ, interrupteur, curseur, pastille de statut, carte de compte, ligne d'opération, squelettes). Shell mobile avec en-tête (titre/retour, cloche avec badge, avatar à initiales) et **barre d'onglets** : Accueil, Statistiques, Envoyer, Historique, Profil. Garder des couleurs sémantiques succès / refus / alerte.

**D2 — Accueil.** « Bonjour {utilisateur} », carrousel de cartes de comptes (solde, IBAN masqué) + « Ajouter », solde total, barre « Plafond restant » (%), rangée « Envoyer à » (bouton + et avatars des bénéficiaires), tuiles « Dépenses » (part du budget, raccourcis catégories), opérations récentes + « Voir tout ».

**D3 — Statistiques.** Total dépensé sur la période, graphique en barres par jour, sélecteur semaine / mois et navigation précédent/suivant, répartition par catégorie (cartes ou anneau avec %), opérations récentes de la période.

**D4 — Envoyer de l'argent.** Choix du compte (carrousel), montant (grand affichage, curseur, montants rapides 50/100/150/200 €, saisie libre), destinataire (recherche nom/IBAN, avatars, « +N »), catégorie, libellé, option « Programmer ». Bouton « Envoyer X € » → écran récapitulatif → écran résultat : **succès**, **refusé** (solde insuffisant / plafond dépassé), **erreur** (réessayer).

**D5 — Historique.** Liste groupée par jour, ligne d'opération (icône de catégorie, libellé, contrepartie, montant signé, statut refusé visible), filtres (statut, débit/crédit, catégorie, recherche), bouton Exporter.

**D6 — Bandeau d'état du service.** Bandeau non bloquant visible sur tous les écrans : « Service perturbé — reprise automatique en cours » puis « Service rétabli » (disparaît seul). Doit être très lisible à distance (démo projetée), sans paraître alarmant.

**D7 — Bénéficiaires.** Liste avec avatars à initiales, recherche, ajout (nom + IBAN, erreurs : IBAN inconnu, déjà enregistré), suppression avec confirmation, action « Envoyer ».

**D8 — Catégories.** Jeu d'icônes et de couleurs (en niveaux de gris) pour les 9 catégories ; sélecteur de catégorie réutilisable (Envoyer, filtres) ; vue détail d'une catégorie (total, opérations).

**D9 — Détail d'opération et RIB.** Fiche opération (montant, sens, statut, date/heure, comptes, catégorie, libellé, référence `requestId` copiable). Écran RIB par compte : titulaire, IBAN, BIC, boutons Copier / Partager / Imprimer + **version imprimable** du RIB.

**D10 — Plafonds.** Barre de plafond (accueil) et écran détail par compte : plafond, consommé, restant, date de remise à zéro ; message de refus « plafond dépassé » dans Envoyer.

**D11 — Cartes.** Visuel de carte noire (4 derniers chiffres, titulaire, expiration), état gelée clairement distinct, interrupteur Geler / Dégeler avec confirmation, réglages : plafond de paiement (curseur), sans contact, paiement en ligne.

**D12 — Virements programmés.** Liste (prochaine exécution, fréquence, statut), création (une fois / hebdo / mensuel, date de début, date de fin), pause / reprise, annulation avec confirmation, affichage d'une exécution échouée.

**D13 — Notifications.** Badge de non-lus sur la cloche, panneau ou page de notifications groupées par date, distinction lue / non lue, « Tout marquer comme lu », icône par type (virement émis/reçu/refusé, plafond 80 %, carte, virement programmé).

**D14 — Relevés.** Choix du compte et de la période, bouton « Télécharger CSV », **page imprimable** du relevé (en-tête banque fictive, titulaire, période, tableau des opérations, totaux) optimisée pour l'impression.

**D15 — Confirmation renforcée.** Modale déclenchée sur un gros virement : explication courte, saisie du mot de passe, états erreur / trop de tentatives / annulation, puis reprise du virement.

**D16 — Profil.** Nom d'utilisateur, temps de session restant, accès à Cartes, Bénéficiaires, Virements programmés, Relevés, RIB, et Déconnexion. Écran de connexion restylé dans le même langage (sans mot de passe pré-rempli).

## Livrable attendu

Les écrans D1→D16 en composants React/Tailwind prêts à intégrer, avec leurs états (chargement, vide, erreur, succès), en données fictives.
