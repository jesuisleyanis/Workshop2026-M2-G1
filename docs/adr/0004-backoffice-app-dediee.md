# ADR 0004 — Le back-office durci est une application dédiée (`services/backoffice`)

- **Statut :** accepté (Consigne Additionnelle 1, 2026-10-20)
- **Contexte :** la Consigne Additionnelle 1 demande de renforcer l'authentification du **back-office** (facteur visage + LED) et d'y intégrer la **gestion complète des habilitations**. Le dépôt possède déjà `services/front` (application **client** de la banque fictive) et `dashboard/` (supervision ZTR). Aucun des deux n'est un back-office privilégié d'administration.
- **Décision :** créer une petite application `services/backoffice` (React + Vite + TypeScript + Tailwind, même stack que le front) servie **derrière le WAF** sur une route/vhost dédiée, **réservée aux rôles `operator`/`admin`**. Elle porte : le login à étapes (identifiant → visage via `getUserMedia` → mot de passe) et l'écran d'habilitations (rôles + enrôlement/révocation des visages). Le **backend** (auth à étapes, `face-id`, pilotage LED) est **indépendant** de cette app : il est identique si l'équipe choisit l'option B (greffer l'écran sur `front`). Seul le lot L3 du backlog dépend de ce choix.
- **Alternative écartée :** durcir le login du `front` client — mélange l'accès client et l'accès privilégié, moins lisible pour le jury, et étend le facteur biométrique à des comptes qui n'en ont pas besoin.
- **Conséquences :**
  - (+) Séparation nette accès client / accès privilégié ; surface biométrique limitée aux comptes privilégiés (cohérent avec la décision D4 : la boucle ZTR ne dépend jamais du visage).
  - (+) Le « back-office » est un livrable identifiable pour le jury.
  - (−) Une app de plus à construire et durcir ; coût borné (réutilise la stack et le client API du front).
