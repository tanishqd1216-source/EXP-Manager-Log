# Vetic Experience Manager Dashboard

The **Vetic Experience Manager Dashboard** is a centralized tool for Experience Managers to review patient interaction history, track appointments, view clinic feedback, and follow Standard Operating Procedures (SOPs) and Key Result Areas (KRAs). 

This document explains the architecture, features, and overall data flow of the application.

---

## 1. Application Architecture

The application is built using a lightweight Python and vanilla web stack:
- **Backend**: FastAPI (Python) running on Uvicorn.
- **Database**: SQLite3 (`database.db`) storing user, appointment, and feedback records.
- **Frontend**: A single-page Vanilla HTML/JS/CSS dashboard (`clinic-experience-dashboard.html`).
- **Network Tunnel**: `ngrok` is used to expose the local dashboard securely over the internet on a permanent static domain (`upriver-glutinous-spoiler.ngrok-free.dev`).

### Key Files
- `app.py`: The main FastAPI server containing all API routes, authentication logic, and database query handlers.
- `sync_responses.py`: Contains the logic to parse CSV data, map columns to the database schema, generate unique fingerprints for rows, and seamlessly import new records into the SQLite database.
- `clinic-experience-dashboard.html`: The frontend UI.
- `run_ngrok.py`: A startup script that spins up both the FastAPI application and the ngrok tunnel concurrently.
- `Book1.xlsx`: A mapping file used to match appointment types to specific SOP actions.

---

## 2. Authentication & Access Control

The dashboard implements a basic session-based authentication system:
- Users log in via the `/login` route using their email and a hardcoded password.
- Upon success, a `session_token` cookie is set.
- **Clinic Restrictions**: Users can be mapped to specific clinics in the `USER_CLINIC_ACCESS` dictionary inside `app.py`. For example, `hina.sharma@vetic.in` is strictly locked to `"Vetic Pet Care, Sector 49, Noida"`. 
- If a user is restricted, the UI automatically filters out all data from other clinics, ensuring they only see information relevant to their location.

---

## 3. Data Flow & Google Form Integration

The dashboard is wired to a Google Form where Experience Managers submit daily feedback and notes. 

### How Syncing Works:
1. **Google Sheets Link**: The Google Form saves responses to a Google Sheet. This Sheet is published/exported as a CSV.
2. **Manual Sync**: The dashboard contains a **Sync Responses** button.
3. **Backend API (`/api/sync-responses`)**: 
   - When the sync button is clicked, the backend appends a cache-busting timestamp to the Google Sheets export URL.
   - It downloads the live CSV to a local file (`Experience Manager@Cx - Today.csv`).
   - It runs the `import_sheet_rows` function from `sync_responses.py`.
4. **Duplicate Prevention**: Every row is converted to a string payload and hashed into a `source_fingerprint` (SHA-256). The system checks this fingerprint against the database and skips any row that has already been imported, ensuring `0` duplicates.
5. **Dynamic Schema**: If the Google Form adds new questions (columns), the sync script automatically executes an `ALTER TABLE` to add these new columns to the SQLite database on the fly.

---

## 4. Frontend Features

The UI (`clinic-experience-dashboard.html`) is designed to be responsive and dynamic:
- **Live Search & Filters**: 
  - **Clinic Filter**: Dropdown to select a clinic (locked if the user has restricted access).
  - **Feedback Filter**: Filters records by 'Happy' or 'Unhappy'. The backend dynamically classifies feedback text based on keywords (e.g., "unhappy", "uh", "happy").
  - **Time Filter**: View records from *All Time*, *Daily (Today)*, or *Weekly (Last 7 Days)* based on the Form's `Timestamp` column.
  - **Text Search**: Search by user name or ID.
- **Patient Action Cards**: Records are shown as visual cards. Clicking a card opens a modal displaying all available data points (columns) for that specific record.
- **Action Case Modal**: Evaluates the `Appointment Type` of the selected record against the rules in `Book1.xlsx` and displays specific SOP action steps for the manager to follow.
- **SOP & KRA Viewer**: Embedded PDF viewers that allow managers to reference operational guidelines without leaving the dashboard.

---

## 5. Running the Application

To start the entire stack:
1. Open a terminal in the project directory.
2. Ensure the virtual environment is activated.
3. Run the startup script:
   ```bash
   python run_ngrok.py
   ```
4. The script will boot FastAPI on port `8000` and establish an `ngrok` tunnel.
5. The dashboard will be securely accessible worldwide via your static ngrok domain.

---

## Summary
This dashboard provides a robust, self-updating, and secure environment for Experience Managers. It seamlessly merges historical database data with live Google Form responses while strictly enforcing clinic-level data privacy.