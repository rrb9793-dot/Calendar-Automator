import os
import psycopg2

# --- DATABASE CONFIGURATION ---
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    try:
        if not DATABASE_URL:
            print("❌ CRITICAL ERROR: DATABASE_URL is missing! Check Railway Variables.")
            return None
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"❌ DATABASE CONNECTION FAILED: {e}")
        return None

# --- FETCH USER PREFERENCES (FOR AUTOFILL) ---
def get_user_preferences(email):
    """Fetches a user's saved settings to autofill the frontend."""
    conn = get_db_connection()
    if not conn: return None
    try:
        cur = conn.cursor()
        # UPDATED: Case-insensitive search
        query = """
            SELECT year, timezone, major, second_concentration, minor,
                   weekday_start_hour, weekday_end_hour, weekend_start_hour, weekend_end_hour
            FROM user_preferences
            WHERE LOWER(email) = LOWER(%s);
        """
        cur.execute(query, (email.strip(),))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            # Return as a dictionary so the frontend can use it
            return {
                "year": row[0],
                "timezone": row[1],
                "major": row[2],
                "second_concentration": row[3],
                "minor": row[4],
                "weekdayStart": row[5],
                "weekdayEnd": row[6],
                "weekendStart": row[7],
                "weekendEnd": row[8]
            }
        return None
    except Exception as e:
        print(f"❌ Error fetching preferences: {e}")
        return None

# --- SAVE USER PREFERENCES ---
def save_user_preferences(survey, prefs):
    """Saves student info to the 'user_preferences' table."""
    conn = get_db_connection()
    if not conn: return

    try:
        cur = conn.cursor()
        print(f"📝 Saving Preferences for: {survey.get('email')}")

        # Using 'second_concentration' (underscore) to match your DB schema
        query = """
            INSERT INTO user_preferences (
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
        print(f"✅ User Preferences Saved: {survey.get('email')}")
        cur.close()
        conn.close()

    except Exception as e:
        print(f"❌ ERROR SAVING PREFERENCES: {e}")
        if conn: conn.rollback()

# --- SAVE ASSIGNMENT ---
def save_assignment(email, course_data, predicted_hours=0):
    """Saves a single assignment to the 'assignments' table."""
    conn = get_db_connection()
    if not conn: return

    try:
        cur = conn.cursor()
        
        # Convert "Yes"/"No" to Boolean for Postgres
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
