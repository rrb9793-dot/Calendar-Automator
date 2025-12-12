import os
import psycopg2

# --- DATABASE CONFIGURATION ---
# Using the credentials you provided
DB_NAME = "railway"
DB_USER = "postgres"
DB_PASSWORD = "KabjEWZlzLUmdxXWUTBSiQgQkcJUvNFC"
DB_HOST = "postgres.railway.internal"
DB_PORT = "5432"

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

def init_db():
    """Initializes the tables based on your schema screenshots."""
    conn = get_db_connection()
    if not conn: return
    
    try:
        cur = conn.cursor()
        
        # 1. Create Student Profile Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS students (
                email TEXT PRIMARY KEY,
                timezone TEXT,
                year INTEGER,
                major TEXT,
                second_concentration TEXT,
                minor TEXT,
                weekday_start_hour TEXT,
                weekday_end_hour TEXT,
                weekend_start_hour TEXT,
                weekend_end_hour TEXT
            );
        """)

        # 2. Create Assignments Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                assignment_id SERIAL PRIMARY KEY,
                assignment_name TEXT,
                assignment_type TEXT,
                field_of_study TEXT,
                external_resources TEXT,
                work_sessions INTEGER,
                time_spent_hours INTEGER,
                work_location TEXT,
                work_in_group BOOLEAN,
                submit_in_person BOOLEAN,
                email TEXT,
                FOREIGN KEY (email) REFERENCES students(email)
            );
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database tables initialized.")
    except Exception as e:
        print(f"❌ Error initializing DB: {e}")

def save_student_profile(survey, prefs):
    """Upserts student data (Insert or Update if email exists)."""
    conn = get_db_connection()
    if not conn: return

    try:
        cur = conn.cursor()
        # Updates user profile if they already exist (ON CONFLICT)
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
            survey.get('second_concentration'),
            survey.get('minor'),
            prefs.get('weekdayStart'),
            prefs.get('weekdayEnd'),
            prefs.get('weekendStart'),
            prefs.get('weekendEnd')
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"❌ Error saving profile: {e}")

def save_assignment(email, course_data, predicted_hours=0):
    """Inserts a single assignment linked to the student email."""
    conn = get_db_connection()
    if not conn: return

    try:
        # Map Frontend "Yes"/"No" to Boolean
        is_group = True if course_data.get('work_in_group') == "Yes" else False
        is_person = True if course_data.get('submitted_in_person') == "Yes" else False
        
        cur = conn.cursor()
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
            int(predicted_hours),  # Using the prediction result
            course_data.get('work_location'),
            is_group,
            is_person,
            email
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"❌ Error saving assignment: {e}")
