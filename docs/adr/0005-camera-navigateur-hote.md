# ADR 0005 — La caméra USB est lue dans le navigateur de l'hôte (`getUserMedia`)

- **Statut :** accepté (Consigne Additionnelle 1, 2026-10-20)
- **Contexte :** la consigne impose que la **caméra USB soit branchée sur le PC Hôte** (celui qui délivre le PA `RESILIENCE-G1` et héberge la stack Docker). Docker Desktop / WSL2 ne fait pas de passthrough USB fiable pour une webcam UVC : un service conteneurisé ne peut pas ouvrir `/dev/video0` de l'hôte Windows simplement.
- **Décision :** le back-office est **ouvert dans le navigateur du PC Hôte**. L'étape d'identification utilise `navigator.mediaDevices.getUserMedia()` pour accéder à la **caméra USB de l'hôte**, capture une trame, l'encode (JPEG base64) et l'envoie à `auth`, qui la relaie au service `face-id` conteneurisé pour la vérification 1:1. La caméra n'est **active que pendant l'étape d'identification** et **coupée** dès la phase terminée (exigence consigne + vie privée). Aucune image n'est persistée ; `face-id` ne conserve que l'**embedding**.
- **Alternatives écartées :**
  - *Agent de capture côté hôte (hors Docker)* poussant les trames vers `face-id` — composant Windows supplémentaire à installer et maintenir, sans bénéfice ici puisque le back-office est déjà ouvert sur l'hôte.
  - *Passthrough USB dans WSL2* (`usbipd`) — fragile, non reproductible, dépendant de la version de Windows.
- **Conséquences :**
  - (+) Satisfait l'exigence « caméra sur le PC Hôte » sans dépendance OS supplémentaire ; reproductible.
  - (+) La trame transite chiffrée via le WAF (HTTPS) ; `face-id` reste interne (réseau `app`).
  - (−) Dépend d'un contexte sécurisé (HTTPS/localhost) pour `getUserMedia` — garanti par le WAF ; à documenter dans le runbook de recette.
