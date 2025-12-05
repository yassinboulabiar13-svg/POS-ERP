# Vente en Magasin - Backend (Flask)

Dossier: `vente-backend/`

## But
Backend Flask minimal pour la fonctionnalité "Vente en Magasin" du POS :
- Gestion articles, panier, checkout, factures
- Règles métiers : TVA, remises, réservation stock, simulation de paiement
- Base SQLite `pos_vente.db`

## Prérequis
- Python 3.10+ recommandé
- git (optionnel)

## Installation (Linux / macOS / WSL)
```bash
cd vente-backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# initialiser la DB (si pos_vente.db manquant, il est créé automatiquement à la première exécution)
python app.py
