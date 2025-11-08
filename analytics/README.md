
# NedVision Analytics Service (FastAPI)

## Quick start (Windows PowerShell)
```powershell
cd analytics
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# Point to your CSV directory (contains statement_{BRANCH}_*.csv files)
$env:NEDVISION_DATA_DIR="C:\Heckathon\NedVision\data"

# Run the service
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Endpoints
- GET /health
- POST /forecast
- POST /simulate

### Example body: /forecast
```json
{
  "branch": "CPT02",
  "horizon_days": 30
}
```
