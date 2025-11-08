# Real-Time

Real-Time Predictive Cash-Flow Dashboard

# NedVision – Cashflow Copilot (MVP)

AI‑assisted cashflow forecasting and “what‑if” simulations for SMEs.

This repo contains three services:

- **`analytics/`** — Python FastAPI service (time‑series forecasting + simulation)
- **`NedVision.Api/`** — .NET 8 Minimal API (orchestrator/proxy to analytics)
- **`nedvision-web/`** — Angular web app (dashboard + what‑if UI)

---

## 0) Prerequisites

- **Python 3.10+** (with `pip`)
- **.NET 8 SDK**
- **Node 18+ & npm** (Angular CLI installed globally: `npm i -g @angular/cli`)
- **Windows PowerShell** (commands below assume Windows paths)

> CSV data lives **outside Git** under `data/` and is not pushed to GitHub.

---

## 1) Folder layout

```
NedVision/
├─ analytics/            # Python FastAPI (main.py, requirements.txt)
├─ NedVision.Api/        # .NET 8 Minimal API
├─ nedvision-web/        # Angular app
├─ data/                 # CSVs (ignored by git)
└─ NedVision.sln
```

**CSV format (example columns)**  
`Date,Account,Description,Debit_ZAR,Credit_ZAR,Balance_ZAR,Category,Reference,Currency,FX_to_ZAR_at_Txn,Latitude,Longitude,Counterparty`

**File naming convention for auto‑discovery:**  
`statement_{BRANCH}_*.csv` (e.g., `statement_CPT02_2022-02.csv`)

---

## 2) Run order (local)

You’ll run **all three** services concurrently:

1. **Python analytics** → `http://127.0.0.1:8000`
2. **.NET API** → `http://127.0.0.1:5000` (proxies to analytics)
3. **Angular UI** → `http://127.0.0.1:4200` (calls .NET API)

> If 8000/5000/4200 are busy, pick any free ports and update the configs below.

---

## 3) Start the Analytics service (Python FastAPI)

```powershell
# From repo root
cd analytics

# Create & activate a virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install deps
pip install -r requirements.txt

# Point the service to your CSV directory (contains statement_{BRANCH}_*.csv)
# e.g., C:\Heckathon\NedVision\data
$env:NEDVISION_DATA_DIR="C:\Heckathon\NedVision\data"

# Run FastAPI
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Health check:** http://127.0.0.1:8000/health  
**Docs (Swagger):** http://127.0.0.1:8000/docs

**Sample request (PowerShell)**

```powershell
Invoke-RestMethod http://127.0.0.1:8000/forecast -Method POST -Body (@{
  branch = "CPT02"; horizon_days = 30
} | ConvertTo-Json) -ContentType "application/json"
```

---

## 4) Start the .NET API (orchestrator)

The .NET API proxies `POST /api/forecast` and `POST /api/simulate` to Python.

```powershell
# From repo root
cd NedVision.Api

# Ensure base URL points to your analytics port
# (appsettings.Development.json)
# {
#   "Analytics": { "BaseUrl": "http://127.0.0.1:8000" }
# }

dotnet restore
dotnet run --urls http://127.0.0.1:5000
```

**Health check:** http://127.0.0.1:5000/health  
**Swagger:** http://127.0.0.1:5000/swagger

**Sample request (PowerShell)**

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/forecast -Method POST -Body (@{
  branch = "CPT02"; horizon_days = 30
} | ConvertTo-Json) -ContentType "application/json"
```

> If you see a `422` about a missing `series` field, you’re hitting a different/old
> service on port 8000. Either stop the stray server or move FastAPI to `8001`
> and update `Analytics:BaseUrl` to `http://127.0.0.1:8001`.

---

## 5) Start the Angular UI

```powershell
# From repo root
cd nedvision-web
npm install
ng serve --port 4200
```

Open **http://127.0.0.1:4200**

- The **Dashboard** loads the 30‑day forecast (history tail + prediction).
- The **What‑if** page lets you apply deltas (e.g., salaries early, invoice late).

> The UI calls `http://127.0.0.1:5000` (configure inside `src/app/core/api.service.ts`).

---

## 6) Useful endpoints

**Analytics (FastAPI)**

- `GET /health`
- `POST /forecast`  
  Body: `{ "branch": "CPT02", "horizon_days": 30 }`
- `POST /simulate`  
  Body:
  ```json
  {
    "branch": "CPT02",
    "horizon_days": 30,
    "adjustments": [
      { "date": "2025-11-10", "delta": -250000, "label": "Salaries early" },
      { "date": "2025-11-14", "delta": 180000, "label": "Client payment late" }
    ]
  }
  ```

**.NET API**

- `GET /health`
- `POST /api/forecast`
- `POST /api/simulate`

---

## 7) Troubleshooting

- **Angular error `No provider for HttpHandler`**  
  Provide HttpClient at app root (standalone):

  ```ts
  // src/app/app.config.ts or main.ts
  import { provideHttpClient } from "@angular/common/http";
  export const appConfig = { providers: [provideHttpClient()] };
  ```

- **.NET returns 422 asking for `series`**  
  You’re hitting a different app on port 8000.

  - Verify FastAPI docs show `branch` (not `series`) at http://127.0.0.1:8000/docs
  - Or run FastAPI on 8001 and set `"Analytics:BaseUrl": "http://127.0.0.1:8001"`

- **CORS issues in Angular**  
  The .NET API enables permissive CORS for development in `Program.cs`. Confirm it’s running on `http://127.0.0.1:5000` and the UI calls that base URL.

- **Large CSVs**  
  For MVP, prefer monthly per‑branch CSVs. The single multi‑GB consolidated file should be ingested later with chunked reads.

---

## 8) Git hygiene

Root `.gitignore` should exclude heavy/ephemeral files:

```gitignore
# Node / Angular
node_modules/
dist/
.angular/
package-lock.json

# .NET
bin/
obj/
.vs/

# Python
__pycache__/
.venv/
*.pyc

# Local data
data/
*.csv
*.xlsx
```

If you accidentally committed `.venv` or `node_modules`, untrack them:

```powershell
git rm -r --cached analytics/.venv
git rm -r --cached nedvision-web/node_modules
git commit -m "Cleanup: remove venv/node_modules from repo"
git push
```

---

## 9) Demo script (suggested flow)

1. Load dashboard → shows current balance + 30‑day forecast.
2. Click **View what‑if** → apply “Salaries early” (−250k) → chart dips.
3. Apply “Invoice late” (+180k in a few days) → compare paths.
4. Point to **drivers** (top inflow/outflow categories) and explain forecast rationale.
5. (Optional) Call an **AI explanation** endpoint to summarize risks & actions.

---

## 10) Notes & roadmap

- Replace bar chart with line/area + tooltips for richer UX.
- Persist curated data to **SQLite/Azure SQL** behind the .NET API.
- Add Azure AI Foundry endpoint (`/api/explain`) with a grounded prompt using drivers.
- Wire a simple “Invoices Due” CRUD or pull from a separate CSV/table.
- Deploy: Containerize FastAPI + .NET and host on Azure (App Service or Container Apps).

---

**Made with ❤️ for the Nedbank Hackathon.**
