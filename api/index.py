from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
import pandas as pd
import numpy as np
import os
import sys
import pickle
import json
from datetime import datetime

# Sklearn Imports
from sklearn.linear_model import ElasticNet

# ============================================
# 1. CONFIGURATION & PATHS
# ============================================

# 1. Get the current directory of this script
current_directory = os.path.dirname(os.path.abspath(__file__))

# 2. Build the exact paths to your static and template folders
template_dir = os.path.join(current_directory, 'templates')
static_dir = os.path.join(current_directory, 'static')

# 3. Tell Flask to use these specific paths
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
# app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# Upload Config (Using /tmp for serverless/Vercel compatibility)
UPLOAD_FOLDER = '/tmp'
ALLOWED_EXTENSIONS = {'pdf', 'ics'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Data Store Paths
TRAINING_PATH = os.path.join(UPLOAD_FOLDER, "training_data.pkl")
ABOUT_PATH = os.path.join(UPLOAD_FOLDER, "about_you.pkl")

# ==========================================
# 2. ML MODEL & MAPPINGS
# ==========================================

model = None
model_columns = []

# --- MAPPINGS (Must match Training Data exactly) ---
new_column_names = {
    'What year are you? ': 'year',
    'What is your major/concentration?': 'major',
    'Second concentration? (if none, select N/A)': 'second_concentration',
    'Minor? (if none select N/A)': 'minor',
    'What class was the assignment for (Please write as said in BrightSpace)': 'class_name',
    'What field of study was the assignment in?': 'field_of_study',
    'What type of assignment was it?': 'assignment_type',
    'Approximately how long did it take (in hours)': 'time_spent_hours',
    'What was the extent of your reliance on external resources? ': 'external_resources',
    'Where did you primarily work on the assignment?': 'work_location',
    'Did you work in a group?': 'worked_in_group',
    'Did you have to submit the assignment in person (physical copy)?': 'submitted_in_person',
    'Approximately how many separate work sessions did you spend on this assignment? (1 or more)': 'work_sessions'
}

category_mapping = {
    'Accounting': 'business', 'Finance': 'business', 'Economics': 'business',
    'Business Administration': 'business', 'Management': 'business', 'Marketing': 'business',
    'International Business': 'business', 'Entrepreneurship': 'business',
    'Supply Chain Management / Logistics': 'business',
    'Management Information Systems (MIS)': 'tech_data', 'Computer Science': 'tech_data',
    'Information Technology': 'tech_data', 'Data Science': 'tech_data', 'Data Analytics': 'tech_data',
    'Computer Engineering': 'engineering', 'Software Engineering': 'engineering',
    'Electrical Engineering': 'engineering', 'Mechanical Engineering': 'engineering',
    'Industrial Engineering': 'engineering', 'Civil Engineering': 'engineering',
    'Chemical Engineering': 'engineering', 'Systems Engineering': 'engineering',
    'Biomedical Engineering': 'engineering', 'Environmental Engineering': 'engineering',
    'Mathematics': 'math', 'Statistics': 'math', 'Applied Mathematics': 'math',
    'Physics': 'natural_sciences', 'Chemistry': 'natural_sciences', 'Biology': 'natural_sciences',
    'Environmental Science': 'natural_sciences', 'Biochemistry': 'natural_sciences',
    'Neuroscience': 'natural_sciences', 'Marine Science': 'natural_sciences',
    'Environmental Studies': 'natural_sciences', 'Agriculture': 'natural_sciences', 'Forestry': 'natural_sciences',
    'Political Science': 'social_sciences_law', 'Psychology': 'social_sciences_law',
    'Sociology': 'social_sciences_law', 'Anthropology': 'social_sciences_law',
    'International Relations': 'social_sciences_law', 'Public Policy': 'social_sciences_law',
    'Geography': 'social_sciences_law', 'Criminology': 'social_sciences_law',
    'Legal Studies': 'social_sciences_law', 'Urban Studies / Planning': 'social_sciences_law',
    'Public Administration': 'social_sciences_law', 'Homeland Security': 'social_sciences_law',
    'English / Literature': 'arts_humanities', 'History': 'arts_humanities',
    'Philosophy': 'arts_humanities', 'Linguistics': 'arts_humanities',
    'Art / Art History': 'arts_humanities', 'Design / Graphic Design': 'arts_humanities',
    'Music': 'arts_humanities', 'Theatre / Performing Arts': 'arts_humanities',
    'Communications': 'arts_humanities', 'Journalism': 'arts_humanities',
    'Film / Media Studies': 'arts_humanities',
    'Nursing': 'health_education', 'Public Health': 'health_education',
    'Pre-Med / Biology (Health Sciences)': 'health_education',
    'Kinesiology / Exercise Science': 'health_education', 'Pharmacy': 'health_education',
    'Nutrition': 'health_education', 'Education': 'health_education',
    'Early Childhood Education': 'health_education', 'Secondary Education': 'health_education',
    'Human Development': 'health_education', 'Social Work': 'health_education',
}

assignment_type_mapping = {
    'Problem Set': 'p_set', 'Coding Assignment': 'coding', 'Research Paper': 'research_paper',
    'Creative Writing/Essay': 'essay', 'Presentation/Slide deck': 'presentation',
    'Modeling (financial, statistics, data)': 'modeling',
    'Discussion post/short written assignment': 'discussion',
    'Readings (textbooks or otherwise)': 'readings', 'Case Study': 'case_study'
}

external_resources_mapping = {
    'Textbook / class materials': 'class_materials', 'Google/internet': 'google',
    'AI / Chatgpt': 'ai', 'Tutoring service (Chegg, etc.)': 'tutoring_service',
    'Study group with peers': 'study_group', 'Other': 'other'
}

work_location_mapping = {
    'At home/private setting': 'home', 'School/library': 'school',
    'Other public setting (cafe, etc.)': 'public'
}

def initialize_model():
    """
    Loads the Student Survey CSV and trains the ElasticNet model on startup.
    """
    global model
    global model_columns
    
    print("🤖 Initializing ML model...")
    # Use the current_directory defined at the top
    csv_path = os.path.join(current_directory, 'Student Assignment Survey v2 2.csv')
    
    if not os.path.exists(csv_path):
        print(f"CRITICAL: CSV not found at {csv_path}")
        return

    try:
        # 1. Load & Clean
        survey_df = pd.read_csv(csv_path)
        survey_df = survey_df.rename(columns=new_column_names)
        
        # 2. Map Categories
        survey_df['major_category'] = survey_df['major'].map(category_mapping)
        survey_df['second_concentration_category'] = survey_df['second_concentration'].map(category_mapping)
        survey_df['minor_category'] = survey_df['minor'].map(category_mapping)
        survey_df['field_of_study_category'] = survey_df['field_of_study'].map(category_mapping)
        
        survey_df['assignment_type'] = survey_df['assignment_type'].replace(assignment_type_mapping)
        survey_df['external_resources'] = survey_df['external_resources'].replace(external_resources_mapping)
        survey_df['work_location'] = survey_df['work_location'].replace(work_location_mapping)

        # 3. One-Hot Encoding
        categorical_cols = ['year', 'major_category', 'second_concentration_category', 'minor_category', 
                            'field_of_study_category', 'assignment_type', 'external_resources', 
                            'work_location', 'worked_in_group', 'submitted_in_person']
        
        for col in categorical_cols:
            if col in survey_df.columns:
                survey_df = pd.get_dummies(survey_df, columns=[col], prefix=col, dtype=int, drop_first=True)

        # 4. Drop unused
        if 'Timestamp' in survey_df.columns: survey_df = survey_df.drop(columns=['Timestamp'])
        drop_cols = ['major', 'second_concentration', 'minor', 'class_name', 'field_of_study', 'Who referred you to this survey?']
        survey_df = survey_df.drop(columns=[c for c in drop_cols if c in survey_df.columns])

        # 5. Fit Model
        X = survey_df.drop('time_spent_hours', axis=1)
        y = survey_df['time_spent_hours']

        model = ElasticNet(alpha=0.078, l1_ratio=0.95, max_iter=5000)
        model.fit(X, y)
        
        # SAVE COLUMNS (Crucial for prediction alignment)
        model_columns = list(X.columns)
        print("✅ Model trained and ready.")
        
    except Exception as e:
        print(f"❌ Model initialization failed: {e}")

# Initialize immediately
initialize_model()


# ============================================
# 3. DATA STORAGE
# ============================================

class SimpleDataStore:
    def __init__(self, data_file=TRAINING_PATH, about_file=ABOUT_PATH):
        self.data_file = data_file
        self.about_file = about_file
        self.df = self._load_df(self.data_file)
        self.about_df = self._load_df(self.about_file)
    
    def _load_df(self, path):
        if os.path.exists(path):
            return pd.read_pickle(path)
        return pd.DataFrame()
    
    def save_submission(self, survey, courses, pdf_filenames, ics_filenames):
        # This saves the RAW frontend data for record-keeping
        timestamp = datetime.now().isoformat()
        new_row = {
            'timestamp': timestamp,
            'year': survey.get('year'),
            'major': survey.get('major'),
            'work_in_group': survey.get('workInGroup'),
            'work_location': survey.get('workLocation'),
            'min_work_time': survey.get('minWorkTime'),
            'max_work_time': survey.get('maxWorkTime'),
            'num_courses': len(courses),
            'courses_json': json.dumps(courses),
            'pdf_files': json.dumps(pdf_filenames),
            'ics_files': json.dumps(ics_filenames)
        }
        
        about_row = {
            'timestamp': timestamp,
            'year': new_row['year'],
            'major': new_row['major'],
            'work_in_group': new_row['work_in_group'],
            'work_location': new_row['work_location'],
        }
        
        self.df = pd.DataFrame([new_row])
        self.about_df = pd.DataFrame([about_row])
        
        self.df.to_pickle(self.data_file)
        self.about_df.to_pickle(self.about_file)
        return 0

    def get_dataframe(self):
        return self.df.copy()
        
    def get_about_dataframe(self):
        return self.about_df.copy()

data_store = SimpleDataStore()


# ============================================
# 4. PREDICTION LOGIC
# ============================================

def process_and_predict(survey, courses):
    """
    1. Takes frontend data.
    2. Creates a data row for each assignment.
    3. Runs the model.
    4. Returns the list of predictions.
    """
    global model
    global model_columns
    
    if not model or not courses:
        return []

    # 1. Prepare Rows (Combine Survey Info + Course Info)
    rows = []
    for course in courses:
        # Create a single data row for this assignment
        row = {
            # Student Attributes (From Survey)
            'year': survey.get('year'),
            'major': survey.get('major'),
            'second_concentration': survey.get('secondConcentration', 'N/A'),
            'minor': survey.get('minor', 'N/A'),
            'work_location': survey.get('workLocation'),
            'worked_in_group': survey.get('workInGroup'),
            'submitted_in_person': survey.get('submitInPerson', 'No'),
            
            # Course Attributes (From Course List)
            'assignment_type': course.get('type'),
            'field_of_study': course.get('subject'), 
            'external_resources': course.get('resources'),
            'class_name': course.get('name')
        }
        rows.append(row)

    # 2. Create DataFrame from these rows
    input_df = pd.DataFrame(rows)

    # 3. Apply Mappings (Identical to Training)
    if 'major' in input_df: 
        input_df['major_category'] = input_df['major'].map(category_mapping)
    if 'second_concentration' in input_df: 
        input_df['second_concentration_category'] = input_df['second_concentration'].map(category_mapping)
    if 'minor' in input_df: 
        input_df['minor_category'] = input_df['minor'].map(category_mapping)
    if 'field_of_study' in input_df: 
        input_df['field_of_study_category'] = input_df['field_of_study'].map(category_mapping)

    if 'assignment_type' in input_df: 
        input_df['assignment_type'] = input_df['assignment_type'].replace(assignment_type_mapping)
    if 'external_resources' in input_df: 
        input_df['external_resources'] = input_df['external_resources'].replace(external_resources_mapping)
    if 'work_location' in input_df: 
        input_df['work_location'] = input_df['work_location'].replace(work_location_mapping)

    # 4. One-Hot Encoding
    categorical_cols = ['year', 'major_category', 'second_concentration_category', 'minor_category', 
                        'field_of_study_category', 'assignment_type', 'external_resources', 
                        'work_location', 'worked_in_group', 'submitted_in_person']

    for col in categorical_cols:
        if col in input_df.columns:
            input_df = pd.get_dummies(input_df, columns=[col], prefix=col, dtype=int, drop_first=True)

    # 5. Align columns with the trained model
    input_df = input_df.reindex(columns=model_columns, fill_value=0)

    # 6. Predict
    try:
        preds = model.predict(input_df)
        
        # NOTE: At this point, we have the prediction. 
        # The input_df currently represents the "data rows" processed by the model.
        # We return the values to be merged with the assignment details in the route.
        return [float(p) for p in preds]
    except Exception as e:
        print(f"Prediction Error: {e}")
        return [0.0] * len(courses)


# ============================================
# 5. ROUTES
# ============================================

@app.route('/', methods=['GET'])
def home():
    return "Student Assignment API is Running"

@app.route('/static/<path:filename>')
def custom_static(filename):
    return send_from_directory(static_dir, filename)

@app.route('/api/generate-schedule', methods=['POST'])
def generate_schedule():
    try:
        data_json = request.form.get('data')
        if not data_json:
            return jsonify({'error': 'No data provided'}), 400
        
        data = json.loads(data_json)
        survey = data.get('survey', {})
        courses = data.get('courses', [])

        # 1. Handle Files (Store only)
        pdf_filenames = []
        if 'pdfs' in request.files:
            for pdf_file in request.files.getlist('pdfs'):
                if allowed_file(pdf_file.filename):
                    filename = secure_filename(pdf_file.filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    pdf_file.save(filepath)
                    pdf_filenames.append(filename)
        
        ics_filenames = []
        if 'ics' in request.files:
            ics_file = request.files['ics']
            if allowed_file(ics_file.filename):
                filename = secure_filename(ics_file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                ics_file.save(filepath)
                ics_filenames.append(filename)
        
        # 2. Store Raw Data
        data_store.save_submission(survey, courses, pdf_filenames, ics_filenames)
        
        # 3. PREDICT & MERGE
        # Get the predicted times based on the processed data rows
        predicted_times = process_and_predict(survey, courses)
        
        # Add the output time to the data row (assignment details)
        courses_with_predictions = []
        for i, course in enumerate(courses):
            c_copy = course.copy() # This contains the assignment details
            
            # Attach the predicted time to this row
            if i < len(predicted_times):
                c_copy['predicted_hours'] = round(predicted_times[i], 2)
            else:
                c_copy['predicted_hours'] = 0
            
            courses_with_predictions.append(c_copy)
        
        return jsonify({
            'status': 'success',
            'message': 'Data stored and predictions generated.',
            'courses': courses_with_predictions
        }), 200
    
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/view-data', methods=['GET'])
def view_data():
    df = data_store.get_dataframe()
    return jsonify({'status': 'success', 'data': df.to_dict('records')})

@app.route('/api/view-about', methods=['GET'])
def view_about():
    about_df = data_store.get_about_dataframe()
    return jsonify({'status': 'success', 'data': about_df.to_dict('records')})

@app.route('/api/health')
def health():
    return jsonify({'status': 'healthy'})

# Helper
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

if __name__ == '__main__':
    app.run(debug=True)

