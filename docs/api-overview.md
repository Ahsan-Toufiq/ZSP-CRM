# API Overview

Base local API URL:

```text
http://127.0.0.1:8000/api
```

Authentication uses Django sessions and CSRF cookies.

## Auth

- `GET /auth/csrf/`
- `POST /auth/login/`
- `POST /auth/logout/`
- `GET /auth/me/`

## Operations

- `GET|POST /operations/customers/`
- `GET|PATCH|DELETE /operations/customers/{id}/`
- `GET|POST /operations/containers/`
- `GET|PATCH|DELETE /operations/containers/{id}/`
- `GET|POST /operations/items/`
- `GET|PATCH|DELETE /operations/items/{id}/`
- `GET|POST /operations/auction-sales/`
- `GET /operations/auction-sales/sold-without-gate-pass/`
- `GET|POST /operations/gate-passes/`
- `POST /operations/gate-passes/{id}/verify/`

## Finance

- `GET|POST /finance/cheque-statuses/`
- `GET|PATCH|DELETE /finance/cheque-statuses/{id}/`
- `GET|POST /finance/cheques/`
- `POST /finance/cheques/{id}/change-status/`
- `GET /finance/cheques/{id}/history/`
- `GET /finance/ledger/`
- `GET /finance/customer-balances/`
- `GET /finance/dashboard-summary/`

All list endpoints are paginated by default.
