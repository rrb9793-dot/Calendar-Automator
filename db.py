import os
import psycopg2
from urllib.parse import urlparse

# --- DATABASE CONFIGURATION ---
# 1. Try to get the automatic Railway URL first (Best Practice)
DATABASE_URL = os.environ.get("DATABASE_URL")

# 2. Fallback credentials (only used if DATABASE_URL is missing)
DB_NAME = "railway"
DB_USER = "postgres"
DB_PASSWORD = "KabjEWZlzLUmdxXWUTBSiQgQkcJUvNFC"
DB_HOST = "postgres.railway.internal"
DB_PORT = "5432"

def get_db_connection():
    """Establishes a connection to the database using the best available method."""
    try:
        if DATABASE_URL:
            # Connect using the secure Railway Variable
            return psycopg2.connect(DATABASE_URL)
        else:
            # Fallback for local testing (often fails on deployment if not configured)
            return psycopg2.connect(
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port=DB_PORT
            )
    except Exception as e:
        print(f"❌ FATAL: Could not connect to DB. Check DATABASE_URL. Error: {e}")
        return None

def save_student_profile(survey, prefs):
    """Saves student info. Updates existing users if email matches."""
    conn = get_db_connection()
    if not conn: return

    try:
        cur = conn.cursor()
        print(f"📝 Saving Profile for: {survey.get('email')}")

        # Note: If your DB column actually has a space ("second concentration"), 
        # change second_concentration to "second concentration" (with quotes) below.
        query = """
            INSERT INTO students (
                email, timezone, year, major, second_concentration, minor,
                weekday_start_hour, weekday_end_hour, weekend_start_hour, weekend_end_hour
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (email) DO UPDATE SET
                timezone = EXCLUDED.timezone,
                year = EXCLUDED.year,
                major = EXCLUDED.major,
                second_concentration = EXCLUDED.second_concentration,
                minor = EXCLUDED.minor,
                weekday_start_hour = EXCLUDED.weekday_start_hour,
                weekday_end_hour = EXCLUDED.weekday_end_hour,
                weekend_start_hour = EXCLUDED.weekend_start_hour,
                weekend_end_hour = EXCLUDED.weekend_end_hour;
        """
        
        cur.execute(query, (
            survey.get('email'),
            prefs.get('timezone', 'UTC'),
            int(survey.get('year', 0)) if survey.get('year') else 0,
            survey.get('major'),
            survey.get('second_concentration', 'N/A'),
            survey.get('minor', 'N/A'),
            prefs.get('weekdayStart'),
            prefs.get('weekdayEnd'),
            prefs.get('weekendStart'),
            prefs.get('weekendEnd')
        ))
        conn.commit()
        print(f"✅ Profile Saved: {survey.get('email')}")
        cur.close()
        conn.close()

    except Exception as e:
        print(f"❌ ERROR SAVING PROFILE: {e}")
        if conn: conn.rollback()

def save_assignment(email, course_data, predicted_hours=0):
    """Saves a single assignment linked to the student."""
    conn = get_db_connection()
    if not conn: return

    try:
        cur = conn.cursor()
        
        # Convert Yes/No strings to Python Booleans
        is_group = True if course_data.get('work_in_group') == "Yes" else False
        is_person = True if course_data.get('submitted_in_person') == "Yes" else False
        
        query = """
            INSERT INTO assignments (
                assignment_name, assignment_type, field_of_study, 
                external_resources, work_sessions, time_spent_hours, 
                work_location, work_in_group, submit_in_person, email
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cur.execute(query, (
            course_data.get('assignment_name'),
            course_data.get('assignment_type'),
            course_data.get('field_of_study'),
            course_data.get('external_resources'),
            int(course_data.get('work_sessions', 1)),
            int(predicted_hours), 
            course_data.get('work_location'),
            is_group,
            is_person,
            email
        ))
        conn.commit()
        print(f"✅ Assignment Saved: {course_data.get('assignment_name')}")
        cur.close()
        conn.close()

    except Exception as e:
        print(f"❌ ERROR SAVING ASSIGNMENT: {e}")
        if conn: conn.rollback()
