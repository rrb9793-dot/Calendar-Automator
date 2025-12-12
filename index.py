import os
import json
import time
import pandas as pd
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from whitenoise import WhiteNoise
import google.generativeai as genai

# --- CUSTOM MODULES ---
import predictive_model 
import syllabus_parser 
import calendar_maker

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
CORS(app)
app.wsgi_app = WhiteNoise(app.wsgi_app, root=STATIC_DIR, prefix='static/')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

# Constants
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# ==========================================
# ROUTES
# ==========================================

@app.route('/', methods=['GET'])
def home():
    print("--- CHECKING AVAILABLE GEMINI MODELS ---")
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"Found model: {m.name}")
    except Exception as e:
        print(f"Error listing models: {e}")
    print("----------------------------------------")
    # --- DEBUGGING END ---
    return render_template('mains.html')

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename), as_attachment=True)

@app.route('/api/generate-schedule', methods=['POST'])
def generate_schedule():
    try:
        # ---------------------------------------------------------
        # 1. GATHER INPUTS
        # ---------------------------------------------------------
        data_str = request.form.get('data')
        req_data = json.loads(data_str) if data_str else {}
        
        frontend_prefs = req_data.get('preferences', {})
        survey_data = req_data.get('survey', {})
        manual_courses = req_data.get('courses', [])

        # B. User ICS Files
        ics_files_bytes = []
        if 'ics' in request.files:
            files = request.files.getlist('ics')
            for f in files:
                if f.filename != '':
                    ics_files_bytes.append(f.read())
                    f.seek(0)

        # ---------------------------------------------------------
        # 2. AGGREGATE ASSIGNMENTS (MANUAL + PDF)
        # ---------------------------------------------------------
        all_assignments = []
        
        # A. Manual Entries (From Frontend)
        for course in manual_courses:
            all_assignments.append({
                "source_type": "manual",
                "Assignment": course.get('assignment_name'),
                "Date": course.get('due_date'),
                "Time": "23:59", 
                "Course": course.get('field_of_study', 'General'),
                "raw_details": course # Frontend inputs
            })

        # B. PDF Entries (From Parsing)
        uploaded_pdfs = request.files.getlist('pdfs')
        if uploaded_pdfs:
            print(f"Processing {len(uploaded_pdfs)} PDF(s)...")
            pdf_dfs = []
            for pdf in uploaded_pdfs:
                if pdf.filename == '': continue
                filename = secure_filename(pdf.filename)
                path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                pdf.save(path)
                
                df = syllabus_parser.parse_syllabus_to_data(path, GEMINI_API_KEY)
                if df is not None and not df.empty:
                    pdf_dfs.append(df)
            
            if pdf_dfs:
                master_df = pd.concat(pdf_dfs, ignore_index=True)
                final_df = syllabus_parser.consolidate_assignments(master_df)
                parsed_records = final_df.to_dict(orient='records')
                
                for record in parsed_records:
                    record["source_type"] = "pdf"
                    all_assignments.append(record)

        # ---------------------------------------------------------
        # 3. PREDICTION & FORMATTING
        # ---------------------------------------------------------
        formatted_assignments = []
        
        for i, item in enumerate(all_assignments):
            # A. Prepare details for prediction
            if item["source_type"] == "manual":
                # Manual entries have full user details
                assignment_details = item["raw_details"]
            else:
                # PDF entries need defaults for fields the PDF lacks
                assignment_details = {
                    'work_sessions': 1,
                    'assignment_type': item.get('Category', 'p_set'), 
                    'field_of_study': survey_data.get('major', 'Business'),
                    'external_resources': 'Google/internet',
                    'work_location': 'School/library',
                    'work_in_group': 'No',
                    'submitted_in_person': 'No'
                }

            # B. Run Prediction (Using strict mapping)
            predicted_hours = predictive_model.predict_assignment_time(survey_data, assignment_details)
            
            # C. Format Date/Time
            date_str = item.get("Date")
            time_str = item.get("Time")
            if not time_str: time_str = "11:59 PM"
            full_due_string = f"{date_str} {time_str}"
            
            # D. Final Structure for Calendar Maker
            formatted_assignments.append({
                "id": f"assign_{i}",
                "name": item.get("Assignment", "Untitled Task"),
                "class_name": item.get("Course", "General"),
                "due_date": full_due_string, 
                "time_estimate": float(predicted_hours), 
                "sessions_needed": int(assignment_details.get('work_sessions', 1)),
                "assignment_type": assignment_details.get('assignment_type', 'p_set')
            })

        # ---------------------------------------------------------
        # 4. CALENDAR GENERATION
        # ---------------------------------------------------------
        backend_preferences = {
            "timezone": "America/New_York",
            "work_windows": {
                "weekday_start_hour": float(frontend_prefs.get('weekdayStart', '09:00').split(':')[0]),
                "weekday_end_hour": float(frontend_prefs.get('weekdayEnd', '22:00').split(':')[0]),
                "weekend_start_hour": float(frontend_prefs.get('weekendStart', '10:00').split(':')[0]),
                "weekend_end_hour": float(frontend_prefs.get('weekendEnd', '20:00').split(':')[0])
            }
        }

        calendar_input_data = {
            "user_preferences": backend_preferences,
            "assignments": formatted_assignments
        }

        result = calendar_maker.process_schedule_request(
            calendar_input_data, 
            ics_files_bytes,
            app.config['UPLOAD_FOLDER']
        )

        return jsonify({
            'message': 'Success',
            'ics_url': f"/download/{result['ics_filename']}",
            'stats': {
                'scheduled': result['scheduled_count'],
                'unscheduled': result['unscheduled_count']
            },
            'assignments': formatted_assignments # <--- NEW: SENDING PREDICTIONS BACK
        })

    except Exception as e:
        print(f"API Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
