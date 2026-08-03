from pathlib import Path
from datetime import datetime, timedelta
import math
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from fastapi import FastAPI, Request, Form, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from pydantic import BaseModel
import gspread
from google.oauth2.service_account import Credentials
import time

BASE_DIR = Path(__file__).resolve().parent
HTML_FILE = BASE_DIR / "clinic-experience-dashboard.html"
SOP_FILE = BASE_DIR / "Experience Manager@Cx - SOP.pdf"
KRA_FILE = BASE_DIR / "Experience Manager@Cx - KRA's.pdf"
APPOINTMENT_ACTIONS_FILE = BASE_DIR / "Book1.xlsx"

VALID_USER_PASSWORD = "Password123"
SESSION_COOKIE_NAME = "session_token"
SESSIONS = {}

USER_CLINIC_ACCESS = {
    "hina.sharma@vetic.in": "Vetic Pet Care, Sector 49, Noida",
    "bhawna.kashyap@vetic.in": "Vetic Pet Care Centre, Greater Kailash 1 ,New Delhi",
}
USER_DISPLAY_NAMES = {
    "hina.sharma@vetic.in": "Hina Sharma",
    "bhawna.kashyap@vetic.in": "Bhawna Kashyap",
}
# Google Form responses don't collect a Clinic Name field, so rows always leave
# it blank. Experience Manager Name is filled in every time and each manager
# only ever reports for one clinic, so it's used as a fallback clinic match.
EXPERIENCE_MANAGER_CLINIC_MAP = {
    "hina": "Vetic Pet Care, Sector 49, Noida",
    "hna": "Vetic Pet Care, Sector 49, Noida",
    "bhawna": "Vetic Pet Care Centre, Greater Kailash 1 ,New Delhi",
}

app = FastAPI()

try:
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_file(str(BASE_DIR / 'credentials'), scopes=scopes)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key('1yQe_HE7MeEm4QFaoPpdiaGY_P_9K2EphmmoAUK3xdHE')
    WORKSHEETS = [
        sheet.get_worksheet_by_id(1293063869),
        sheet.get_worksheet_by_id(1381377826)
    ]
except Exception as e:
    print(f"Failed to connect to Google Sheets: {e}")
    WORKSHEETS = []

SHEET_CACHE = {"records": [], "last_fetched": 0, "headers": []}
CACHE_TTL = 30

def get_sheet_records():
    global SHEET_CACHE
    if time.time() - SHEET_CACHE["last_fetched"] > CACHE_TTL and WORKSHEETS:
        all_records = []
        all_headers = []
        for ws_idx, ws in enumerate(WORKSHEETS):
            if not ws: continue
            all_values = ws.get_all_values()
            if not all_values: continue
            
            # Find the header row (look in first 5 rows)
            header_row_idx = 0
            for idx, row in enumerate(all_values[:5]):
                row_str = " ".join([str(c).lower() for c in row])
                if 'client_name' in row_str or 'clinic name' in row_str or 'timestamp' in row_str or 'appt id' in row_str:
                    header_row_idx = idx
                    break
                    
            headers = all_values[header_row_idx]
            data_rows = all_values[header_row_idx + 1:]
            records = [dict(zip(headers, row)) for row in data_rows if any(row)]
            
            if not all_headers:
                all_headers = headers
            else:
                for h in headers:
                    if h not in all_headers:
                        all_headers.append(h)
                        
            # Data starts at row header_row_idx + 2 in 1-indexed Google Sheets
            for i, row in enumerate(records):
                row['db_rowid'] = f"{ws_idx}_{header_row_idx + i + 2}"
                all_records.append(row)
                
        SHEET_CACHE["records"] = all_records
        SHEET_CACHE["headers"] = all_headers
        SHEET_CACHE["last_fetched"] = time.time()
    return SHEET_CACHE["records"], SHEET_CACHE["headers"]

FIXED_CLINICS = [
    "Vetic Pet Care Centre, Andheri West, Mumbai",
    "Vetic Pet Care Centre, Sector 45",
    "Vetic Pet Care, Sector 49, Noida",
    "Vetic Pet Care Centre, Greater Kailash 1 ,New Delhi",
    "Vetic Pet Care Centre, Chembur, Mumbai",
    "Vetic Pet Care, Dwarka Sector 17, New Delhi",
]

def normalize_text(value: str) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()

def get_display_fields(row):
    field_candidates = [
        ("Client Name", ["client_name", "customer_name", "client"]),
        ("Appointment Type", ["appointment_type", "appointment type", "service"]),
        ("Date", ["date", "appointment_date", "start_time", "created_at"]),
        ("Resource Details", ["resource_details", "resource", "resource_name"]),
        ("Booking Source", ["booking_source", "booking source", "source"]),
        ("Done", ["done", "status"]),
    ]
    values = []
    for label, aliases in field_candidates:
        for key in row.keys():
            if any(normalize_text(key) == normalize_text(alias) for alias in aliases):
                value = row.get(key)
                if value is not None and str(value).strip() != "":
                    values.append((label, str(value).strip()))
                break
    return values

def row_matches_clinic(row, clinic_cols, target):
    for col in clinic_cols:
        val = row.get(col, "")
        if val and str(val).strip():
            return normalize_text(val) == target
    manager_col = next((k for k in row.keys() if normalize_text(k) == "experience manager name"), None)
    if manager_col:
        # Managers retype their name by hand on every form submission, so it
        # varies row to row (e.g. "Bhawna Kashyap ", "Bhawna r", "H8Na" with a
        # stray digit). Strip digits before matching, and match on whichever
        # mapped key appears anywhere in the typed name, rather than requiring
        # an exact match, so it keeps working across variations.
        manager = re.sub(r"[0-9]", "", normalize_text(row.get(manager_col, "")))
        for key, mapped_clinic in EXPERIENCE_MANAGER_CLINIC_MAP.items():
            if key and key in manager:
                return normalize_text(mapped_clinic) == target
    return False

def get_client_name(row):
    for key in row.keys():
        if any(normalize_text(key) == normalize_text(alias) for alias in ["client_name", "customer_name", "client"]):
            value = row.get(key)
            if value is not None:
                return normalize_text(str(value))
    return ""

def create_session(email: str) -> str:
    token = uuid.uuid4().hex
    SESSIONS[token] = email
    return token

def get_current_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    return SESSIONS.get(token)

def get_user_allowed_clinic(email: str):
    if not email:
        return None
    return USER_CLINIC_ACCESS.get(email.strip().lower())

def require_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user

def login_page(error: str = "") -> str:
    error_html = f"<p class='error'>{error}</p>" if error else ""
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
<meta charset=\"UTF-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
<title>Vetic Login</title>
<style>
  body {{ margin: 0; font-family: 'Inter', sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; background: #eef4fb; }}
  .login-card {{ width: min(420px, 90vw); background: #fff; padding: 36px; border-radius: 22px; box-shadow: 0 24px 60px rgba(15, 42, 84, 0.12); }}
  h1 {{ margin: 0 0 12px; font-size: 28px; color: #1a3c82; }}
  p {{ margin: 0 0 22px; color: #4a5568; line-height: 1.5; }}
  .input-group {{ margin-bottom: 18px; }}
  label {{ display: block; margin-bottom: 8px; font-size: 13px; color: #5f6c87; text-transform: uppercase; letter-spacing: 0.04em; }}
  input {{ width: 100%; padding: 14px 16px; border: 1px solid #d5dce8; border-radius: 14px; font-size: 15px; outline: none; transition: border-color 0.2s; }}
  input:focus {{ border-color: #3f76f1; box-shadow: 0 0 0 4px rgba(63, 118, 241, 0.08); }}
  button {{ width: 100%; padding: 14px 18px; border: none; border-radius: 14px; background: #1a73e8; color: #fff; font-size: 15px; font-weight: 700; cursor: pointer; transition: background 0.2s; }}
  button:hover {{ background: #1557b0; }}
  .error {{ margin: 0 0 16px; color: #c5221f; font-weight: 600; }}
</style>
</head>
<body>
  <div class=\"login-card\">
    <h1>Vetic Login</h1>
    <p>Enter your email and password to access the Experience Manager dashboard.</p>
    {error_html}
    <form method=\"post\" action=\"/login\">
      <div class=\"input-group\">
        <label for=\"email\">Email</label>
        <input id=\"email\" type=\"email\" name=\"email\" required>
      </div>
      <div class=\"input-group\">
        <label for=\"password\">Password</label>
        <input id=\"password\" type=\"password\" name=\"password\" required>
      </div>
      <button type=\"submit\">Sign In</button>
    </form>
  </div>
</body>
</html>"""

def load_appointment_action_map():
    mapping = {}
    if not APPOINTMENT_ACTIONS_FILE.exists():
        return mapping
    with zipfile.ZipFile(APPOINTMENT_ACTIONS_FILE, 'r') as z:
        shared_strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            shared_xml = ET.fromstring(z.read('xl/sharedStrings.xml'))
            ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            for si in shared_xml.findall('.//ns:si', ns):
                shared_strings.append(''.join(t.text or '' for t in si.findall('.//ns:t', ns)))
        sheet_xml = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        for row in sheet_xml.findall('.//ns:row', ns):
            cells = {}
            for cell in row.findall('ns:c', ns):
                ref = cell.attrib.get('r', '')
                value_node = cell.find('ns:v', ns)
                if value_node is None: continue
                value = value_node.text or ''
                if cell.attrib.get('t') == 's':
                    try:
                        value = shared_strings[int(value)]
                    except Exception:
                        pass
                match = re.match(r'^([A-Z]+)', ref)
                if match:
                    cells[match.group(1)] = value.strip()
            appointment_type = cells.get('B', '').strip()
            action_text = cells.get('D', '').strip()
            if appointment_type and action_text:
                key = normalize_text(appointment_type)
                mapping.setdefault(key, []).append(action_text)
    for key, actions in mapping.items():
        mapping[key] = list(dict.fromkeys(actions))
    return mapping

APPOINTMENT_ACTION_MAP = load_appointment_action_map()

def classify_feedback(value: str) -> str:
    if value is None:
        return "neutral"
    text = str(value).strip().lower()
    normalized = " ".join(text.replace("-", " ").replace("_", " ").split())
    unhappy_terms = ["unhappy", "un happy", "unh", "uh", "uhh", "u", "un-happy", "uh-h"]
    happy_terms = ["happy", "h", "hp"]
    has_unhappy = any(term in normalized for term in unhappy_terms)
    has_happy = any(term in normalized for term in happy_terms)
    if has_unhappy and not has_happy:
        return "unhappy"
    if has_happy and not has_unhappy:
        return "happy"
    if has_unhappy and has_happy:
        unhappy_score = sum(1 for term in unhappy_terms if term in normalized)
        happy_score = sum(1 for term in happy_terms if term in normalized)
        return "unhappy" if unhappy_score >= happy_score else "happy"
    return "neutral"

def get_row_feedback_state(row: dict) -> str:
    feedback_values = [
        str(value) for key, value in row.items()
        if (key.lower().startswith("feedback") or key.lower().startswith("customer") or key.lower().startswith("rating"))
        and value is not None and str(value).strip() != ""
    ]
    if not feedback_values:
        return "neutral"
    return classify_feedback(" ".join(feedback_values))

def find_actions_for_appointment_type(appointment_type: str):
    normalized = normalize_text(appointment_type)
    if not normalized:
        return []
    if normalized in APPOINTMENT_ACTION_MAP:
        return APPOINTMENT_ACTION_MAP[normalized]
    for key, actions in APPOINTMENT_ACTION_MAP.items():
        if key in normalized or normalized in key:
            return actions
    return []

@app.get("/login", response_class=HTMLResponse)
def get_login(request: Request):
    if get_current_user(request):
        return RedirectResponse(url='/', status_code=302)
    return HTMLResponse(login_page())

@app.post("/login")
def post_login(request: Request, email: str = Form(...), password: str = Form(...)):
    if password == VALID_USER_PASSWORD:
        token = create_session(email.strip().lower())
        response = RedirectResponse(url='/', status_code=302)
        response.set_cookie(key=SESSION_COOKIE_NAME, value=token, httponly=True, path='/')
        return response
    return HTMLResponse(login_page("Invalid email or password."), status_code=401)

@app.get("/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        SESSIONS.pop(token, None)
    response = RedirectResponse(url='/login', status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME, path='/')
    return response

@app.get("/api/session")
def get_session(request: Request, current_user: str = Depends(require_auth)):
    allowed_clinic = get_user_allowed_clinic(current_user)
    display_name = USER_DISPLAY_NAMES.get(current_user.strip().lower(), current_user)
    return {
        "email": current_user,
        "display_name": display_name,
        "allowed_clinic": allowed_clinic,
        "can_change_clinic": allowed_clinic is None,
    }

@app.get("/api/clinics")
def get_clinics(request: Request, current_user: str = Depends(require_auth)):
    allowed_clinic = get_user_allowed_clinic(current_user)
    try:
        if allowed_clinic:
            return {"clinics": [allowed_clinic]}

        users, headers = get_sheet_records()
        clinic_cols = [c for c in headers if 'clinic' in c.lower() or 'location' in c.lower() or 'center' in c.lower() or c in ['Region', 'City']]
        if not clinic_cols:
            return {"clinics": sorted(FIXED_CLINICS)}

        clinic_values = set(FIXED_CLINICS)
        for row in users:
            for col in clinic_cols:
                if row.get(col):
                    clinic_values.add(str(row[col]).strip())

        clinics = sorted([c for c in clinic_values if c], key=lambda item: normalize_text(item))
        return {"clinics": clinics}
    except Exception as e:
        return {"error": str(e), "clinics": []}

@app.get("/api/summary")
def get_summary(request: Request, current_user: str = Depends(require_auth)):
    allowed_clinic = get_user_allowed_clinic(current_user)
    try:
        users, headers = get_sheet_records()
        clinic_cols = [c for c in headers if 'clinic' in c.lower() or 'location' in c.lower() or 'center' in c.lower() or c in ['Region', 'City']]
        clinics_to_summarize = [allowed_clinic] if allowed_clinic else FIXED_CLINICS

        def count_bucket(rows):
            happy = sum(1 for r in rows if get_row_feedback_state(r) == "happy")
            unhappy = sum(1 for r in rows if get_row_feedback_state(r) == "unhappy")
            return {"total": len(rows), "happy": happy, "unhappy": unhappy, "neutral": len(rows) - happy - unhappy}

        clinic_summaries = []
        matched_rowids = set()
        for clinic in clinics_to_summarize:
            target = normalize_text(clinic)
            clinic_rows = [row for row in users if row_matches_clinic(row, clinic_cols, target)]
            matched_rowids.update(row.get("db_rowid") for row in clinic_rows)
            clinic_summaries.append({"clinic": clinic, **count_bucket(clinic_rows)})

        # Rows that don't map to any known clinic (e.g. an unrecognized/typoed
        # manager name) are surfaced explicitly rather than silently dropped —
        # this exact class of bug has bitten this dashboard before.
        unmatched_rows = [row for row in users if row.get("db_rowid") not in matched_rowids] if not allowed_clinic else []
        unmatched = count_bucket(unmatched_rows) if not allowed_clinic else None

        totals = {
            "total": sum(s["total"] for s in clinic_summaries) + (unmatched["total"] if unmatched else 0),
            "happy": sum(s["happy"] for s in clinic_summaries) + (unmatched["happy"] if unmatched else 0),
            "unhappy": sum(s["unhappy"] for s in clinic_summaries) + (unmatched["unhappy"] if unmatched else 0),
            "neutral": sum(s["neutral"] for s in clinic_summaries) + (unmatched["neutral"] if unmatched else 0),
        }

        return {"clinics": clinic_summaries, "unmatched": unmatched, "totals": totals}
    except Exception as e:
        return {"error": str(e), "clinics": [], "unmatched": None, "totals": None}

@app.get("/api/feedbacks")
def get_feedbacks(request: Request, current_user: str = Depends(require_auth)):
    try:
        users, headers = get_sheet_records()
        feedback_col = next((c for c in headers if 'feedback' in c.lower()), None)
        if feedback_col:
            fbs = {str(row[feedback_col]).strip() for row in users if row.get(feedback_col)}
            feedbacks = sorted([f for f in fbs if f])
        else:
            feedbacks = []
        return {"feedbacks": feedbacks}
    except Exception as e:
        return {"error": str(e), "feedbacks": []}

@app.get("/api/users")
def search_users(request: Request, clinic: str = "", feedback: str = "", user_search: str = "", time_filter: str = "all", start_date: str = "", end_date: str = "", page: int = 1, limit: int = 25, current_user: str = Depends(require_auth)):
    allowed_clinic = get_user_allowed_clinic(current_user)
    if allowed_clinic:
        clinic = allowed_clinic

    # Restricted managers always have `clinic` auto-filled above, so reaching
    # here with no clinic/search means an unrestricted admin browsing without
    # a filter — show every sheet response rather than nothing.
    try:
        users, headers = get_sheet_records()
        clinic_cols = [c for c in headers if 'clinic' in c.lower() or 'location' in c.lower() or 'center' in c.lower() or c in ['Region', 'City']]
        name_cols = [c for c in headers if 'name' in c.lower() and 'clinic' not in c.lower() and 'pet' not in c.lower() and 'service' not in c.lower()]
        id_cols = [c for c in headers if 'id' in c.lower() and 'ticket' not in c.lower()]
        
        if clinic:
            target = normalize_text(clinic)
            users = [row for row in users if row_matches_clinic(row, clinic_cols, target)]
            
        if user_search:
            search_target = normalize_text(user_search)
            users = [row for row in users if any(search_target in normalize_text(row.get(col, "")) for col in name_cols + id_cols)]

        if feedback and feedback.lower() != "all":
            filtered_users = []
            for row in users:
                feedback_values = []
                for key, value in row.items():
                    if key.lower().startswith("feedback") or key.lower().startswith("customer") or key.lower().startswith("rating"):
                        if value is not None and str(value).strip() != "":
                            feedback_values.append(str(value))
                if not feedback_values:
                    filtered_users.append(row)
                    continue
                combined = " ".join(feedback_values)
                if classify_feedback(combined) == feedback.lower():
                    filtered_users.append(row)
            users = filtered_users

        def _get_ts(r):
            ts_str = r.get("Timestamp") or r.get("created_at") or r.get("date")
            if ts_str:
                try:
                    return datetime.strptime(str(ts_str).strip(), "%d/%m/%Y %H:%M:%S")
                except:
                    pass
            return datetime.min

        if time_filter in ["daily", "weekly", "custom"]:
            filtered_by_time = []
            now = datetime.now()
            custom_start = None
            custom_end = None
            if time_filter == "custom":
                try:
                    if start_date: custom_start = datetime.strptime(start_date, "%Y-%m-%d").date()
                    if end_date: custom_end = datetime.strptime(end_date, "%Y-%m-%d").date()
                except:
                    pass

            for r in users:
                ts = _get_ts(r)
                if ts != datetime.min:
                    r_date = ts.date()
                    if time_filter == "daily" and r_date == now.date():
                        filtered_by_time.append(r)
                    elif time_filter == "weekly" and r_date >= (now.date() - timedelta(days=7)):
                        filtered_by_time.append(r)
                    elif time_filter == "custom":
                        if custom_start and r_date < custom_start:
                            continue
                        if custom_end and r_date > custom_end:
                            continue
                        filtered_by_time.append(r)
            users = filtered_by_time

        users.sort(key=_get_ts, reverse=True)
        total_records = len(users)
        total_pages = math.ceil(total_records / limit) if limit > 0 else 1
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_users = users[start_idx:end_idx]
        
        return {
            "users": paginated_users,
            "total_records": total_records,
            "total_pages": total_pages,
            "current_page": page,
            "limit": limit
        }
    except Exception as e:
        return {"error": str(e), "users": [], "total_records": 0, "total_pages": 1, "current_page": 1}



@app.get("/api/actions")
def get_actions(request: Request, appointment_type: str = "", current_user: str = Depends(require_auth)):
    actions = find_actions_for_appointment_type(appointment_type)
    return {"appointment_type": appointment_type, "actions": actions}

@app.get("/api/sop")
def get_sop_pdf(request: Request, current_user: str = Depends(require_auth)):
    if SOP_FILE.exists():
        headers = {"Content-Disposition": f'inline; filename="{SOP_FILE.name}"'}
        return FileResponse(SOP_FILE, media_type="application/pdf", headers=headers)
    return {"error": "SOP PDF not found"}

@app.get("/api/kra")
def get_kra_pdf(request: Request, current_user: str = Depends(require_auth)):
    if KRA_FILE.exists():
        headers = {"Content-Disposition": f'inline; filename="{KRA_FILE.name}"'}
        return FileResponse(KRA_FILE, media_type="application/pdf", headers=headers)
    return {"error": "KRA PDF not found"}

@app.get("/")
def root(request: Request):
    if get_current_user(request):
        return RedirectResponse(url='/clinic-experience-dashboard.html', status_code=302)
    return RedirectResponse(url='/login', status_code=302)

@app.get("/clinic-experience-dashboard.html", response_class=HTMLResponse)
def get_dashboard(request: Request):
    if not get_current_user(request):
        return RedirectResponse(url='/login', status_code=302)
    try:
        return HTML_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "Dashboard HTML file not found."

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
