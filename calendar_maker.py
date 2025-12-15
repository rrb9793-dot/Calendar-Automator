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
        
        # --- FIX APPLIED HERE ---
        # Added format='mixed' to handle "11:59 PM" and other formats gracefully
        if "due_dates" in df_assignments.columns:
            df_assignments["due_dates"] = pd.to_datetime(df_assignments["due_dates"], format='mixed', errors='coerce')
            # Drop any rows where the date couldn't be parsed (NaT)
            df_assignments = df_assignments.dropna(subset=['due_dates'])
        
        if "time_spent_hours" in df_assignments.columns:
            df_assignments["time_spent_hours"] = pd.to_numeric(df_assignments["time_spent_hours"])
        else:
            df_assignments["time_spent_hours"] = 2.0 

        if "sessions_needed" not in df_assignments.columns:
            df_assignments["sessions_needed"] = 1
        else:
            df_assignments["sessions_needed"] = pd.to_numeric(df_assignments["sessions_needed"], errors='coerce').fillna(1).astype(int)

    else:
        df_assignments = pd.DataFrame()

    return local_tz, work_windows, df_assignments

# ==========================================================
# BLOCK 3: ICS PARSING (Busy Times)
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

def clip_blocks_to_horizon(blocks, horizon_start, horizon_end):
    clipped = []
    for start, end in blocks:
        if end <= horizon_start or start >= horizon_end: continue
        s = max(start, horizon_start)
        e = min(end, horizon_end)
        if s < e: clipped.append((s, e))
    return clipped

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
    now = datetime.now(local_tz)

    while current_date <= horizon_end.date():
        day_start_cal = datetime.combine(current_date, time.min).replace(tzinfo=local_tz)
        day_end_cal = day_start_cal + timedelta(days=1)

        effective_start = max(day_start_cal, horizon_start)
        if current_date == now.date():
            effective_start = max(effective_start, now)

        current_day_start = effective_start
        current_day_end = min(day_end_cal, horizon_end)

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
# BLOCK 4: ENGINE
# ==========================================================
def generate_free_blocks_engine(local_tz, work_windows, df_assignments, uploaded_files_bytes):
    # 1. HORIZON
    today_dt = datetime.now(local_tz)
    if not df_assignments.empty and "due_dates" in df_assignments:
        min_due = df_assignments["due_dates"].min().date()
        max_due = df_assignments["due_dates"].max().date()
        start_date = min(today_dt.date(), min_due)
        end_date = max_due + timedelta(days=7)
    else:
        start_date = today_dt.date()
        end_date = start_date + timedelta(days=30)

    horizon_start = datetime.combine(start_date, time.min).replace(tzinfo=local_tz)
    horizon_end   = datetime.combine(end_date, time.min).replace(tzinfo=local_tz) + timedelta(days=1)

    # 2. PROCESS ICS
    all_events = []
    for f_bytes in uploaded_files_bytes:
        df = parse_ics_bytes(f_bytes, local_tz, horizon_start, horizon_end)
        all_events.append(df)

    if all_events and any(not df.empty for df in all_events):
        df_events = pd.concat([df for df in all_events if not df.empty], ignore_index=True)
        busy_blocks = list(zip(df_events["start"], df_events["end"]))
    else:
        busy_blocks = []

    busy_clipped = clip_blocks_to_horizon(busy_blocks, horizon_start, horizon_end)
    busy_timeline = merge_busy_blocks(busy_clipped, join_touching=True)
    buffered_busy = add_buffer_to_busy_timeline(busy_timeline, 30)

    return build_free_blocks(work_windows, buffered_busy, horizon_start, horizon_end, local_tz)

def generate_sessions_from_assignments(df_assignments, default_session_minutes=60):
    sessions = []
    if df_assignments.empty: return sessions

    for _, row in df_assignments.iterrows():
        total_hours = row.get("time_spent_hours", 2.0)
        total_time_mins = total_hours * 60
        
        # --- LOGIC UPDATED TO RESPECT 'work sessions' INPUT ---
        explicit_sessions = row.get("sessions_needed", 1)
        if explicit_sessions > 1:
            num_sessions = int(explicit_sessions)
        else:
            # Fallback to pure time-based calc if they said 1 session or didn't specify
            # But if total time is huge, force split
            num_sessions = math.ceil(total_time_mins / default_session_minutes)
        
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
                "due_date": d_obj,
                "field_of_study": row.get("field_of_study", ""),
                "assignment_type": row.get("assignment_type", "")
            })
    return sorted(sessions, key=lambda x: x["due_date"])

def schedule_sessions_load_balanced(free_blocks_map, sessions, 
                                    max_hours_per_day=24, 
                                    break_minutes=15,
                                    max_sessions_per_day=4): # <-- NEW PARAMETER
    scheduled = []
    unscheduled = []
    daily_usage_minutes = defaultdict(float)
    daily_session_count = defaultdict(int) # <-- NEW TRACKER
    max_minutes = max_hours_per_day * 60
    break_duration = timedelta(minutes=break_minutes) 

    # Create a deep copy of free blocks to modify
    free_map = {k: v[:] for k, v in free_blocks_map.items()}
    sorted_dates = sorted(free_map.keys())

    for session in sessions:
        placed = False
        duration_mins = session["duration_minutes"]
        duration = timedelta(minutes=duration_mins)

        for d in sorted_dates:
            # 1. Check Due Date, Daily Time Limit, and DAILY SESSION LIMIT <-- MODIFIED CHECK
            if d > session["due_date"]: 
                break
            if daily_usage_minutes[d] + duration_mins > max_minutes: 
                continue
            if daily_session_count[d] >= max_sessions_per_day: # <-- NEW CONSTRAINT
                continue

            day_blocks = free_map[d]
            for i, (start, end) in enumerate(day_blocks):
                
                # Required duration includes the session time PLUS the post-session break
                required_block_duration = duration + break_duration
                block_duration = end - start
                
                if block_duration >= required_block_duration:
                    session_start = start
                    session_end = start + duration

                    # 2. Schedule the Session
                    rec = session.copy()
                    rec["start"] = session_start
                    rec["end"] = session_end
                    rec["date"] = d
                    scheduled.append(rec)
                    
                    # 3. Update Daily Trackers
                    daily_usage_minutes[d] += duration_mins
                    daily_session_count[d] += 1 # <-- INCREMENT COUNTER

                    # 4. Calculate New Free Block Start (Includes Break)
                    new_start = session_end + break_duration 

                    if new_start < end:
                        # The block has remaining time after the session and break
                        free_map[d][i] = (new_start, end)
                    else:
                        # The session and break consumed the entire block
                        free_map[d].pop(i)
                    
                    placed = True
                    break
                    
            if placed: 
                break

        if not placed:
            unscheduled.append(session)

    return scheduled, unscheduled
# def schedule_sessions_load_balanced(free_blocks_map, sessions, max_hours_per_day=24):
#     scheduled = []
#     unscheduled = []
#     daily_usage_minutes = defaultdict(float)
#     max_minutes = max_hours_per_day * 60

#     free_map = {k: v[:] for k, v in free_blocks_map.items()}
#     sorted_dates = sorted(free_map.keys())

#     for session in sessions:
#         placed = False
#         duration_mins = session["duration_minutes"]
#         duration = timedelta(minutes=duration_mins)

#         for d in sorted_dates:
#             if d > session["due_date"]: break
#             if daily_usage_minutes[d] + duration_mins > max_minutes: continue

#             day_blocks = free_map[d]
#             for i, (start, end) in enumerate(day_blocks):
#                 block_duration = end - start
#                 if block_duration >= duration:
#                     session_start = start
#                     session_end = start + duration

#                     rec = session.copy()
#                     rec["start"] = session_start
#                     rec["end"] = session_end
#                     rec["date"] = d
#                     scheduled.append(rec)
                    
#                     daily_usage_minutes[d] += duration_mins

#                     new_start = session_end
#                     if new_start < end:
#                         free_map[d][i] = (new_start, end)
#                     else:
#                         free_map[d].pop(i)
#                     placed = True
#                     break
#             if placed: break

#         if not placed:
#             unscheduled.append(session)

#     return scheduled, unscheduled

# ==========================================================
# BLOCK 6: OUTPUT GENERATOR
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

        event.add('summary', f"Study: {task['assignment_name']}")
        event.add('dtstart', start)
        event.add('dtend', end)
        event.add('description', f"Course: {task.get('class_name','')}\nType: {task.get('assignment_type','')}")
        
        cal.add_component(event)

    with open(output_path, 'wb') as f:
        f.write(cal.to_ical())
    
    return output_path

# ==========================================================
# MAIN PROCESSOR
# ==========================================================
def process_schedule_request(json_data, uploaded_files_bytes, output_folder):
    # 1. Parse Inputs
    local_tz, work_windows, df_assignments = parse_request_inputs(json_data)

    # 2. Calculate Free Time
    free_blocks = generate_free_blocks_engine(local_tz, work_windows, df_assignments, uploaded_files_bytes)

    # 3. Create Session Chunks
    all_sessions = generate_sessions_from_assignments(df_assignments)
    
    # Set your desired limits here, added this 
    MAX_DAILY_HOURS = 8
    BREAK_MINUTES = 15
    MAX_DAILY_SESSIONS = 3 
     # 4. Schedule
    scheduled, unscheduled = schedule_sessions_load_balanced(
        free_blocks, 
        all_sessions, 
        max_hours_per_day=MAX_DAILY_HOURS,
        break_minutes=BREAK_MINUTES,
        max_sessions_per_day=MAX_DAILY_SESSIONS
    )
    #scheduled, unscheduled = schedule_sessions_load_balanced(free_blocks, all_sessions)

    # 5. Generate ICS File
    timestamp = int(datetime.now().timestamp())
    filename = f"optimized_schedule_{timestamp}.ics"
    output_path = os.path.join(output_folder, filename)
    
    create_output_ics(scheduled, output_path)

    return {
        "status": "success",
        "ics_filename": filename,
        "scheduled_count": len(scheduled),
        "unscheduled_count": len(unscheduled)
    }
