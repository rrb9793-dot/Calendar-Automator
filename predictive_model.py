import os
import pandas as pd
import numpy as np
import joblib
from sklearn.linear_model import ElasticNet

# --- CONFIGURATION ---
# Uses the directory of this script to find survey.csv
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, 'survey.csv')

model = None
model_columns = []

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

            model = ElasticNet(alpha=0.078, l1_ratio=0.95, max_iter=5000)
            model.fit(X, y)

            print("✅ Predictive Model Trained Successfully.")
        else:
            print("❌ Error: 'time_spent_hours' column missing from survey.csv.")

    except Exception as e:
        print(f"❌ Error training model: {e}")
else:
    print(f"❌ Error: {CSV_PATH} not found.")
