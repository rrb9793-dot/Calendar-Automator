import os
import json
import time
import math
import pandas as pd
import recurring_ical_events
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

# Web Framework
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from whitenoise import WhiteNoise

# Calendar
from icalendar import Calendar as ICalLoader
from ics import Calendar as IcsCalendar, Event as IcsEvent

# --- CUSTOM MODULES ---
# Importing this automatically runs the training logic in predictive_model.py
import predictive_model 
# import syllabus_parser (Uncomment when ready to add parser)

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')

# Initialize App
app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
CORS(app)

# WhiteNoise (Static file serving)
app.wsgi_app = WhiteNoise(app.wsgi_app, root=STATIC_DIR, prefix='static/')

# File System Setup
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

# Constants
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
LOCAL_TZ = ZoneInfo("America/New_York")
CHUNK_SIZE = 60

# --- PREDICTIVE MODEL ---
# Access the fitted model and columns directly from the module
model = predictive_model.model
model_columns = predictive_model.model_columns

# Verification Log
if model:
    print("✅ Index.py: Predictive model loaded and ready.")
else:
    print("❌ Index.py: Predictive model failed to load (check survey.csv).")

# ==========================================
# ROUTES
# ==========================================

@app.route('/', methods=['GET'])
def home():
    return render_template('mains.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
