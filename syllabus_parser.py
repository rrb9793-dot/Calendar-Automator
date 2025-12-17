import os
import time
import pandas as pd
import re
import json
from datetime import datetime
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

DEFAULT_API_KEY = os.environ.get("GEMINI_API_KEY")

def standardize_time(time_str):
    if not time_str: return None
    clean = re.split(r'\s*[-–]\s*|\s+to\s+', str(time_str))[0].strip()
    formats = ["%I:%M %p", "%I %p", "%H:%M", "%I:%M%p", "%I%p"]
    for fmt in formats:
        try: return datetime.strptime(clean, fmt).strftime("%H:%M")
        except: continue
    if clean.isdigit():
        val = int(clean)
        if 7 <= val <= 11: return f"{val:02d}:00"
        if 1 <= val <= 6:  return f"{val+12:02d}:00"
        if val == 12:      return "12:00"
    return None 

def resolve_time(row, schedule_map):
    if row.get('Time') and any(c.isdigit() for c in str(row['Time'])):
        t = standardize_time(row['Time'])
        if t: return t
    try:
        if pd.notna(row['Date']):
            day = pd.to_datetime(row['Date']).strftime('%A')
            if day in schedule_map: return schedule_map[day]
    except: pass
    return "23:59"

def parse_syllabus_to_data(pdf_path: str, api_key: str = None):
    print(f"--- 🚀 STARTED PARSING: {os.path.basename(pdf_path)} ---", flush=True)
    genai.configure(api_key=api_key or DEFAULT_API_KEY)

    try:
        f = genai.upload_file(path=pdf_path, display_name="Syllabus")
        while f.state.name == "PROCESSING": time.sleep(1); f = genai.get_file(f.name)
        
        prompt = """Extract metadata and assignments from this syllabus into JSON.
        Output format:
        {
            "metadata": {
                "course_name": "string (Official Name)",
                "field_of_study": "string (Choose best fit from list below)",
                "class_meetings": [{"days": ["Monday"], "start_time": "14:00"}]
            },
            "assignments": [
                {
                    "date": "YYYY-MM-DD",
                    "time": "HH:MM", 
                    "assignment_name": "string",
                    "category": "STRICT_CATEGORY" 
                }
            ]
        }
        Rules:
        1. "field_of_study" MUST be one of: "Business", "Tech & Data Science", "Engineering", "Math", "Natural Sciences", "Social Sciences", "Arts & Humanities", "Health & Education".
        2. "category" MUST be one of: "Exam", "Problem Set", "Coding Assignment", "Research Paper", "Creative Writing/Essay", "Presentation", "Modeling", "Discussion Post", "Readings", "Case Study".
        3. Dates YYYY-MM-DD. Times 24h.
        4. IGNORE holidays, breaks, or "No Class" entries.
        """
        
        model = genai.GenerativeModel('gemini-2.0-flash')
        for _ in range(3):
            try:
                resp = model.generate_content([f, prompt], generation_config={"response_mime_type": "application/json"})
                break
            except ResourceExhausted: time.sleep(5)
            except: return None
        
        if not resp: return None
        data = json.loads(resp.text)
        if isinstance(data, list): data = {"assignments": data, "metadata": {}}
        
        meta = data.get("metadata", {})
        course = meta.get("course_name", "") 
        field = meta.get("field_of_study", "Business")
        
        print(f"--- METADATA: Course='{course}', Field='{field}' ---", flush=True)

        sched_map = {}
        for m in meta.get("class_meetings", []):
            t = standardize_time(m.get("start_time", ""))
            days = m.get("days", [])
            if t:
                for d in (days if isinstance(days, list) else [days]):
                    for fd in ['Monday','Tuesday','Wednesday','Thursday','Friday']:
                        if fd.lower() in str(d).lower(): sched_map[fd] = t

        rows = []
        for i in data.get("assignments", []):
            # 1. IMMEDIATE FILTER: Skip blank names
            name = i.get("assignment_name", "").strip()
            if not name or name.lower() in ["untitled", "no class", "no class."]:
                continue
                
            rows.append({
                "Course": course, 
                "Field": field,
                "Date": i.get("date"), 
                "Time": i.get("time"),
                "Category": i.get("category", "p_set"), 
                "Assignment": name
            })
            
        df = pd.DataFrame(rows)
        if df.empty: return df
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['Date'])
        
        # --- 2. SEQUENTIAL RENAMING (The Fix) ---
        # Sort by date so "Assignment 1" is actually the first one
        df = df.sort_values(by='Date')
        
        # Identify duplicates
        # We group by the 'Assignment' name. If a name appears >1 time, we number them.
        name_counts = df['Assignment'].value_counts()
        duplicates = name_counts[name_counts > 1].index
        
        # Create a tracker for names we've seen
        seen_counts = {}
        
        def rename_duplicates(row):
            name = row['Assignment']
            if name in duplicates:
                if name not in seen_counts:
                    seen_counts[name] = 1
                else:
                    seen_counts[name] += 1
                return f"{name} {seen_counts[name]}"
            return name

        df['Assignment'] = df.apply(rename_duplicates, axis=1)

        # Standardize Date String
        df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
        df['Time'] = df.apply(lambda r: resolve_time(r, sched_map), axis=1)
        
        # Append Course Name (Only if it exists)
        def format_final_name(row):
            name = row['Assignment']
            c = row['Course']
            if c and c.strip(): return f"{name} ({c})"
            return name
            
        df['Assignment'] = df.apply(format_final_name, axis=1)
        
        return df

    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        return None

def consolidate_assignments(df):
    if df.empty: return df
    # Since we made names unique (seq numbering), we group by the FULL name now
    return df.groupby(['Course', 'Field', 'Date', 'Time', 'Category']).agg({
        'Assignment': lambda x: " / ".join(sorted(set(str(s) for s in x if s)))
    }).reset_index().sort_values(by=['Date', 'Time'])
