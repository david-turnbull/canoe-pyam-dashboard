# CANOE pyam dashboard

A Streamlit dashboard for comparing **pyam-IAMC-style** datasets across multiple files.  
Filter by **Activity / Capacity / Emissions**, choose **Level-2** aggregation or **Level-3+ technology breakdown**, and visualize with pyam-standard chart types. Export the aggregated view as CSV.


##  Order of operations

1. **Convert Excel workbooks to CSV (if needed)** and ensure **Unit** is present.
2. **Create a virtual environment** in the project directory.
3. **Activate** the environment.
4. **Install dependencies** from `requirements.txt`.
5. **Run** the app with Streamlit.

---

## Setup

### 1) Create & activate a virtual environment

**Windows (PowerShell):**
```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Install requirements
```bash
pip install -r requirements.txt
```

### 3) Run the app
```bash
streamlit run pyam_dashboard.py
```
This opens the dashboard in your browser (usually `http://localhost:8501`).

### 4) Stop & deactivate
- Stop: press **CTRL+C** in the terminal running Streamlit.  
- Deactivate venv: `deactivate`

---

## Using the dashboard

1. **Upload** one or more CSV/XLSX pyam files.
2. Select **Category** (Activity / Capacity / Emissions).
3. Choose **chart type** and **comparison mode** (Overlay, Facet by dataset, or Stack).
4. Pick **Aggregation detail**:
   - **Level-2 (sum technologies)** — higher-level overview
   - **Level-3+ (technology breakdown)** — composition inside each Level-2
5. Filter by **Model / Scenario / Region** and select which **Level-2** items to include.
6. (For bar charts) choose the **single year**.
7. **Download** the aggregated table as CSV if needed.


