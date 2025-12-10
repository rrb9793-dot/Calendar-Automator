import os
import json
import time
import pandas as pd
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from whitenoise import WhiteNoise

# --- DATABASE IMPORTS ---
import psycopg2 

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
# DATABASE CONFIGURATION
# ==========================================
# We use os.environ.get to prefer Railway's auto-injected variables, 
# falling back to your hardcoded strings if needed.
DB_NAME = os.environ.get("PGDATABASE", "railway")
DB_USER = os.environ.get("PGUSER", "postgres")
DB_PASSWORD = os.environ.get("PGPASSWORD", "mOUfapERMofXipKrrolKOZYGpKgzuokF")
DB_HOST = os.environ.get("PGHOST", "postgres.railway.internal")
DB_PORT = os.environ.get("PGPORT", "5432")

def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"❌ Database Connection Error: {e}")
        return None

# ==========================================
# ROUTES
# ==========================================

@app.route('/', methods=['GET'])
def home():
    # Test DB connection on home load (optional, just for debugging logs)
    conn = get_db_connection()
    if conn:
        print("✅ DB Connected Successfully")
        conn.close()
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
        
        # A. Metadata (Survey & Preferences)
        data_str = request.form.get('data')
        req_data = json.loads(data_str) if data_str else {}
        
        frontend_prefs = req_data.get('preferences', {})
        frontend_survey = req_data.get('survey', {})
        
        # B. User ICS Files (Busy Time)
        ics_files_bytes = []
        if 'ics' in request.files and request.files['ics'].filename != '':
            ics_file = request.files['ics']
            ics_files_bytes.append(ics_file.read())
            ics_file.seek(0) 

        # ---------------------------------------------------------
        # 2. PDF PARSING (Syllabus -> Assignments)
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
                
                # Run Syllabus Parser
                df = syllabus_parser.parse_syllabus_to_data(path, GEMINI_API_KEY)
                if df is not None and not df.empty:
                    pdf_dfs.append(df)
            
            # Consolidate
            if pdf_dfs:
                master_df = pd.concat(pdf_dfs, ignore_index=True)
                final_df = syllabus_parser.consolidate_assignments(master_df)
                parsed_records = final_df.to_dict(orient='records')
                assignments_list.extend(parsed_records)

        # ---------------------------------------------------------
        # 3. PREPARE DATA FOR CALENDAR MAKER
        # ---------------------------------------------------------
        
        # Map Frontend Preferences -> Calendar Maker Format
        backend_preferences = {
            "timezone": "America/New_York",
            "work_windows": {
                "weekday_start_hour": float(frontend_prefs.get('weekdayStart', '09:00').split(':')[0]),
                "weekday_end_hour": float(frontend_prefs.get('weekdayEnd', '22:00').split(':')[0]),
                "weekend_start_hour": float(frontend_prefs.get('weekendStart', '10:00').split(':')[0]),
                "weekend_end_hour": float(frontend_prefs.get('weekendEnd', '20:00').split(':')[0])
            }
        }

        # Format Assignments for Calendar Maker
        formatted_assignments = []
        for i, item in enumerate(assignments_list):
            formatted_assignments.append({
                "id": f"assign_{i}",
                "name": item.get("Assignment", "Untitled Task"),
                "class_name": item.get("Course", "General"),
                "due_date": item.get("Date"), 
                "time_estimate": 2.0, 
                "assignment_type": item.get("Category", "p_set")
            })

        calendar_input_data = {
            "user_preferences": backend_preferences,
            "assignments": formatted_assignments
        }

        # ---------------------------------------------------------
        # 4. RUN CALENDAR MAKER
        # ---------------------------------------------------------
        result = calendar_maker.process_schedule_request(
            calendar_input_data, 
            ics_files_bytes,
            app.config['UPLOAD_FOLDER']
        )

        # ---------------------------------------------------------
        # 5. RESPONSE
        # ---------------------------------------------------------
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
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
