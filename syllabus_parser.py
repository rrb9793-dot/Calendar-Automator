import os
import time
import pandas as pd
import re
import json
from datetime import datetime
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

# --- CONFIGURATION ---
DEFAULT_API_KEY = os.environ.get("GEMINI_API_KEY")

# --- HELPER: STRICT STANDARDIZATION (24-HOUR FORMAT) ---
def standardize_time(time_str):
    """Converts various time formats to strictly HH:MM (24-hour)."""
    if not time_str: return None
    
    clean = re.split(r'\s*[-–]\s*|\s+to\s+', str(time_str))[0].strip()
    
    formats = [
        "%I:%M %p", "%I %p", "%H:%M", "%I:%M%p", "%I%p"
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(clean, fmt).strftime("%H:%M")
        except ValueError:
            continue
            
    if clean.isdigit():
        val = int(clean)
        if 7 <= val <= 11: return f"{val:02d}:00"
        if 1 <= val <= 6:  return f"{val+12:02d}:00"
        if val == 12:      return "12:00"
        
    return None 

def resolve_time(row, schedule_map):
    """Determines the best time for an assignment."""
    existing_time = row.get('Time')
    
    if existing_time and any(char.isdigit() for char in str(existing_time)):
        std = standardize_time(existing_time)
        if std: return std

    try:
        if pd.notna(row['Date']):
            date_obj = pd.to_datetime(row['Date'])
            day_name = date_obj.strftime('%A') 
            if day_name in schedule_map:
                return schedule_map[day_name]
    except:
        pass

    return "23:59"

# --- PARSING ENGINE ---
# [FIX] Added manual_course_name argument here
def parse_syllabus_to_data(pdf_path: str, api_key: str = None, manual_course_name: str = None):
    active_key = api_key if api_key else DEFAULT_API_KEY
    if not active_key:
        print("❌ Error: No GEMINI_API_KEY found.")
        return None

    genai.configure(api_key=active_key)
    print(f"📄 Parsing: {os.path.basename(pdf_path)}")

    try:
        sample_file = genai.upload_file(path=pdf_path, display_name="Syllabus")
        
        while sample_file.state.name == "PROCESSING":
            time.sleep(1)
            sample_file = genai.get_file(sample_file.name)
            
        if sample_file.state.name != "ACTIVE":
            print(f"❌ File processing failed: {sample_file.state.name}")
            return None

        prompt = """
        Extract all assignments, exams, and due dates from this syllabus into JSON.
        
        Output format:
        {
            "metadata": {
                "course_name": "string",
                "class_meetings": [ {"days": ["Monday"], "start_time": "14:00"} ]
            },
            "assignments": [
                {
                    "date": "YYYY-MM-DD",
                    "time": "HH:MM", 
                    "assignment_name": "string",
                    "category": "Exam/Reading/P-Set/Essay/Project",
                    "description": "string"
                }
            ]
        }
        
        Rules:
        1. Dates MUST be YYYY-MM-DD.
        2. Times MUST be 24-hour format (HH:MM) if available. If not, null.
        """

        model = genai.GenerativeModel('gemini-2.0-flash')

        max_retries = 3
        response = None

        for attempt in range(max_retries):
            try:
                response = model.generate_content(
                    [sample_file, prompt],
                    generation_config={"response_mime_type": "application/json"}
                )
                break 
            except ResourceExhausted:
                print(f"⚠️ Quota hit. Retrying in 5s... ({attempt+1}/{max_retries})")
                time.sleep(5)
            except Exception as e:
                print(f"❌ GenAI Error: {e}")
                return None
        
        if not response: return None

        try:
            data = json.loads(response.text)
        except:
            print("❌ Failed to parse JSON response from Gemini")
            return None

        # --- FIX: Handle List vs Dict Response ---
        # If Gemini returned a plain list [ ... ], wrap it in a dict
        if isinstance(data, list):
            data = {"assignments": data, "metadata": {}}
        
        # --- Process Metadata ---
        meta = data.get("metadata", {})
        
        # [FIX] Override AI extracted name if manual name is provided
        ai_extracted_name = meta.get("course_name", "Unknown Course")
        course_name = manual_course_name if manual_course_name else ai_extracted_name
        
        schedule_map = {}
        for meeting in meta.get("class_meetings", []):
            raw_time = meeting.get("start_time", "")
            std_time = standardize_time(raw_time)
            days = meeting.get("days", [])
            if isinstance(days, str): days = [days]
            
            if std_time:
                for day in days:
                    for full_day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
                        if full_day.lower() in str(day).lower():
                            schedule_map[full_day] = std_time

        # --- Process Assignments ---
        rows = []
        # Now .get() is safe because we ensured data is a dict
        for item in data.get("assignments", []):
            rows.append({
                "Course": course_name, # Uses the manual name if provided
                "Date": item.get("date"),
                "Time": item.get("time"), 
                "Category": item.get("category", "Other"),
                "Assignment": item.get("assignment_name", "Untitled"),
                "Description": item.get("description", "")
            })
            
        df = pd.DataFrame(rows)
        if df.empty: return df

        df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
        df = df.dropna(subset=['Date'])
        
        df['Time'] = df.apply(lambda row: resolve_time(row, schedule_map), axis=1)

        return df

    except Exception as e:
        print(f"❌ Critical Parsing Error: {e}")
        return None

# --- CONSOLIDATION ---
def consolidate_assignments(df):
    if df.empty: return df

    group_cols = ['Course', 'Date', 'Time', 'Category']
    
    def merge_unique(series):
        return " / ".join(sorted(set(str(s) for s in series if s)))

    df_consolidated = df.groupby(group_cols).agg({
        'Assignment': merge_unique,
        'Description': merge_unique
    }).reset_index()
    
    return df_consolidated.sort_values(by=['Date', 'Time'])
