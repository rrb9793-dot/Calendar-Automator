import os
import json
import time
import pandas as pd
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from whitenoise import WhiteNoise

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
        # Survey data is here if you need it later: req_data.get('survey', {})

        # B. User ICS Files
        ics_files_bytes = []
        if 'ics' in request.files:
            # Handle multiple files or single file under key 'ics'
            files = request.files.getlist('ics')
            for f in files:
                if f.filename != '':
                    ics_files_bytes.append(f.read())
                    f.seek(0)

        # ---------------------------------------------------------
        # 2. PDF PARSING
        # ---------------------------------------------------------
        assignments_list = []
        uploaded_pdfs = request.files.getlist('pdfs')
        
        if uploaded_pdfs:
            print(f"Processing {len(uploaded_pdfs)} PDF(s)...")
            pdf_dfs = []
            for pdf in uploaded_pdfs:
                if pdf.filename == '': continue
                filename = secure_filename(pdf.filename)
                path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                pdf.save(path)
                
                # Parse using the new parser code
                # Passes GEMINI_API_KEY from env, or parser falls back to hardcoded one
                df = syllabus_parser.parse_syllabus_to_data(path, GEMINI_API_KEY)
                
                if df is not None and not df.empty:
                    pdf_dfs.append(df)
            
            # Consolidate all parsed dataframes
            if pdf_dfs:
                master_df = pd.concat(pdf_dfs, ignore_index=True)
                final_df = syllabus_parser.consolidate_assignments(master_df)
                parsed_records = final_df.to_dict(orient='records')
                assignments_list.extend(parsed_records)

        # ---------------------------------------------------------
        # 3. PREPARE & RUN CALENDAR MAKER
        # ---------------------------------------------------------
        # Set default hours if frontend keys are missing
        backend_preferences = {
            "timezone": "America/New_York",
            "work_windows": {
                "weekday_start_hour": float(frontend_prefs.get('weekdayStart', '09:00').split(':')[0]),
                "weekday_end_hour": float(frontend_prefs.get('weekdayEnd', '22:00').split(':')[0]),
                "weekend_start_hour": float(frontend_prefs.get('weekendStart', '10:00').split(':')[0]),
                "weekend_end_hour": float(frontend_prefs.get('weekendEnd', '20:00').split(':')[0])
            }
        }

        formatted_assignments = []
        for i, item in enumerate(assignments_list):
            # --- DATE/TIME FIX APPLIED HERE ---
            date_str = item.get("Date")
            time_str = item.get("Time")
            
            # Default to 11:59 PM if parser returned None for time
            if not time_str:
                time_str = "11:59 PM"
            
            # Combine them so calendar_maker gets a full timestamp
            full_due_string = f"{date_str} {time_str}"
            
            formatted_assignments.append({
                "id": f"assign_{i}",
                "name": item.get("Assignment", "Untitled Task"),
                "class_name": item.get("Course", "General"),
                "due_date": full_due_string, 
                "time_estimate": 2.0, 
                "assignment_type": item.get("Category", "p_set")
            })

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
            }
        })

    except Exception as e:
        print(f"API Error: {e}")
        # Helpful for debugging: print the full traceback in logs if needed
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
