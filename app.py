import os
import json
import pandas as pd
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from whitenoise import WhiteNoise
from google.api_core.exceptions import ResourceExhausted

import predictive_model 
import syllabus_parser 
import calendar_maker
import db 

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

@app.route('/', methods=['GET'])
def home(): return render_template('mains.html')

@app.route('/download/<filename>')
def download_file(filename): return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename), as_attachment=True)

@app.route('/api/get-user-preferences', methods=['GET'])
def get_user_preferences_route():
    email = request.args.get('email'); return (jsonify(db.get_user_preferences(email)) if email and db.get_user_preferences(email) else (jsonify({}), 404))

@app.route('/api/generate-schedule', methods=['POST'])
def generate_schedule():
    try:
        data_str = request.form.get('data')
        req_data = json.loads(data_str) if data_str else {}
        frontend_prefs = req_data.get('preferences', {})
        survey_data = req_data.get('survey', {})
        manual_courses = req_data.get('courses', [])

        if survey_data.get('email'): db.save_user_preferences(survey_data, frontend_prefs)

        # UPDATED: Capture multiple files from getlist
        ics_files_bytes = []
        if 'ics' in request.files:
            for f in request.files.getlist('ics'):
                if f.filename != '':
                    ics_files_bytes.append(f.read())
                    f.seek(0)

        all_assignments = []
        for course in manual_courses:
            assign_name = course.get('assignment_name', '').strip()
            if not assign_name: continue
            course_field = course.get('field_of_study', '')
            final_name = f"{assign_name} ({course_field})" if course_field and course_field != "N/A" else assign_name
            all_assignments.append({"source_type": "manual", "Assignment": final_name, "Date": course.get('due_date'), "Time": "23:59", "Course": course_field, "Category": course.get('assignment_type', 'p_set'), "raw_details": course})

        pdf_count = int(request.form.get('pdf_count', 0))
        if pdf_count > 0:
            pdf_dfs = []
            for i in range(pdf_count):
                pdf = request.files.get(f'pdf_{i}')
                if not pdf or pdf.filename == '': continue
                path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(pdf.filename))
                pdf.save(path)
                try:
                    df = syllabus_parser.parse_syllabus_to_data(path, GEMINI_API_KEY)
                    if df is not None and not df.empty: pdf_dfs.append(df)
                except ResourceExhausted: return jsonify({'error': 'AI Quota Exceeded.'}), 429
                except Exception as e: print(f"Parser Error: {e}"); continue
            if pdf_dfs:
                master_df = pd.concat(pdf_dfs, ignore_index=True)
                for record in syllabus_parser.consolidate_assignments(master_df).to_dict(orient='records'):
                    record["source_type"] = "pdf"; all_assignments.append(record)

        formatted_assignments = []
        for i, item in enumerate(all_assignments):
            raw_name = item.get("Assignment", "").strip()
            if not raw_name or raw_name == "Untitled": continue
            category = item.get('Category', 'p_set')

            if item["source_type"] == "manual":
                raw = item["raw_details"]
                predicted_hours = predictive_model.predict_assignment_time(survey_data, raw)
                sessions_needed, is_fixed_event = int(raw.get('work_sessions', 1)), False
                if survey_data.get('email'): db.save_assignment(survey_data['email'], raw, predicted_hours)
            else:
                is_exam = (category == "Exam")
                ai_sessions = int(item.get("Sessions", 1))
                if is_exam: sessions_needed, predicted_hours, is_fixed_event = 1, 1.25, True
                else:
                    sessions_needed, is_fixed_event = max(1, ai_sessions), False
                    predicted_hours = predictive_model.predict_assignment_time(survey_data, {"assignment_name": item.get("Assignment", "Untitled"), "work_sessions": sessions_needed, "assignment_type": category, "field_of_study": item.get("Field", survey_data.get('major', 'Business')), "external_resources": 'Google/internet', "work_location": 'At home/private setting', "work_in_group": 'No', "submitted_in_person": 'No'})

            formatted_assignments.append({"id": f"assign_{i}", "name": item.get("Assignment", "Untitled Task"), "class_name": item.get("Course", "General"), "due_date": f"{item.get('Date')} {item.get('Time') if item.get('Time') else '23:59'}", "time_estimate": float(predicted_hours), "sessions_needed": sessions_needed, "assignment_type": category, "is_fixed_event": is_fixed_event})

        backend_preferences = {"timezone": frontend_prefs.get('timezone', 'America/New_York'), "work_windows": {"weekday_start_hour": float(frontend_prefs.get('weekdayStart', '09:00').split(':')[0]), "weekday_end_hour": float(frontend_prefs.get('weekdayEnd', '22:00').split(':')[0]), "weekend_start_hour": float(frontend_prefs.get('weekendStart', '10:00').split(':')[0]), "weekend_end_hour": float(frontend_prefs.get('weekendEnd', '20:00').split(':')[0])}}
        result = calendar_maker.process_schedule_request({"user_preferences": backend_preferences, "assignments": formatted_assignments}, ics_files_bytes, app.config['UPLOAD_FOLDER'])

        return jsonify({'message': 'Success', 'ics_url': f"/download/{result['ics_filename']}", 'stats': {'scheduled': result['scheduled_count'], 'unscheduled': result['unscheduled_count']}, 'assignments': formatted_assignments})

    except Exception as e: return jsonify({'error': str(e)}), 500

if __name__ == '__main__': app.run(debug=True, port=5000)
