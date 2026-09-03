# Digi7 ZSP Auctions

New-build replacement for the legacy ZSP spare-parts CRM. This app is designed around the real business flow: imported spare-parts containers, auction sales, gate-pass release control, cheque tracking, and customer balances.

## Stack

- Backend: Django + Django REST Framework
- Frontend: Next.js + React + TypeScript
- Database: PostgreSQL
- Auth: Django session auth with CSRF protection
- Local infrastructure: Docker Compose PostgreSQL

## Business Scope

ZSP receives overseas containers containing spare parts. Each container has a manifest/list of individual parts. Those parts are auctioned off individually, and sold items must not leave the premises until a gate pass is issued and verified.

The system currently supports:

- Customer directory with real customer balance calculation.
- Container registry.
- Container item inventory with unique lot numbers per container.
- Auction sale recording.
- One-sale-per-item protection.
- Cash sales without mandatory customer.
- Credit, cheque, and mixed sales requiring a customer.
- Gate-pass issuing for one or multiple sold items.
- One-gate-pass-per-sold-item protection.
- Gate-pass verification that marks items as released.
- Gate-pass editing before verification.
- Gate-pass print tracking with a two-copy print layout.
- Cheque register.
- System cheque statuses: `Pending`, `Bounced`, `Settled`, `Settled by Cash`, `Cleared`.
- Custom cheque statuses.
- Cheque entry from the auction sale dialog when payment type is cheque.
- Persisted dropdown values for banks, item categories, item conditions, and units.
- Ledger-based customer receivables.
- API-level role permissions.

## Local Setup

From the project root:

```bash
docker compose up -d db
```

Backend:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 127.0.0.1:8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Open:

- Frontend: http://127.0.0.1:3000
- Backend admin: http://127.0.0.1:8000/admin/

## Local Demo Users

These are local seed credentials only. Do not use these passwords in production.

| Username | Password | Role |
| --- | --- | --- |
| `admin` | `Admin@12345` | Superuser / Admin |
| `operator` | `Operator@12345` | Operations |
| `finance` | `Finance@12345` | Finance |
| `gatekeeper` | `Gatekeeper@12345` | Gatekeeper |

## Environment

Backend production variables are documented in [backend/.env.example](backend/.env.example).

Frontend production variables are documented in [frontend/.env.example](frontend/.env.example).

Required production values:

- `SECRET_KEY`
- `DJANGO_DEBUG=false`
- `ALLOWED_HOSTS`
- `DATABASE_URL`
- `CORS_ALLOWED_ORIGINS`
- `CSRF_TRUSTED_ORIGINS`
- `SESSION_COOKIE_SECURE=true`
- `CSRF_COOKIE_SECURE=true`
- `NEXT_PUBLIC_API_BASE_URL`

## Production Notes

- Use managed PostgreSQL.
- Run migrations during deploy.
- Do not run demo seed data in production.
- Put frontend and backend behind HTTPS.
- Keep the backend API origin in CORS/CSRF allowlists.
- Use separate production users with strong passwords.
- Add backups before replacing the existing ZSP deployment.

## Current Verification

Backend service tests cover:

- Credit sale ledger debit.
- Customer required for non-cash sale.
- Duplicate sale prevention for the same item.
- Gate-pass issue and verify flow.
- Gate-pass editing and print-status reset.
- Cheque sale creation.
- Cheque settlement ledger credit.
- Bounced cheque reversal.

Frontend checks cover:

- TypeScript type checking.
- Next production build.
- ESLint.

See [docs/production-readiness.md](docs/production-readiness.md) for what is complete versus still required before live replacement.
