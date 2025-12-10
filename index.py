import os
import json
import time
import pandas as pd
import psycopg2
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from whitenoise import WhiteNoise

# --- CUSTOM MODULES ---
import predictive_model 
import syllabus_parser # <--- The file above

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
LOCAL_TZ = ZoneInfo("America/New_York")

#Database
DB_NAME = "railway"             # PGDATABASE
DB_USER = "postgres"            # PGUSER
DB_PASSWORD = "mOUfapERMofXipKrrolKOZYGpKgzuokF"    # PGPASSWORD
DB_HOST = "postgres.railway.internal"   # PGHOST
DB_PORT = "5432"                # PGPORT

def get_db_connection():
    import psycopg2
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )

# Load Predictive Model (kept as requested, even if unused for PDFs right now)
model = predictive_model.model

if model:
    print("✅ Index.py: Predictive model loaded.")
else:
    print("❌ Index.py: Predictive model failed to load.")

# ==========================================
# ROUTES
# ==========================================

@app.route('/', methods=['GET'])
def home():
    return render_template('mains.html')

@app.route('/api/generate-schedule', methods=['POST'])
def generate_schedule():
    try:
        # 1. Parse other form data (survey, etc.)
        data_str = request.form.get('data')
        req_data = json.loads(data_str) if data_str else {}
        courses = req_data.get('courses', []) # Manual inputs
        
        # 2. PDF Processing (The Core Task)
        uploaded_pdfs = request.files.getlist('pdfs')
        pdf_dfs = []

        if uploaded_pdfs:
            print(f"Processing {len(uploaded_pdfs)} PDF(s)...")
            for pdf in uploaded_pdfs:
                if pdf.filename == '': continue
                
                # Save file temporarily
                filename = secure_filename(pdf.filename)
                path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                pdf.save(path)
                
                # Run YOUR parser
                df = syllabus_parser.parse_syllabus_to_data(path)
                if df is not None and not df.empty:
                    pdf_dfs.append(df)
            
            # Consolidate Data
            if pdf_dfs:
                master_df = pd.concat(pdf_dfs, ignore_index=True)
                final_df = syllabus_parser.consolidate_assignments(master_df)
                
                # Convert to dict to send back to frontend or pass to calendar_maker
                parsed_courses = final_df.to_dict(orient='records')
                
                # Append to courses list (or handle separately)
                # Note: The keys here match your parser (Course, Date, Time, etc.)
                courses.extend(parsed_courses)

        # 3. Future Step: Calendar Maker 
        # (You said you will add this later. For now, we return the parsed data)
        
        return jsonify({
            'message': 'Success', 
            'courses': courses,
            'info': 'PDFs parsed and consolidated. Ready for Calendar Maker.'
        })

    except Exception as e:
        print(f"API Error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
