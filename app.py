import os
import json
import time
import pandas as pd
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from whitenoise import WhiteNoise
from google.api_core.exceptions import ResourceExhausted

# --- CUSTOM MODULES ---
import predictive_model 
import syllabus_parser 
import calendar_maker
import db 

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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# ==========================================
# ROUTES
# ==========================================

@app.route('/', methods=['GET'])
def home():
    return render_template('mains.html')

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename), as_attachment=True)

# --- USER PREFERENCES ROUTE ---
@app.route('/api/get-user-preferences', methods=['GET'])
def get_user_preferences_route():
    email = request.args.get('email')
    if not email:
        return jsonify({}), 400
    
    # Fetch from DB
    data = db.get_user_preferences(email)
    
    if data:
        return jsonify(data)
    else:
        return jsonify({}), 404

# --- GENERATE SCHEDULE ROUTE ---
@app.route('/api/generate-schedule', methods=['POST'])
def generate_schedule():
    try:
        # 1. GATHER INPUTS
        data_str = request.form.get('data')
        req_data = json.loads(data_str) if data_str else {}
        
        frontend_prefs = req_data.get('preferences', {})
        survey_data = req_data.get('survey', {})
        manual_courses = req_data.get('courses', [])

        # --- SAVE PREFERENCES ---
        if survey_data.get('email'):
            db.save_user_preferences(survey_data, frontend_prefs)

        # B. User ICS Files
        ics_files_bytes = []
        if 'ics' in request.files:
            files = request.files.getlist('ics')
            for f in files:
                if f.filename != '':
                    ics_files_bytes.append(f.read())
                    f.seek(0)

        # 2. AGGREGATE ASSIGNMENTS
        all_assignments = []
        
        # A. Manual Entries (USER INPUTS REIGN SUPREME HERE)
        for course in manual_courses:
            assign_name = course.get('assignment_name', 'Untitled')
            course_field = course.get('field_of_study', 'General')
            
            # Append Course Name here to match Parser style
            final_name = f"{assign_name} ({course_field})"

            all_assignments.append({
                "source_type": "manual",
                "Assignment": final_name, 
                "Date": course.get('due_date'),
                # For manual tasks, we assume user input due time or default to end of day
                "Time": "23:59", 
                "Course": course_field,
                "Category": course.get('assignment_type', 'p_set'),
                "raw_details": course 
            })

        # B. PDF Entries
        pdf_count = int(request.form.get('pdf_count', 0))
        
        if pdf_count > 0:
            print(f"Processing {pdf_count} PDF(s) with Gemini...", flush=True)
            pdf_dfs = []
            
            for i in range(pdf_count):
                pdf = request.files.get(f'pdf_{i}')
                # We NO LONGER check for manual course_name here.
                
                if not pdf or pdf.filename == '': continue
                
                filename = secure_filename(pdf.filename)
                path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                pdf.save(path)
                
                try:
                    # Parse using AI for course name
                    df = syllabus_parser.parse_syllabus_to_data(path, GEMINI_API_KEY)
                    
                    print(f"\n--- 📄 PARSER RESULT FOR: {filename} ---", flush=True)
                    if df is not None and not df.empty:
                        # .to_string() forces the logs to show the WHOLE table
                        print(df.to_string(), flush=True) 
                    else:
                        print("❌ Parser returned EMPTY or NONE.", flush=True)
                    print("------------------------------------------\n", flush=True)

                    if df is not None and not df.empty:
                        pdf_dfs.append(df)
                    time.sleep(2) 
                
                except ResourceExhausted:
                    print("❌ Google AI Quota Exceeded.", flush=True)
                    return jsonify({'error': 'Google AI Quota Exceeded. Please wait.'}), 429
                except Exception as e:
                    print(f"❌ Error processing {filename}: {e}", flush=True)
                    continue
            
            if pdf_dfs:
                master_df = pd.concat(pdf_dfs, ignore_index=True)
                final_df = syllabus_parser.consolidate_assignments(master_df)
                for record in final_df.to_dict(orient='records'):
                    record["source_type"] = "pdf"
                    all_assignments.append(record)

        # 3. PREDICTION & DB SAVE
        formatted_assignments = []
        
        # Hard PDF tasks that get 2 sessions by default
        HARD_TASKS = ['Problem Set', 'Coding Assignment', 'Research Paper', 'Modeling', 'Case Study']
        
        for i, item in enumerate(all_assignments):
            category = item.get('Category', 'p_set')
            
            # --- BRANCH 1: MANUAL (User overrides everything) ---
            if item["source_type"] == "manual":
                raw = item["raw_details"]
                
                # Use User's exact inputs
                assignment_details = raw 
                
                # Predict time (Manual tasks always go through predictor)
                predicted_hours = predictive_model.predict_assignment_time(survey_data, assignment_details)
                
                # Manual inputs for sessions
                sessions_needed = int(raw.get('work_sessions', 1))
                is_fixed_event = False # Manual tasks are "To-Dos", not fixed events

                if survey_data.get('email'):
                    db.save_assignment(survey_data['email'], assignment_details, predicted_hours)

            # --- BRANCH 2: PDF (Apply defaults) ---
            else:
                is_exam = (category == "Exam")
                
                # Defaults for PDF
                if is_exam:
                    sessions_needed = 1
                    predicted_hours = 1.25 # Default 1.25 hours (75 mins) for Exams
                    is_fixed_event = True  # <--- CRITICAL: Tells calendar this is a specific time
                else:
                    sessions_needed = 2 if category in HARD_TASKS else 1
                    is_fixed_event = False
                    
                    # Construct details for predictor (Assumes Home/Google)
                    assignment_details = {
                        "assignment_name": item.get("Assignment", "Untitled"),
                        "work_sessions": sessions_needed,
                        "assignment_type": category, 
                        "field_of_study": survey_data.get('major', 'Business'),
                        "external_resources": 'Google/internet',       # Default
                        "work_location": 'At home/private setting',    # Default
                        "work_in_group": 'No',
                        "submitted_in_person": 'No'
                    }
                    predicted_hours = predictive_model.predict_assignment_time(survey_data, assignment_details)

            # Formatting
            date_str = item.get("Date")
            time_str = item.get("Time")
            
            # If no time, manual default to end of day.
            # If parser didn't find time for Exam, it defaults to 23:59 (imperfect, but safe).
            if not time_str: time_str = "23:59"
            
            full_due_string = f"{date_str} {time_str}"
            
            formatted_assignments.append({
                "id": f"assign_{i}",
                "name": item.get("Assignment", "Untitled Task"),
                "class_name": item.get("Course", "General"),
                "due_date": full_due_string, 
                "time_estimate": float(predicted_hours), 
                "sessions_needed": sessions_needed,
                "assignment_type": category,
                "is_fixed_event": is_fixed_event # <--- New Flag passed to Calendar Maker
            })

        # 4. CALENDAR GENERATION
        backend_preferences = {
            "timezone": frontend_prefs.get('timezone', 'America/New_York'),
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
            'assignments': formatted_assignments
        })

    except Exception as e:
        print(f"API Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
