import os
import pandas as pd
import numpy as np
import joblib
from sklearn.linear_model import ElasticNet

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, 'survey.csv')

model = None

# STRICT COLUMN DEFINITION
# These are the exact columns your model was trained on.
MODEL_COLUMNS = [
    'work_sessions',
    'year_2027', 'year_2028', 'year_2029',
    'major_category_business', 'major_category_engineering', 'major_category_math', 
    'major_category_natural_sciences', 'major_category_social_sciences_law', 'major_category_tech_data',
    'second_concentration_category_health_education', 'second_concentration_category_math', 
    'second_concentration_category_tech_data',
    'minor_category_business', 'minor_category_math', 'minor_category_natural_sciences', 
    'minor_category_social_sciences_law', 'minor_category_tech_data',
    'field_of_study_category_business', 'field_of_study_category_math', 
    'field_of_study_category_natural_sciences', 'field_of_study_category_social_sciences_law', 
    'field_of_study_category_tech_data',
    'assignment_type_coding', 'assignment_type_discussion', 'assignment_type_essay', 
    'assignment_type_modeling', 'assignment_type_p_set', 'assignment_type_presentation', 
    'assignment_type_readings', 'assignment_type_research_paper',
    'external_resources_class_materials', 'external_resources_google',
    'work_location_public', 'work_location_school',
    'worked_in_group_Yes', 'submitted_in_person_Yes'
]

# ==========================================
# PART 1: TRAINING (Strictly uses survey.csv)
# ==========================================
if os.path.exists(CSV_PATH):
    try:
        # Load Data
        survey_df = pd.read_csv(CSV_PATH)

        # --- 1. Renaming ---
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
        survey_df = survey_df.rename(columns=new_column_names)

        # --- 2. Mappings ---
        category_mapping = {
            'Accounting': 'business', 'Finance': 'business', 'Economics': 'business', 'Business Administration': 'business',
            'Management': 'business', 'Marketing': 'business', 'International Business': 'business', 'Entrepreneurship': 'business',
            'Supply Chain Management / Logistics': 'business', 'Management Information Systems (MIS)': 'tech_data',
            'Computer Science': 'tech_data', 'Information Technology': 'tech_data', 'Data Science': 'tech_data',
            'Data Analytics': 'tech_data', 'Computer Engineering': 'engineering', 'Software Engineering': 'engineering',
            'Electrical Engineering': 'engineering', 'Mechanical Engineering': 'engineering', 'Industrial Engineering': 'engineering',
            'Civil Engineering': 'engineering', 'Chemical Engineering': 'engineering', 'Systems Engineering': 'engineering',
            'Biomedical Engineering': 'engineering', 'Environmental Engineering': 'engineering', 'Mathematics': 'math',
            'Statistics': 'math', 'Applied Mathematics': 'math', 'Physics': 'natural_sciences', 'Chemistry': 'natural_sciences',
            'Biology': 'natural_sciences', 'Environmental Science': 'natural_sciences', 'Biochemistry': 'natural_sciences',
            'Neuroscience': 'natural_sciences', 'Marine Science': 'natural_sciences', 'Environmental Studies': 'natural_sciences',
            'Agriculture': 'natural_sciences', 'Forestry': 'natural_sciences', 'Political Science': 'social_sciences_law',
            'Psychology': 'social_sciences_law', 'Sociology': 'social_sciences_law', 'Anthropology': 'social_sciences_law',
            'International Relations': 'social_sciences_law', 'Public Policy': 'social_sciences_law', 'Geography': 'social_sciences_law',
            'Criminology': 'social_sciences_law', 'Legal Studies': 'social_sciences_law', 'Urban Studies / Planning': 'social_sciences_law',
            'Public Administration': 'social_sciences_law', 'Homeland Security': 'social_sciences_law', 'English / Literature': 'arts_humanities',
            'History': 'arts_humanities', 'Philosophy': 'arts_humanities', 'Linguistics': 'arts_humanities', 'Art / Art History': 'arts_humanities',
            'Design / Graphic Design': 'arts_humanities', 'Music': 'arts_humanities', 'Theatre / Performing Arts': 'arts_humanities',
            'Communications': 'arts_humanities', 'Journalism': 'arts_humanities', 'Film / Media Studies': 'arts_humanities',
            'Nursing': 'health_education', 'Public Health': 'health_education', 'Pre-Med / Biology (Health Sciences)': 'health_education',
            'Kinesiology / Exercise Science': 'health_education', 'Pharmacy': 'health_education', 'Nutrition': 'health_education',
            'Education': 'health_education', 'Early Childhood Education': 'health_education', 'Secondary Education': 'health_education',
            'Human Development': 'health_education', 'Social Work': 'health_education',
        }

        # Apply Mappings
        for col in ['major', 'second_concentration', 'minor', 'field_of_study']:
            if col in survey_df.columns:
                survey_df[f'{col}_category'] = survey_df[col].map(category_mapping)

        assignment_type_mapping = {
            'Problem Set': 'p_set', 'Coding Assignment': 'coding', 'Research Paper': 'research_paper',
            'Creative Writing/Essay': 'essay', 'Presentation/Slide deck': 'presentation',
            'Modeling (financial, statistics, data)': 'modeling', 'Discussion post/short written assignment': 'discussion',
            'Readings (textbooks or otherwise)': 'readings', 'Case Study': 'case_study'
        }
        survey_df['assignment_type'] = survey_df['assignment_type'].replace(assignment_type_mapping)

        external_resources_mapping = {
            'Textbook / class materials': 'class_materials', 'Google/internet': 'google', 'AI / Chatgpt': 'ai',
            'Tutoring service (Chegg, etc.)': 'tutoring_service', 'Study group with peers': 'study_group', 'Other': 'other'
        }
        survey_df['external_resources'] = survey_df['external_resources'].replace(external_resources_mapping)

        work_location_mapping = {
            'At home/private setting': 'home', 'School/library': 'school', 'Other public setting (cafe, etc.)': 'public'
        }
        survey_df['work_location'] = survey_df['work_location'].replace(work_location_mapping)

        # --- 3. One-Hot Encoding ---
        categorical_cols = ['year', 'major_category', 'second_concentration_category', 'minor_category', 
                            'field_of_study_category', 'assignment_type', 'external_resources', 
                            'work_location', 'worked_in_group', 'submitted_in_person']

        for col in categorical_cols:
            if col in survey_df.columns:
                survey_df = pd.get_dummies(survey_df, columns=[col], prefix=col, dtype=int, drop_first=True)

        # Drop Unused
        columns_to_drop = ['major', 'second_concentration', 'minor', 'class_name', 'field_of_study', 'Who referred you to this survey?']
        survey_df = survey_df.drop(columns=[c for c in columns_to_drop if c in survey_df.columns])

        # --- 4. Training ---
        if 'time_spent_hours' in survey_df.columns:
            X = survey_df.drop('time_spent_hours', axis=1)
            y = survey_df['time_spent_hours']

            # Ensure we strictly use the MODEL_COLUMNS (if they exist in survey data)
            # This prevents training on junk columns if the CSV changes
            available_cols = [c for c in MODEL_COLUMNS if c in X.columns]
            X = X[available_cols]

            model = ElasticNet(alpha=0.078, l1_ratio=0.95, max_iter=5000)
            model.fit(X, y)

            print("✅ Predictive Model Trained Successfully.")
        else:
            print("❌ Error: 'time_spent_hours' column missing from survey.csv.")

    except Exception as e:
        print(f"❌ Error training model: {e}")
else:
    print(f"❌ Error: {CSV_PATH} not found.")


# ==========================================
# PART 2: FRONTEND MAPPING (Strictly for Prediction)
# ==========================================
def predict_assignment_time(user_profile, assignment_details):
    """
    1. Accepts raw frontend strings.
    2. Maps them to the categories used in training.
    3. One-hot encodes them into the exact MODEL_COLUMNS structure.
    4. Returns predicted hours.
    """
    if model is None:
        return 2.0 # Fallback default

    # A. Map Frontend Options -> Model Internal Categories
    FRONTEND_MAP = {
        # Majors / Fields
        "Business": "business",
        "Tech & Data Science": "tech_data",
        "Engineering": "engineering",
        "Math": "math",
        "Natural Sciences": "natural_sciences",
        "Social Sciences": "social_sciences_law",
        "Arts & Humanities": "arts_humanities",
        "Health & Education": "health_education",
        
        # Assignment Types
        "Problem Set": "p_set",
        "Coding Assignment": "coding",
        "Research Paper": "research_paper",
        "Creative Writing/Essay": "essay",
        "Presentation": "presentation",
        "Modeling": "modeling",
        "Discussion Post": "discussion",
        "Readings": "readings",
        "Case Study": "case_study",
        
        # Resources
        "Textbook / class materials": "class_materials",
        "Google/internet": "google",
        "AI / Chatgpt": "ai",
        
        # Locations
        "At home/private setting": "home",
        "School/library": "school",
        "Other public setting (cafe, etc.)": "public",
        
        # Boolean Checkboxes
        "Yes": "Yes",
        "No": "No"
    }

    # B. Initialize Empty Vector with EXACT MODEL COLUMNS
    input_vector = {col: 0 for col in MODEL_COLUMNS}

    # C. Helper to flip the specific 1-hot bit
    def set_feature(prefix, raw_value):
        mapped_val = FRONTEND_MAP.get(raw_value)
        if mapped_val:
            col_name = f"{prefix}_{mapped_val}"
            # Only set if it exists in our strict model definition
            if col_name in input_vector:
                input_vector[col_name] = 1
    
    # D. Populate Features from Input
    # 1. Continuous Variables
    try:
        ws = int(assignment_details.get('work_sessions', 1))
        input_vector['work_sessions'] = ws
    except:
        input_vector['work_sessions'] = 1

    # 2. Categorical Variables (User Profile)
    year_val = user_profile.get('year') # e.g., "2027"
    if f"year_{year_val}" in input_vector:
        input_vector[f"year_{year_val}"] = 1
        
    set_feature('major_category', user_profile.get('major'))
    set_feature('second_concentration_category', user_profile.get('second_concentration'))
    set_feature('minor_category', user_profile.get('minor'))
    
    # 3. Categorical Variables (Assignment Specifics)
    set_feature('field_of_study_category', assignment_details.get('field_of_study'))
    set_feature('assignment_type', assignment_details.get('assignment_type'))
    set_feature('external_resources', assignment_details.get('external_resources'))
    set_feature('work_location', assignment_details.get('work_location'))
    set_feature('worked_in_group', assignment_details.get('work_in_group'))
    set_feature('submitted_in_person', assignment_details.get('submitted_in_person'))

    # E. Convert to DataFrame
    input_df = pd.DataFrame([input_vector])
    
    # F. ENFORCE INT64 FOR WORK SESSIONS
    input_df['work_sessions'] = input_df['work_sessions'].astype('int64')

    # Ensure correct column order matches MODEL_COLUMNS exactly
    input_df = input_df[MODEL_COLUMNS]

    prediction = model.predict(input_df)[0]
    return round(max(0.5, prediction), 2)
