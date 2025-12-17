import pandas as pd
import json
import math
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event
import recurring_ical_events
from collections import defaultdict

# ==========================================================
# BLOCK 1 & 2: INPUT PARSER
# ==========================================================
def parse_request_inputs(json_data):
    # 1. TIMEZONE & WORK WINDOWS
    user_prefs = json_data.get("user_preferences", {})
    user_tz_str = user_prefs.get("timezone", "America/New_York") 
    try:
        local_tz = ZoneInfo(user_tz_str)
    except:
        local_tz = ZoneInfo("America/New_York")

    ww = user_prefs.get("work_windows", {})
    work_windows = {}

    # Defaults
    wd_start = float(ww.get("weekday_start_hour", 9))
    wd_end   = float(ww.get("weekday_end_hour", 21))
    we_start = float(ww.get("weekend_start_hour", 10))
    we_end   = float(ww.get("weekend_end_hour", 20))

    weekday_block = (wd_start, wd_end)
    weekend_block = (we_start, we_end)

    for wd in range(7):
        work_windows[wd] = [weekday_block] if wd <= 4 else [weekend_block]

    # 2. ASSIGNMENTS
    raw_assignments = json_data.get("assignments", [])
    
    if raw_assignments:
        df_assignments = pd.DataFrame(raw_assignments)
        
        # Standardize Columns
        column_map = {
            "id": "assignment_id",
            "name": "assignment_name",
            "due_date": "due_dates",
            "time_estimate": "time_spent_hours",
            "sessions_needed": "sessions_needed"
        }
        df_assignments.rename(columns=column_map, inplace=True)
        
        # Format Dates
        if "due_dates" in df_assignments.columns:
            df_assignments["due_dates"] = pd.to_datetime(df_assignments["due_dates"], format='mixed', errors='coerce')
            
            # --- FIX: FORCE TIMEZONE AWARENESS ---
            # 1. If date has no timezone (Naive), stamp it with the User's Local TZ
            # 2. If it already has one, convert it to the User's Local TZ
            if df_assignments["due_dates"].dt.tz is None:
                df_assignments["due_dates"] = df_assignments["due_dates"].dt.tz_localize(local_tz, ambiguous='NaT', nonexistent='shift_forward')
            else:
                df_assignments["due_dates"] = df_assignments["due_dates"].dt.tz_convert(local_tz)
            
            df_assignments = df_assignments.dropna(subset=['due_dates'])
        
        if "time_spent_hours" in df_assignments.columns:
            df_assignments["time_spent_hours"] = pd.to_numeric(df_assignments["time_spent_hours"])
        else:
            df_assignments["time_spent_hours"] = 2.0 

        if "sessions_needed" not in df_assignments.columns:
            df_assignments["sessions_needed"] = 1
        else:
            df_assignments["sessions_needed"] = pd.to_numeric(df_assignments["sessions_needed"], errors='coerce').fillna(1).astype(int)

        # Ensure fixed event flag exists for Exams
        if "is_fixed_event" not in df_assignments.columns:
            df_assignments["is_fixed_event"] = False

    else:
        df_assignments = pd.DataFrame()

    return local_tz, work_windows, df_assignments

# ==========================================================
# BLOCK 2: ICS PARSING (Busy Times)
# ==========================================================
def _to_local_dt(value, local_tz: ZoneInfo):
    if value is None: return None
    if isinstance(value, datetime):
        if value.tzinfo is None: return value.replace(tzinfo=local_tz)
        return value.astimezone(local_tz)
    return datetime.combine(value, time.min, tzinfo=local_tz)

def parse_ics_bytes(ics_content_bytes: bytes, local_tz: ZoneInfo, horizon_start: datetime, horizon_end: datetime) -> pd.DataFrame:
    columns = ["uid", "summary", "start", "end", "all_day"]
    try:
        cal = Calendar.from_ical(ics_content_bytes)
    except Exception as e:
        print(f"❌ ICS Parse Error: {e}")
        return pd.DataFrame(columns=columns)

    occurrences = recurring_ical_events.of(cal).between(horizon_start, horizon_end)
    records = []
    for comp in occurrences:
        dtstart_prop = comp.get("DTSTART")
        dtend_prop   = comp.get("DTEND")
        orig_start_raw = dtstart_prop.dt if dtstart_prop else None
        orig_end_raw   = dtend_prop.dt if dtend_prop else None
        all_day = not isinstance(orig_start_raw, datetime)

        start = _to_local_dt(orig_start_raw, local_tz)
        end   = _to_local_dt(orig_end_raw, local_tz) if orig_end_raw is not None else None

        if end is None:
            end = start + (timedelta(days=1) if all_day else timedelta(hours=1))

        if end <= start: continue

        records.append({
            "uid": str(comp.get("UID")),
            "summary": str(comp.get("SUMMARY")),
            "start": start,
            "end": end,
            "all_day": all_day
        })

    if not records: return pd.DataFrame(columns=columns)
    return pd.DataFrame(records).sort_values("start").reset_index(drop=True)

def merge_busy_blocks(blocks, join_touching=True):
    if not blocks: return []
    blocks = sorted(blocks, key=lambda x: x[0])
    merged = []
    cur_start, cur_end = blocks[0]
    for s, e in blocks[1:]:
        if (join_touching and s <= cur_end) or (not join_touching and s < cur_end):
            if e > cur_end: cur_end = e
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = s, e
    merged.append((cur_start, cur_end))
    return merged

def subtract_busy_from_window(window_start, window_end, busy_blocks):
    relevant = []
    for s, e in busy_blocks:
        if e <= window_start or s >= window_end: continue
        s_clipped = max(s, window_start)
        e_clipped = min(e, window_end)
        if s_clipped < e_clipped: relevant.append((s_clipped, e_clipped))
    relevant.sort(key=lambda x: x[0])
    free = []
    cur = window_start
    for s, e in relevant:
        if s > cur: free.append((cur, s))
        cur = max(cur, e)
    if cur < window_end: free.append((cur, window_end))
    return free

def add_buffer_to_busy_timeline(busy_timeline, buffer_minutes=15):
    delta = timedelta(minutes=buffer_minutes)
    buffered = [(s - delta, e + delta) for (s, e) in busy_timeline]
    return merge_busy_blocks(buffered, join_touching=True)

def build_free_blocks(WORK_WINDOWS, BUSY_TIMELINE, horizon_start, horizon_end, local_tz):
    FREE_BLOCKS = {}
    current_date = horizon_start.date()
    
    while current_date <= horizon_end.date():
        day_start_cal = datetime.combine(current_date, time.min).replace(tzinfo=local_tz)
        
        effective_start = max(day_start_cal, horizon_start)
        current_day_start = effective_start
        current_day_end = min(day_start_cal + timedelta(days=1), horizon_end)

        if current_day_start >= current_day_end:
            current_date += timedelta(days=1); continue

        weekday = current_date.weekday()
        day_work_windows = WORK_WINDOWS.get(weekday, [])

        day_busy = []
        for s, e in BUSY_TIMELINE:
            if e <= current_day_start or s >= current_day_end: continue
            s_clipped = max(s, current_day_start)
            e_clipped = min(e, current_day_end)
            if s_clipped < e_clipped: day_busy.append((s_clipped, e_clipped))
        day_busy.sort(key=lambda x: x[0])

        day_free = []
        for start_hour, end_hour in day_work_windows:
            w_start_cal = day_start_cal + timedelta(hours=float(start_hour))
            w_end_cal = day_start_cal + timedelta(hours=float(end_hour))
            w_actual_start = max(w_start_cal, current_day_start)
            w_actual_end = min(w_end_cal, current_day_end)
            if w_actual_start < w_actual_end:
                day_free.extend(subtract_busy_from_window(w_actual_start, w_actual_end, day_busy))

        FREE_BLOCKS[current_date] = day_free
        current_date += timedelta(days=1)
    return FREE_BLOCKS

# ==========================================================
# BLOCK 3: SESSION GENERATOR
# ==========================================================
def generate_sessions_from_assignments(df_assignments):
    sessions = []
    if df_assignments.empty: return sessions

    for _, row in df_assignments.iterrows():
        total_hours = row.get("time_spent_hours", 2.0)
        total_time_mins = total_hours * 60
        
        explicit_sessions = row.get("sessions_needed", 1)
        num_sessions = int(explicit_sessions)
        
        # Avoid division by zero
        num_sessions = max(1, num_sessions)

        base_duration = int(total_time_mins // num_sessions)
        remainder = int(total_time_mins % num_sessions)

        for i in range(num_sessions):
            dur = base_duration + (1 if i < remainder else 0)
            d_obj = row["due_dates"].date() if isinstance(row["due_dates"], datetime) else row["due_dates"]
            
            sessions.append({
                "assignment_id": row.get("assignment_id", f"task_{i}"),
                "assignment_name": row.get("assignment_name", "Study Task"),
                "class_name": row.get("class_name", "General"),
                "duration_minutes": dur,
                "due_date": d_obj, # This is the DEADLINE date
                "full_due_dt": row["due_dates"], # Keep full datetime for sorting
                "field_of_study": row.get("field_of_study", ""),
                "assignment_type": row.get("assignment_type", "")
            })
    # Sort by actual due time so we prioritize imminent tasks
    return sorted(sessions, key=lambda x: x["full_due_dt"])

# ==========================================================
# BLOCK 4: SCHEDULING ENGINE (The "Tetris" Player)
# ==========================================================
def schedule_sessions_load_balanced(free_blocks_map, sessions, 
                                    max_hours_per_day=8, 
                                    break_minutes=15,
                                    max_sessions_per_day=4):
    scheduled = []
    unscheduled = []
    daily_usage_minutes = defaultdict(float)
    daily_session_count = defaultdict(int)
    max_minutes = max_hours_per_day * 60
    break_duration = timedelta(minutes=break_minutes) 

    # Deep copy free blocks
    free_map = {k: v[:] for k, v in free_blocks_map.items()}
    sorted_dates = sorted(free_map.keys())

    for session in sessions:
        placed = False
        duration_mins = session["duration_minutes"]
        duration = timedelta(minutes=duration_mins)

        for d in sorted_dates:
            # Check Deadline
            if d > session["due_date"]: break
            
            # Check Daily Constraints
            if daily_usage_minutes[d] + duration_mins > max_minutes: continue
            if daily_session_count[d] >= max_sessions_per_day: continue

            day_blocks = free_map[d]
            for i, (start, end) in enumerate(day_blocks):
                
                # We need enough time for the Task + a Break
                block_duration = end - start
                
                if block_duration >= duration:
                    session_start = start
                    session_end = start + duration

                    # Add to Schedule
                    rec = session.copy()
                    rec["start"] = session_start
                    rec["end"] = session_end
                    rec["date"] = d
                    scheduled.append(rec)
                    
                    # Update Trackers
                    daily_usage_minutes[d] += duration_mins
                    daily_session_count[d] += 1

                    # Slice the Block (Task + Break)
                    new_start = session_end + break_duration 

                    if new_start < end:
                        free_map[d][i] = (new_start, end)
                    else:
                        free_map[d].pop(i)
                    
                    placed = True
                    break
            if placed: break

        if not placed:
            unscheduled.append(session)

    return scheduled, unscheduled

# ==========================================================
# BLOCK 5: OUTPUT GENERATOR
# ==========================================================
def create_output_ics(scheduled_tasks, output_path):
    cal = Calendar()
    cal.add('prodid', '-//StudentOS Scheduler//mxm.dk//')
    cal.add('version', '2.0')

    for task in scheduled_tasks:
        event = Event()
        start = task['start']
        end = task['end']
        
        if isinstance(start, str): start = datetime.fromisoformat(start)
        if isinstance(end, str): end = datetime.fromisoformat(end)

        # Different summary if it's an Exam vs Study Session
        if task.get('is_exam', False):
             event.add('summary', f"EXAM: {task['assignment_name']}")
        else:
             event.add('summary', f"Do: {task['assignment_name']}")
             
        event.add('dtstart', start)
        event.add('dtend', end)
        event.add('description', f"Course: {task.get('class_name','')}\nType: {task.get('assignment_type','')}")
        
        cal.add_component(event)

    with open(output_path, 'wb') as f:
        f.write(cal.to_ical())
    
    return output_path

# ==========================================================
# MAIN PROCESSOR (The Orchestrator)
# ==========================================================
def process_schedule_request(json_data, uploaded_files_bytes, output_folder):
    # 1. Parse Inputs
    local_tz, work_windows, df_assignments = parse_request_inputs(json_data)

    # 2. Determine Horizon
    today_dt = datetime.now(local_tz)
    horizon_start = datetime.combine(today_dt.date(), time.min).replace(tzinfo=local_tz)
    horizon_end = horizon_start + timedelta(days=30)
    
    if not df_assignments.empty and "due_dates" in df_assignments:
        max_due = df_assignments["due_dates"].max()
        horizon_end = max(horizon_end, max_due + timedelta(days=7))

    # 3. Handle Fixed Events (Exams) vs Floating Tasks
    fixed_tasks = []
    floating_df = pd.DataFrame()
    
    if not df_assignments.empty:
        # Split Dataframe
        fixed_mask = df_assignments["is_fixed_event"] == True
        fixed_df = df_assignments[fixed_mask]
        floating_df = df_assignments[~fixed_mask]
        
        # Process Fixed Events
        for _, row in fixed_df.iterrows():
            start_time = row["due_dates"]
            # Default to 1.25 hours for Exams
            dur = row.get("time_spent_hours", 1.25)
            end_time = start_time + timedelta(hours=dur)
            
            fixed_tasks.append({
                "assignment_name": row.get("assignment_name"),
                "class_name": row.get("class_name"),
                "assignment_type": row.get("assignment_type"),
                "start": start_time,
                "end": end_time,
                "is_exam": True # Flag for ICS generator
            })

    # 4. Calculate Busy Times (ICS Files + Fixed Exams)
    busy_blocks = []
    
    # A. User ICS Files
    for f_bytes in uploaded_files_bytes:
        ics_df = parse_ics_bytes(f_bytes, local_tz, horizon_start, horizon_end)
        for _, r in ics_df.iterrows():
            busy_blocks.append((r['start'], r['end']))
            
    # B. Add Fixed Exams to Busy Blocks (So we don't schedule study time over exams)
    for t in fixed_tasks:
        busy_blocks.append((t['start'], t['end']))

    # C. Buffer and Merge
    merged_busy = merge_busy_blocks(busy_blocks, join_touching=True)
    buffered_busy = add_buffer_to_busy_timeline(merged_busy, buffer_minutes=15)

    # 5. Calculate Free Blocks
    free_blocks = build_free_blocks(work_windows, buffered_busy, horizon_start, horizon_end, local_tz)

    # 6. Generate Sessions for Floating Tasks
    floating_sessions = generate_sessions_from_assignments(floating_df)

    # 7. Schedule Floating Tasks (Tetris Time)
    scheduled_floating, unscheduled = schedule_sessions_load_balanced(
        free_blocks, 
        floating_sessions, 
        max_hours_per_day=8,
        break_minutes=15,
        max_sessions_per_day=4
    )

    # 8. Combine All Tasks
    all_scheduled = fixed_tasks + scheduled_floating
    
    # 9. Generate ICS
    timestamp = int(datetime.now().timestamp())
    filename = f"optimized_schedule_{timestamp}.ics"
    output_path = os.path.join(output_folder, filename)
    
    create_output_ics(all_scheduled, output_path)

    return {
        "status": "success",
        "ics_filename": filename,
        "scheduled_count": len(all_scheduled),
        "unscheduled_count": len(unscheduled)
    }
