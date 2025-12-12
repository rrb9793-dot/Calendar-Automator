import os
import time
import pandas as pd
import re
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold



# --- CONFIGURATION ---
API_KEY = os.environ.get("GEMINI_API_KEY")


# --- HELPER: STRICT STANDARDIZATION ---
def standardize_time(time_str):
    if not time_str: return None
    clean = re.split(r'\s*[-–]\s*|\s+to\s+', str(time_str))[0].strip()
    for fmt in ["%I:%M %p", "%I %p", "%H:%M", "%I:%M%p"]:
        try:
            return datetime.strptime(clean, fmt).strftime("%I:%M %p")
        except ValueError:
            continue
    if clean.isdigit():
        val = int(clean)
        if 8 <= val <= 11: return f"{val:02d}:00 AM"
        if 1 <= val <= 6:  return f"{val:02d}:00 PM"
        if val == 12:      return "12:00 PM"
    return clean

def resolve_time(row, schedule_map):
    existing_time = row['Time']
    if existing_time and any(char.isdigit() for char in str(existing_time)):
        return standardize_time(existing_time)
    try:
        date_obj = pd.to_datetime(row['Date'])
        day_name = date_obj.strftime('%A') 
    except:
        return "11:59 PM"
    if day_name in schedule_map:
        return schedule_map[day_name]
    return "11:59 PM"

# --- PARSING ENGINE ---
def parse_syllabus_to_data(pdf_path: str, api_key: str = None):
    # Resolve Key
    active_key = api_key if api_key else API_KEY
    if not active_key:
        print("❌ Error: No API Key found. Set GEMINI_API_KEY in Railway Variables.")
        return None

    # Configure the Stable SDK
    genai.configure(api_key=active_key)
    print(f"Reading {pdf_path}...")

    try:
        # Upload File
        sample_file = genai.upload_file(path=pdf_path, display_name="Syllabus")
        
        # Wait for processing
        # Increased sleep to 2s to reduce API call frequency
        while sample_file.state.name == "PROCESSING":
            time.sleep(2)
            sample_file = genai.get_file(sample_file.name)
            
        if sample_file.state.name != "ACTIVE":
            print(f"❌ File processing failed: {sample_file.state.name}")
            return None

        prompt = """
        Extract syllabus data into JSON format.
        
        Structure:
        {
            "metadata": {
                "course_name": "string",
                "class_meetings": [
                    {"days": ["Monday"], "start_time": "11:00 AM"}
                ]
            },
            "assignments": [
                {
                    "date": "YYYY-MM-DD",
                    "time": "11:59 PM", 
                    "assignment_name": "string",
                    "category": "Exam/Reading/Project/Other",
                    "description": "string"
                }
            ]
        }
        
        Rules:
        - Dates format must be YYYY-MM-DD.
        - If no time is listed, use null.
        - Capture all exams and due dates.
        """

        # --- CHANGED: Using 1.5 Flash for better rate limit stability ---
        model = genai.GenerativeModel('gemini-2.0-flash')

        # --- ADDED: Retry Logic for 429 Errors ---
        max_retries = 3
        response = None

        for attempt in range(max_retries):
            try:
                response = model.generate_content(
                    [sample_file, prompt],
                    generation_config={"response_mime_type": "application/json"}
                )
                break # Success, exit loop
            except Exception as e:
                # Check for "429" or "Resource Exhausted"
                if "429" in str(e) or "resource exhausted" in str(e).lower():
                    if attempt < max_retries - 1:
                        print(f"⚠️ Rate limit hit (429). Retrying in {2} seconds...")
                        time.sleep(5)
                        continue
                print(f"❌ Error generating content: {e}")
                return None
        
        if not response:
            return None

        import json
        try:
            data = json.loads(response.text)
        except Exception as e:
            print(f"❌ JSON Parse Error: {e}")
            return None

        # --- Process Metadata ---
        meta = data.get("metadata", {})
        course_name = meta.get("course_name", "Unknown Course")
        meetings = meta.get("class_meetings", [])
        
        schedule_map = {}
        for meeting in meetings:
            raw_time = meeting.get("start_time", "")
            std_time = standardize_time(raw_time)
            
            days = meeting.get("days", [])
            if isinstance(days, str): days = [days] 
            
            for day in days:
                for full_day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
                    if full_day.lower() in str(day).lower():
                        schedule_map[full_day] = std_time

        # --- Process Assignments ---
        rows = []
        for item in data.get("assignments", []):
            rows.append({
                "Course": course_name,
                "Date": item.get("date"),
                "Time": item.get("time"), 
                "Category": item.get("category", "Other"),
                "Assignment": item.get("assignment_name", "Untitled"),
                "Description": item.get("description", "")
            })
            
        df = pd.DataFrame(rows)
        if not df.empty:
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
            df = df.dropna(subset=['Date'])
            df['Time'] = df.apply(lambda row: resolve_time(row, schedule_map), axis=1)

        return df

    except Exception as e:
        print(f"❌ Error analyzing {pdf_path}: {e}")
        return None

# --- CONSOLIDATION ---
def consolidate_assignments(df):
    if df.empty: return df

    group_cols = ['Course', 'Date', 'Time', 'Category']
    
    def merge_text(series):
        items = [s for s in series if s]
        if not items: return ""
        unique_items = []
        seen = set()
        for x in items:
            if x not in seen:
                unique_items.append(x)
                seen.add(x)
        if len(unique_items) == 1: return unique_items[0]
        return " / ".join(unique_items)

    def merge_names(series):
        return " / ".join(sorted(set(series)))

    df_consolidated = df.groupby(group_cols).agg({
        'Assignment': merge_names,
        'Description': merge_text
    }).reset_index()
    
    return df_consolidated.sort_values(by=['Date', 'Time'])
