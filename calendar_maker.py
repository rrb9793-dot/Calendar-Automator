import pandas as pd
import json
import math
import os
import re
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event
import recurring_ical_events
from collections import defaultdict

# ==========================================================
# 🔧 DEMO SWITCH (TIME TRAVEL)
# ==========================================================
# Set this to a date string (e.g., "2025-09-01") to pretend it is that day.
# Set to None to use the actual real-world date.
DEMO_START_DATE = "2025-09-01" 
# DEMO_START_DATE = None 

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
        
        # Format Dates & FIX TIMEZONE CRASH
        if "due_dates" in df_assignments.columns:
            df_assignments["due_dates"] = pd.to_datetime(df_assignments["due_dates"], format='mixed', errors='coerce')
            
            # Force Timezone Awareness to match local_tz
            if not df_assignments.empty:
                if df_assignments["due_dates"].dt.tz is None:
                    df_assignments["due_dates"] = df_assignments["due_dates"].dt.tz_localize(local_tz, ambiguous='NaT', nonexistent='shift_forward')
                else:
                    df_assignments["due_dates"] = df_assignments["due_dates"].dt.tz_convert(local_tz)

            df_assignments = df_assignments.dropna(subset=['due_dates'])
        
        # Clean Numbers
        if "time_spent_hours" in df_assignments.columns:
            df_assignments["time_spent_hours"] = pd.to_numeric(df_assignments["time_spent_hours"], errors='coerce').fillna(2.0)
        else:
            df_assignments["time_spent_hours"] = 2.0 

        if "sessions_needed" not in df_assignments.columns:
            df_assignments["sessions_needed"] = 1
        else:
            df_assignments["sessions_needed"] = pd.to_numeric(df_assignments["sessions_needed"], errors='coerce').fillna(1).astype(int)

        if "is_fixed_event" not in df_assignments.columns:
            df_assignments["is_fixed_event"] = False
            
        # Ensure class_name exists
        if "class_name" not in df_assignments.columns:
            df_assignments["class_name"] = "General"

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

def build_free_blocks(WORK_WINDOWS, BUSY_TIMELINE, horizon_start, horizon_end, local_tz, current_simulated_dt):
    """
    Constructs free time blocks.
    Uses 'current_simulated_dt' instead of real 'now' to allow time travel.
    """
    FREE_BLOCKS = {}
    current_date = horizon_start.date()
    
    # Use the passed-in "Now" (which might be the demo date)
    now = current_simulated_dt
    
    while current_date <= horizon_end.date():
        day_start_cal = datetime.combine(current_date, time.min).replace(tzinfo=local_tz)
        effective_start = max(day_start_cal, horizon_start)
        
        # Clip to "Now" if we are on the starting day
        if current_date == now.date():
             effective_start = max(effective_start, now)
        
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
# BLOCK 3: SESSION GENERATOR (WITH CATCH-UP LOGIC)
# ==========================================================
def extract_class_from_title(title):
    match = re.search(r'\((.*?)\)', title)
    if match:
        return match.group(1).strip()
    return "General"

def generate_sessions_from_assignments(df_assignments, current_date):
    """
    Handles assignments. 
    If an assignment is OVERDUE, it gives it a fake deadline of 
    'Today + 7 Days' to allow the spacer to work.
    """
    sessions = []
    if df_assignments.empty: return sessions

    for _, row in df_assignments.iterrows():
        total_hours = row.get("time_spent_hours", 2.0)
        total_time_mins = total_hours * 60
        explicit_sessions = row.get("sessions_needed", 1)
        num_sessions = max(1, int(explicit_sessions))

        base_duration = int(total_time_mins // num_sessions)
        remainder = int(total_time_mins % num_sessions)
        
        original_due = row["due_dates"].date() if isinstance(row["due_dates"], datetime) else row["due_dates"]
        is_overdue = original_due < current_date
        
        # --- CATCH-UP LOGIC ---
        if is_overdue:
            effective_due = current_date + timedelta(days=7)
        else:
            effective_due = max(original_due, current_date)
        # ----------------------

        c_name = row.get("class_name", "General")
        a_name = row.get("assignment_name", "Study Task")
        if c_name == "General":
             c_name = extract_class_from_title(a_name)

        for i in range(num_sessions):
            dur = base_duration + (1 if i < remainder else 0)
            sessions.append({
                "assignment_id": row.get("assignment_id", f"task_{i}"),
                "assignment_name": a_name,
                "class_name": c_name,
                "duration_minutes": dur,
                "due_date": effective_due, 
                "full_due_dt": row["due_dates"], 
                "is_overdue": is_overdue, 
                "field_of_study": row.get("field_of_study", ""),
                "assignment_type": row.get("assignment_type", "")
            })

    return sorted(sessions, key=lambda x: (x["is_overdue"], x["full_due_dt"]))

# ==========================================================
# BLOCK 4: SCHEDULING ENGINE (CLASS-BASED SPACING)
# ==========================================================
def schedule_sessions_load_balanced(free_blocks_map, sessions, 
                                    max_hours_per_day, 
                                    break_minutes=15,
                                    daily_usage_tracker=None,
                                    daily_class_tracker=None,
                                    enforce_spacing=False):
    scheduled = []
    unscheduled = []
    
    if daily_usage_tracker is None: daily_usage_minutes = defaultdict(float)
    else: daily_usage_minutes = daily_usage_tracker

    if daily_class_tracker is None: daily_class_tracker = defaultdict(set)

    max_minutes = max_hours_per_day * 60
    break_duration = timedelta(minutes=break_minutes) 
    sorted_dates = sorted(free_blocks_map.keys())

    for session in sessions:
        placed = False
        duration_mins = session["duration_minutes"]
        duration = timedelta(minutes=duration_mins)
        s_class = session["class_name"] 

        for d in sorted_dates:
            if d > session["due_date"]: break
            
            # 1. CHECK HOURS
            if daily_usage_minutes[d] + duration_mins > max_minutes: continue

            # 2. CHECK SPACING (Subject-Based)
            if enforce_spacing:
                if s_class in daily_class_tracker[d] and s_class != "General":
                    continue

            day_blocks = free_blocks_map[d]
            for i, (start, end) in enumerate(day_blocks):
                block_duration = end - start
                
                if block_duration >= duration:
                    session_start = start
                    session_end = start + duration

                    rec = session.copy()
                    rec["start"] = session_start
                    rec["end"] = session_end
                    rec["date"] = d
                    scheduled.append(rec)
                    
                    daily_usage_minutes[d] += duration_mins
                    daily_class_tracker[d].add(s_class) 
                    
                    new_start = session_end + break_duration 
                    if new_start < end:
                        free_blocks_map[d][i] = (new_start, end)
                    else:
                        free_blocks_map[d].pop(i)
                    
                    placed = True
                    break
            if placed: break

        if not placed:
            unscheduled.append(session)

    return scheduled, unscheduled

# ==========================================================
# BLOCK 4.5: MERGE BLOCKS
# ==========================================================
def merge_contiguous_sessions(scheduled_sessions):
    if not scheduled_sessions: return []
    sorted_sessions = sorted(scheduled_sessions, key=lambda x: x["start"])
    merged = []
    current_block = sorted_sessions[0]

    for next_block in sorted_sessions[1:]:
        same_assignment = (current_block["assignment_name"] == next_block["assignment_name"])
        touching_time = (current_block["end"] == next_block["start"])
        
        if same_assignment and touching_time:
            current_block["end"] = next_block["end"]
            current_block["duration_minutes"] += next_block["duration_minutes"]
        else:
            merged.append(current_block)
            current_block = next_block

    merged.append(current_block)
    return merged

# ==========================================================
# BLOCK 5: OUTPUT & MAIN
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

        # --- DEADLINE FORMATTING ---
        deadline_dt = task.get('full_due_dt')
        deadline_str = "Unknown"
        if deadline_dt:
             if isinstance(deadline_dt, str):
                 deadline_str = deadline_dt
             elif isinstance(deadline_dt, datetime):
                 deadline_str = deadline_dt.strftime("%Y-%m-%d %H:%M")
             else:
                 deadline_str = str(deadline_dt)
        # ---------------------------

        summary_prefix = "EXAM: " if task.get('is_exam') else "Do: "
        event.add('summary', f"{summary_prefix}{task['assignment_name']}")
        event.add('dtstart', start)
        event.add('dtend', end)
        
        # --- ENRICHED DESCRIPTION ---
        description = (
            f"Class: {task.get('class_name', 'General')}\n"
            f"Deadline: {deadline_str}\n"
            f"Type: {task.get('assignment_type', 'Task')}"
        )
        event.add('description', description)
        # ----------------------------

        cal.add_component(event)

    with open(output_path, 'wb') as f:
        f.write(cal.to_ical())
    return output_path

def process_schedule_request(json_data, uploaded_files_bytes, output_folder):
    local_tz, work_windows, df_assignments = parse_request_inputs(json_data)

    # ==========================================
    # ⏳ TIME TRAVEL LOGIC
    # ==========================================
    if DEMO_START_DATE:
        print(f"🔮 DEMO MODE: Time traveling to {DEMO_START_DATE}")
        # Parse the demo date
        demo_dt = datetime.fromisoformat(DEMO_START_DATE)
        # Combine with current time of day to make it realistic, or set to morning
        today_dt = datetime.combine(demo_dt.date(), datetime.now().time()).replace(tzinfo=local_tz)
    else:
        today_dt = datetime.now(local_tz)
    # ==========================================

    horizon_start = datetime.combine(today_dt.date(), time.min).replace(tzinfo=local_tz)
    horizon_end = horizon_start + timedelta(days=30)
    
    if not df_assignments.empty and "due_dates" in df_assignments:
        max_due = df_assignments["due_dates"].max()
        horizon_end = max(horizon_end, max_due + timedelta(days=14))

    fixed_tasks = []
    floating_df = pd.DataFrame()
    
    if not df_assignments.empty:
        fixed_mask = df_assignments["is_fixed_event"] == True
        fixed_df = df_assignments[fixed_mask]
        floating_df = df_assignments[~fixed_mask]
        
        for _, row in fixed_df.iterrows():
            start_time = row["due_dates"]
            dur = row.get("time_spent_hours", 1.25)
            end_time = start_time + timedelta(hours=dur)
            fixed_tasks.append({
                "assignment_name": row.get("assignment_name"),
                "class_name": row.get("class_name", "General"),
                "assignment_type": row.get("assignment_type"),
                "start": start_time,
                "end": end_time,
                "duration_minutes": dur * 60,
                "is_exam": True
            })

    busy_blocks = []
    for f_bytes in uploaded_files_bytes:
        ics_df = parse_ics_bytes(f_bytes, local_tz, horizon_start, horizon_end)
        for _, r in ics_df.iterrows():
            busy_blocks.append((r['start'], r['end']))
    for t in fixed_tasks:
        busy_blocks.append((t['start'], t['end']))

    merged_busy = merge_busy_blocks(busy_blocks, join_touching=True)
    buffered_busy = add_buffer_to_busy_timeline(merged_busy, buffer_minutes=15)
    
    # PASS THE SIMULATED DATE HERE
    free_blocks = build_free_blocks(work_windows, buffered_busy, horizon_start, horizon_end, local_tz, today_dt)
    
    floating_sessions = generate_sessions_from_assignments(floating_df, today_dt.date())

    # =========================================================================
    # TWO-PASS LOGIC (Class-Based Spacing + Catch-Up)
    # =========================================================================
    daily_usage_tracker = defaultdict(float)
    daily_class_tracker = defaultdict(set)

    # PHASE 1: Healthy (8h) + Enforce Class Spacing
    scheduled_p1, unscheduled_p1 = schedule_sessions_load_balanced(
        free_blocks, 
        floating_sessions, 
        max_hours_per_day=8,      
        break_minutes=15,
        daily_usage_tracker=daily_usage_tracker,
        daily_class_tracker=daily_class_tracker,
        enforce_spacing=True 
    )

    # PHASE 2: Failsafe (Crunch)
    if unscheduled_p1:
        print(f"⚠️ FAILSAFE: {len(unscheduled_p1)} tasks must be stacked.")
        scheduled_p2, unscheduled_final = schedule_sessions_load_balanced(
            free_blocks,            
            unscheduled_p1,         
            max_hours_per_day=24,
            break_minutes=15,
            daily_usage_tracker=daily_usage_tracker,
            daily_class_tracker=daily_class_tracker,
            enforce_spacing=False
        )
    else:
        scheduled_p2 = []
        unscheduled_final = []

    all_scheduled = fixed_tasks + scheduled_p1 + scheduled_p2
    final_optimized = merge_contiguous_sessions(all_scheduled)
    
    timestamp = int(datetime.now().timestamp())
    filename = f"optimized_schedule_{timestamp}.ics"
    output_path = os.path.join(output_folder, filename)
    create_output_ics(final_optimized, output_path)

    return {
        "status": "success",
        "ics_filename": filename,
        "scheduled_count": len(all_scheduled),
        "unscheduled_count": len(unscheduled_final)
    }
