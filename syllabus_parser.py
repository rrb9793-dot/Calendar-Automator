import os
import time
import pandas as pd
import re
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# --- CONFIGURATION ---
# Reads directly from Railway Environment Variables
API_KEY = os.environ.get("GEMINI_API_KEY")

# --- DATA MODELS ---
class MeetingSchedule(BaseModel):
    days: List[str] = Field(description="List of days (e.g., ['Monday', 'Wednesday']).")
    start_time: str = Field(description="The START time of the class ONLY (e.g. '11:00 AM').")

class AssignmentItem(BaseModel):
    date: str = Field(description="The due date in 'YYYY-MM-DD' format.")
    time: Optional[str] = Field(description="Specific deadline if explicitly written (e.g. '11:59 PM'). Otherwise null.")
    assignment_name: str = Field(description="Concise name.")
    category: str = Field(description="Category: 'Reading', 'Writing', 'Exam', 'Project', 'Presentation', 'Other'.")
    description: str = Field(description="Details. If exam, include duration here. If readings, bullet points.")

class CourseMetadata(BaseModel):
    course_name: str = Field(description="Name of the course.")
    semester_year: str = Field(description="Semester and Year (e.g., 'Fall 2025').")
    class_meetings: List[MeetingSchedule] = Field(description="The weekly schedule.")

class SyllabusResponse(BaseModel):
    metadata: CourseMetadata
    assignments: List[AssignmentItem]

# --- 10/10 HELPER: STRICT STANDARDIZATION ---
def standardize_time(time_str):
    """
    Parses messy times (2pm, 2:00 pm, 14:00) and converts them to
    a strict 'HH:MM AM/PM' format (e.g., '02:00 PM') for perfect grouping.
    """
    if not time_str: return None
    
    # Clean up input (remove ranges like -3:15)
    clean = re.split(r'\s*[-–]\s*|\s+to\s+', str(time_str))[0].strip()
    
    # Try multiple formats
    for fmt in ["%I:%M %p", "%I %p", "%H:%M", "%I:%M%p"]:
        try:
            return datetime.strptime(clean, fmt).strftime("%I:%M %p")
        except ValueError:
            continue
            
    # Fallback heuristics for raw numbers
    if clean.isdigit():
        val = int(clean)
        if 8 <= val <= 11: return f"{val:02d}:00 AM"
        if 1 <= val <= 6:  return f"{val:02d}:00 PM"
        if val == 12:      return "12:00 PM"
    
    return clean # Return original if we really can't parse it

def resolve_time(row, schedule_map):
    """
    Logic: Explicit > Class Time > 11:59 PM.
    """
    existing_time = row['Time']
    
    # 1. Explicit Deadline
    if existing_time and any(char.isdigit() for char in str(existing_time)):
        return standardize_time(existing_time)

    # 2. Check Class Day
    try:
        # Use pandas to handle date parsing robustly
        date_obj = pd.to_datetime(row['Date'])
        day_name = date_obj.strftime('%A') 
    except:
        return "11:59 PM"

    if day_name in schedule_map:
        return schedule_map[day_name]
    
    # 3. Fallback
    return "11:59 PM"

# --- PARSING ENGINE ---
def parse_syllabus_to_data(pdf_path: str):
    if not API_KEY:
        print("❌ Error: GEMINI_API_KEY not found in environment variables.")
        return None

    client = genai.Client(api_key=API_KEY)
    print(f"Reading {pdf_path}...")

    try:
        file_upload = client.files.upload(file=pdf_path)
        while file_upload.state.name == "PROCESSING":
            time.sleep(1)
            file_upload = client.files.get(name=file_upload.name)
        
        if file_upload.state.name != "ACTIVE":
            return None

        prompt = """
        Analyze this syllabus for Calendar Import.
        
        PHASE 1: METADATA
        - Extract Course Name.
        - **Class Schedule:** Extract Days and **START TIME ONLY**.
        
        PHASE 2: ASSIGNMENTS
        - Extract deliverables and readings.
        - **Dates:** YYYY-MM-DD.
        - **Times:** Leave time NULL unless a specific deadline is written.
        - **Exams:** If "In Class", leave time NULL.
        """

        response = client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=[file_upload, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SyllabusResponse
            )
        )
        
        data: SyllabusResponse = response.parsed
        
        # Build Schedule Map with STANDARDIZED times
        schedule_map = {}
        for meeting in data.metadata.class_meetings:
            std_time = standardize_time(meeting.start_time)
            for day in meeting.days:
                for full_day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
                    if full_day.lower() in day.lower():
                        schedule_map[full_day] = std_time

        rows = []
        for item in data.assignments:
            rows.append({
                "Course": data.metadata.course_name,
                "Date": item.date,
                "Time": item.time, 
                "Category": item.category,
                "Assignment": item.assignment_name,
                "Description": item.description
            })
            
        df = pd.DataFrame(rows)
        
        if not df.empty:
            # Force Dates to be standard strings to prevent duplicates
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
            df = df.dropna(subset=['Date']) # Drop rows where date failed parse
            
            # Apply Time Logic
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
        # Remove duplicates while preserving order
        unique_items = []
        seen = set()
        for x in items:
            if x not in seen:
                unique_items.append(x)
                seen.add(x)
        
        if len(unique_items) == 1: return unique_items[0]
        
        clean_items = []
        for x in unique_items:
            x = x.strip()
            if x.startswith("•") or x.startswith("-"):
                clean_items.append(x)
            else:
                clean_items.append(f"• {x}")
        return "\n".join(clean_items)

    def merge_names(series):
        # Unique names only
        return " / ".join(sorted(set(series)))

    df_consolidated = df.groupby(group_cols).agg({
        'Assignment': merge_names,
        'Description': merge_text
    }).reset_index()
    
    return df_consolidated.sort_values(by=['Date', 'Time'])
