import os
import json
import time
import math
import re
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time as dt_time
from typing import List, Optional
from zoneinfo import ZoneInfo
from dateutil import parser as date_parser

from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from whitenoise import WhiteNoise

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
CORS(app)

# Serve static files in production
app.wsgi_app = WhiteNoise(app.wsgi_app, root=STATIC_DIR, prefix='static/')

# Folders
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Files & Secrets
CSV_PATH = os.path.join(BASE_DIR, 'survey.csv')
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
LOCAL_TZ = ZoneInfo("America/New_York") 
CHUNK_SIZE = 60 # Minutes per study session

# --- LIBRARIES ---
try:
    from sklearn.linear_model import ElasticNet
except ImportError:
    sys.exit("CRITICAL: scikit-learn missing. Check requirements.txt")

try:
    from google import genai
    from google.genai import types
    from pydantic import BaseModel, Field
except ImportError:
    genai = None

try:
    from icalendar import Calendar as ICalLoader
    from ics import Calendar as IcsCalendar, Event as IcsEvent
    import recurring_ical_events
except ImportError:
    sys.exit("CRITICAL: Calendar libs missing. Check requirements.txt")

# ==========================================
# 1. MODEL TRAINING (Refined for Frontend Match)
# ==========================================
model = None
model_columns = []

def initialize_model():
    """
    Trains the model ONLY on fields provided by the Frontend:
    1. Year
    2. Major
    3. Assignment Type
    """
    global model, model_columns
    if not os.path.exists(CSV_PATH):
        print("⚠️ Survey CSV not found. Model will use fallback.")
        return

    try:
        df = pd.read_csv(CSV_PATH)
        
        # Rename columns to match internal logic
        df = df.rename(columns={
            'What year are you? ': 'year',
            'What is your major/concentration?': 'major', 
            'What type of assignment was it?': 'assignment_type', 
            'Approximately how long did it take (in hours)': 'time_spent_hours'
        })

        # KEEP ONLY RELEVANT COLUMNS
        # We drop 'external_resources', 'work_location', etc. because the frontend doesn't ask for them.
        keep_cols = ['year', 'major', 'assignment_type', 'time_spent_hours']
        df = df[[c for c in keep_cols if c in df.columns]]

        # Drop rows with missing target
        df = df.dropna(subset=['time_spent_hours'])

        # One-Hot Encode Categorical Variables
        # This creates columns like 'year_2026', 'major_Computer Science', 'assignment_type_Essay'
        df = pd.get_dummies(df, columns=['year', 'major', 'assignment_type'], dummy_na=False)

        # Separate Features (X) and Target (y)
        # Ensure only numeric columns remain
        df = df.select_dtypes(include=[np.number])
        
        if 'time_spent_hours' in df.columns:
            X = df.drop('time_spent_hours', axis=1)
            y = df['time_spent_hours']
            
            # Train ElasticNet
            clf = ElasticNet(alpha=0.1, l1_ratio=0.5, max_iter=5000)
            clf.fit(X, y)
            
            model = clf
            model_columns = list(X.columns)
            print(f"✅ Model Trained on features: {model_columns}")
        else:
            print("❌ Target column 'time_spent_hours' missing after processing.")

    except Exception as e:
        print(f"❌ Training Failed: {e}")

initialize_model()

# ==========================================
# 2. PDF PARSER & LOGIC
# ==========================================

def parse_syllabus(file_path):
    if not genai or not GEMINI_API_KEY: 
        print("⚠️ Gemini AI not configured.")
        return None
    try:
        class AssignmentItem(BaseModel):
            date: str = Field(description="Due Date in YYYY-MM-DD format")
            assignment_name: str = Field(description="Name of the task")
            category: str = Field(description="Type: 'Problem Set', 'Essay', 'Reading', 'Exam', 'Project'")

        class SyllabusResponse(BaseModel):
            course_name: str = Field(description="Name of the course")
            assignments: List[AssignmentItem]

        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # Upload
        file_upload = client.files.upload(file=file_path)
        print(f"Processing PDF: {file_upload.name}")
        
        # Wait for processing
        while file_upload.state.name == "PROCESSING":
            time.sleep(1)
            file_upload = client.files.get(name=file_upload.name)
        
        if file_upload.state.name != "ACTIVE": 
            return None

        prompt = "Extract all assignments with their due dates (YYYY-MM-DD) and types."
        response = client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=[file_upload, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", 
                response_schema=SyllabusResponse
            )
        )
        
        # Parse Response
        data = response.parsed
        if not data: return None

        rows = []
        for item in data.assignments:
            # Validate Date Format
            try:
                dt = date_parser.parse(item.date)
                date_str = dt.strftime('%Y-%m-%d')
            except:
                continue # Skip invalid dates

            rows.append({
                "name": f"{data.course_name}: {item.assignment_name}", 
                "date": date_str, 
                "type": item.category
            })
        
        return rows
    except Exception as e:
        print(f"PDF Parsing error: {e}")
        return []

# ==========================================
# 3. SCHEDULER LOGIC
# ==========================================

def get_free_time_windows(start_dt, end_dt, preferences, busy_blocks):
    """Generates available study slots."""
    free_blocks = []
    current_day = start_dt.date()
    end_date_date = end_dt.date()
    
    # Sort busy blocks
    busy_blocks.sort(key=lambda x: x[0])

    while current_day <= end_date_date:
        is_weekend = current_day.weekday() >= 5
        
        # Work Windows
        if is_weekend:
            s_str, e_str = preferences.get('weekendStart', '10:00'), preferences.get('weekendEnd', '20:00')
        else:
            s_str, e_str = preferences.get('weekdayStart', '09:00'), preferences.get('weekdayEnd', '22:00')

        try:
            sh, sm = map(int, s_str.split(':'))
            eh, em = map(int, e_str.split(':'))
        except:
            sh, sm, eh, em = 9, 0, 21, 0

        day_start = datetime.combine(current_day, dt_time(sh, sm)).replace(tzinfo=LOCAL_TZ)
        day_end = datetime.combine(current_day, dt_time(eh, em)).replace(tzinfo=LOCAL_TZ)

        # Subtract Busy Blocks
        current_pointer = day_start
        day_busy = [b for b in busy_blocks if b[1] > day_start and b[0] < day_end]

        for b_start, b_end in day_busy:
            b_start = max(b_start, day_start)
            b_end = min(b_end, day_end)

            if b_start > current_pointer:
                dur = (b_start - current_pointer).total_seconds() / 60
                if dur >= 30: 
                    free_blocks.append({'start': current_pointer, 'end': b_start, 'duration': dur})
            current_pointer = max(current_pointer, b_end)

        if current_pointer < day_end:
            dur = (day_end - current_pointer).total_seconds() / 60
            if dur >= 30:
                free_blocks.append({'start': current_pointer, 'end': day_end, 'duration': dur})

        current_day += timedelta(days=1)
    
    return pd.DataFrame(free_blocks)

def create_schedule_file(courses, preferences, user_ics_path):
    now = datetime.now(LOCAL_TZ)
    end_horizon = now + timedelta(days=90)

    # 1. Parse Busy Times
    busy = []
    if user_ics_path and os.path.exists(user_ics_path):
        try:
            with open(user_ics_path, 'rb') as f:
                cal = ICalLoader.from_ical(f.read())
            events = recurring_ical_events.of(cal).between(now, end_horizon)
            for ev in events:
                dtstart = ev.get('DTSTART').dt
                dtend = ev.get('DTEND').dt
                
                # Normalize types
                if not isinstance(dtstart, datetime): dtstart = datetime.combine(dtstart, dt_time.min).replace(tzinfo=LOCAL_TZ)
                else: dtstart = dtstart.astimezone(LOCAL_TZ)

                if not isinstance(dtend, datetime): dtend = datetime.combine(dtend, dt_time.max).replace(tzinfo=LOCAL_TZ)
                else: dtend = dtend.astimezone(LOCAL_TZ)
                
                busy.append((dtstart, dtend))
        except Exception as e:
            print(f"ICS Error: {e}")

    # 2. Get Free Blocks
    free_df = get_free_time_windows(now, end_horizon, preferences, busy)
    if free_df.empty: return None

    # 3. Create Sessions
    sessions = []
    for c in courses:
        try:
            due_dt = datetime.strptime(c['date'], '%Y-%m-%d').replace(tzinfo=LOCAL_TZ).replace(hour=23, minute=59)
            hours = float(c.get('predicted_hours', 2.0))
            
            # Split into chunks
            total_mins = int(hours * 60)
            num_chunks = math.ceil(total_mins / CHUNK_SIZE)
            
            for i in range(num_chunks):
                dur = min(CHUNK_SIZE, total_mins - (i * CHUNK_SIZE))
                sessions.append({
                    'name': c['name'],
                    'due': due_dt,
                    'duration': dur
                })
        except: continue

    sessions.sort(key=lambda x: x['due'])

    # 4. Schedule
    final_events = []
    for sess in sessions:
        valid = free_df[
            (free_df['start'] >= now) & 
            (free_df['end'] <= sess['due']) & 
            (free_df['duration'] >= sess['duration'])
        ]
        
        if not valid.empty:
            idx = valid.index[0]
            block = free_df.loc[idx]
            
            start_t = block['start']
            end_t = start_t + timedelta(minutes=sess['duration'])
            
            final_events.append({'name': f"Study: {sess['name']}", 'begin': start_t, 'end': end_t})
            
            # Update block
            new_start = end_t
            new_dur = (block['end'] - new_start).total_seconds() / 60
            if new_dur >= 30:
                free_df.at[idx, 'start'] = new_start
                free_df.at[idx, 'duration'] = new_dur
            else:
                free_df.drop(idx, inplace=True)

    # 5. Export ICS
    cal = IcsCalendar()
    for ev in final_events:
        e = IcsEvent()
        e.name = ev['name']
        e.begin = ev['begin']
        e.end = ev['end']
        cal.events.add(e)
    
    filename = f"schedule_{int(time.time())}.ics"
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    with open(path, 'w') as f:
        f.writelines(cal.serialize_iter())
        
    return filename

# ==========================================
# 4. API ROUTES
# ==========================================

@app.route('/', methods=['GET'])
def home():
    return render_template('mains.html')

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename), as_attachment=True)

@app.route('/api/generate-schedule', methods=['POST'])
def generate_schedule():
    try:
        data_str = request.form.get('data')
        if not data_str: return jsonify({'error': 'No data'}), 400
        
        req_data = json.loads(data_str)
        survey = req_data.get('survey', {})
        courses = req_data.get('courses', [])
        preferences = req_data.get('preferences', {})

        # A. HANDLE PDFS (Add to courses list)
        uploaded_pdfs = request.files.getlist('pdfs')
        for pdf in uploaded_pdfs:
            if pdf.filename == '': continue
            filename = secure_filename(pdf.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            pdf.save(path)
            
            # Parse and merge into courses
            parsed_courses = parse_syllabus(path)
            if parsed_courses:
                courses.extend(parsed_courses)

        # B. PREDICT TIMES (Synced with Frontend Inputs)
        for c in courses:
            if model and model_columns:
                # Create a zero-filled vector for all known columns
                input_vector = {col: 0 for col in model_columns}
                
                # Activate User's Year (e.g., 'year_2026')
                y_col = f"year_{survey.get('year')}"
                if y_col in input_vector: input_vector[y_col] = 1
                
                # Activate User's Major (e.g., 'major_Computer Science')
                m_col = f"major_{survey.get('major')}"
                if m_col in input_vector: input_vector[m_col] = 1

                # Activate Assignment Type (e.g., 'assignment_type_Essay')
                # Note: We normalize input to match potential CSV columns if needed, 
                # but simplistic matching usually works if strings align.
                t_col = f"assignment_type_{c.get('type')}"
                if t_col in input_vector: input_vector[t_col] = 1
                
                # Predict
                pred = model.predict(pd.DataFrame([input_vector]))[0]
                c['predicted_hours'] = round(max(0.5, pred), 1)
            else:
                c['predicted_hours'] = 2.0 # Default if model fails

        # C. GENERATE SCHEDULE
        # Handle ICS file for busy times
        user_ics_path = None
        ics_file = request.files.get('ics')
        if ics_file and ics_file.filename != '':
            path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(ics_file.filename))
            ics_file.save(path)
            user_ics_path = path

        result_file = create_schedule_file(courses, preferences, user_ics_path)

        if not result_file:
            return jsonify({'error': 'Schedule generation failed. No free time found?'}), 400

        return jsonify({
            'message': 'Success',
            'courses': courses,
            'ics_url': f"/download/{result_file}"
        })

    except Exception as e:
        print(f"API Error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
