\# payments-backend



Backend Flask pour le module "Paiements \& Encaissements".



\## Structure

\- app.py : serveur Flask principal

\- pos\_payments.db : base SQLite (créée automatiquement)



\## Pré-requis

\- Python 3.11+ recommandé

\- pip



\## Installation

1\. Créer et activer un environnement virtuel

&nbsp;  - Windows:

&nbsp;    python -m venv venv

&nbsp;    venv\\Scripts\\activate

&nbsp;  - macOS / Linux:

&nbsp;    python -m venv venv

&nbsp;    source venv/bin/activate



2\. Installer dépendances

&nbsp;  pip install -r requirements.txt



3\. Lancer le serveur

&nbsp;  python app.py

&nbsp;  Le serveur écoute sur http://0.0.0.0:5003



\## Endpoints principaux

\- GET `/health` — check

\- POST `/payments/initiate` — initier un paiement (idempotent avec client\_payment\_id)

\- POST `/payments/authorize/<payment\_id>` — autoriser paiement électronique (simulé)

\- POST `/payments/confirm/<payment\_id>` — confirmer/capturer paiement et générer reçu

\- GET `/payments/<payment\_id>` — consulter paiement

\- GET `/payments` — lister paiements

\- GET `/receipts/<receipt\_number>` — récupérer reçu

\- GET `/admin/erp\_queue` — lister file ERP

\- POST `/admin/force\_sync/<payment\_id>` — forcer sync ERP

\- POST `/admin/approve/<payment\_id>` — donner approbation manager (pour montants élevés)



\## Règles métier importantes

\- Seuil d'approbation manager : `MANAGER\_APPROVAL\_THRESHOLD` (par défaut 1000.0)

\- Idempotence : `client\_payment\_id` unique par tentative de paiement

\- Simulated provider: authorize succeeds deterministically if last digit of card number is even

\- ERP sync simulated by un worker en arrière-plan; les paiements impairs peuvent rester non syncés et nécessiter intervention admin



\## Tests (curl)

Voir `test\_curl.sh` pour les commandes d'exemple. En PowerShell, utiliser `Invoke-RestMethod` équivalent.





