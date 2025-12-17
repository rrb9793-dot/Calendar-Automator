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
        
        if "due_dates" in df_assignments.columns:
            df_assignments["due_dates"] = pd.to_datetime(df_assignments["due_dates"], format='mixed', errors='coerce')
            df_assignments = df_assignments.dropna(subset=['due_dates'])
        
        if "time_spent_hours" in df_assignments.columns:
            df_assignments["time_spent_hours"] = pd.to_numeric(df_assignments["time_spent_hours"])
        else:
            df_assignments["time_spent_hours"] = 2.0 

        # Ensure is_fixed_event exists (New for Exam Logic)
        if "is_fixed_event" not in df_assignments.columns:
            df_assignments["is_fixed_event"] = False

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

def parse_ics_bytes(ics_content_bytes, local_tz, horizon_start, horizon_end):
    columns = ["uid", "summary", "start", "end", "all_day"]
    try:
        cal = Calendar.from_ical(ics_content_bytes)
    except:
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

def merge_busy_blocks(blocks):
    """Merges overlapping or adjacent time blocks."""
    if not blocks: return []
    blocks = sorted(blocks, key=lambda x: x[0])
    merged = []
    cur_start, cur_end = blocks[0]
    for s, e in blocks[1:]:
        if s <= cur_end:
            if e > cur_end: cur_end = e
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = s, e
    merged.append((cur_start, cur_end))
    return merged

def subtract_busy_from_window(window_start, window_end, busy_blocks):
    """Subtracts busy blocks from a work window to find free time."""
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

def build_free_blocks(work_windows, busy_timeline, horizon_start, horizon_end, local_tz):
    free_blocks = {}
    current_date = horizon_start.date()
    
    while current_date <= horizon_end.date():
        day_start = datetime.combine(current_date, time.min).replace(tzinfo=local_tz)
        day_end = day_start + timedelta(days=1)
        
        wd = current_date.weekday()
        day_work_windows = work_windows.get(wd, [])
        
        day_free = []
        for start_hour, end_hour in day_work_windows:
            w_start = day_start + timedelta(hours=float(start_hour))
            w_end = day_start + timedelta(hours=float(end_hour))
            
            # Clip to horizon
            if w_end <= horizon_start: continue
            w_start = max(w_start, horizon_start)
            w_end = min(w_end, horizon_end)
            
            if w_start < w_end:
                day_free.extend(subtract_busy_from_window(w_start, w_end, busy_timeline))
            
        free_blocks[current_date] = day_free
        current_date += timedelta(days=1)
    
    return free_blocks

# ==========================================================
# BLOCK 4: ENGINE (UPDATED FOR FIXED EXAMS)
# ==========================================================
def process_schedule_request(json_data, uploaded_files_bytes, output_folder):
    # 1. Parse Inputs
    local_tz, work_windows, df = parse_request_inputs(json_data)
    
    scheduled_tasks = []
    unscheduled_tasks = []
    
    # 2. Horizon
    today = datetime.now(local_tz)
    horizon_start = today
    horizon_end = today + timedelta(days=30)
    if not df.empty and "due_dates" in df.columns:
        max_due = df["due_dates"].max()
        horizon_end = max(horizon_end, max_due + timedelta(days=7))

    busy_blocks = []
    
    # A. Load ICS Busy Times
    for f_bytes in uploaded_files_bytes:
        ics_df = parse_ics_bytes(f_bytes, local_tz, horizon_start, horizon_end)
        for _, r in ics_df.iterrows():
            busy_blocks.append((r['start'], r['end']))

    # B. Handle Fixed Exams (They act as BUSY BLOCKS and SCHEDULED ITEMS)
    floating_tasks_df = pd.DataFrame()
    
    if not df.empty:
        # Split dataframe
        fixed_mask = df["is_fixed_event"] == True
        fixed_df = df[fixed_mask]
        floating_tasks_df = df[~fixed_mask]
        
        # Process Fixed Events (Exams)
        for _, row in fixed_df.iterrows():
            start_time = row["due_dates"]
            # Exams use their specific time estimate (1.25h), default to 1h if missing
            duration_h = row.get("time_spent_hours", 1.0) 
            end_time = start_time + timedelta(hours=duration_h)
            
            # 1. Add to Busy List (So we don't study during the exam)
            busy_blocks.append((start_time, end_time))
            
            # 2. Add to Final Schedule
            scheduled_tasks.append({
                "assignment_id": row.get("assignment_id"),
                "assignment_name": row.get("assignment_name"),
                "class_name": row.get("class_name"),
                "assignment_type": row.get("assignment_type"),
                "start": start_time,
                "end": end_time
            })

    # 3. Calculate Free Time (Now excluding Exam times)
    # Merge overlapping busy blocks + add buffer
    busy_merged = merge_busy_blocks(busy_blocks)
    
    # Add 15min buffer around busy blocks
    buffer = timedelta(minutes=15)
    buffered_busy = [(s-buffer, e+buffer) for s, e in busy_merged]
    
    free_blocks = build_free_blocks(work_windows, merge_busy_blocks(buffered_busy), horizon_start, horizon_end, local_tz)

    # 4. Schedule Floating Tasks
    sessions_to_schedule = []
    if not floating_tasks_df.empty:
        # Break tasks into sessions
        for _, row in floating_tasks_df.iterrows():
            total_time = row.get("time_spent_hours", 2.0) * 60
            n_sessions = int(row.get("sessions_needed", 1))
            
            # Avoid divide by zero
            n_sessions = max(1, n_sessions)
            session_dur = int(total_time / n_sessions)
            
            for i in range(n_sessions):
                sessions_to_schedule.append({
                    "assignment_id": row.get("assignment_id"),
                    "assignment_name": row.get("assignment_name"),
                    "class_name": row.get("class_name"),
                    "assignment_type": row.get("assignment_type"),
                    "due_date": row["due_dates"],
                    "duration_minutes": session_dur
                })
        
        # Sort by due date
        sessions_to_schedule.sort(key=lambda x: x["due_date"])

        # Run "Tetris" Logic
        daily_mins = defaultdict(int)
        MAX_DAILY_MINS = 8 * 60
        
        # Deep copy free blocks
        available = {k: v[:] for k, v in free_blocks.items()}
        sorted_days = sorted(available.keys())
        
        for sess in sessions_to_schedule:
            placed = False
            dur = timedelta(minutes=sess["duration_minutes"])
            
            for day in sorted_days:
                if day > sess["due_date"].date(): break # Can't do after due date
                if daily_mins[day] + sess["duration_minutes"] > MAX_DAILY_MINS: continue
                
                day_slots = available[day]
                for i, (s, e) in enumerate(day_slots):
                    if (e - s) >= dur:
                        # Schedule it!
                        scheduled_tasks.append({
                            "assignment_name": sess["assignment_name"],
                            "class_name": sess["class_name"],
                            "assignment_type": sess["assignment_type"],
                            "start": s,
                            "end": s + dur
                        })
                        
                        # Update trackers
                        daily_mins[day] += sess["duration_minutes"]
                        placed = True
                        
                        # Slice the block
                        new_start = s + dur + timedelta(minutes=15) # Add break
                        if new_start < e:
                            available[day][i] = (new_start, e)
                        else:
                            available[day].pop(i)
                        break
                if placed: break
            
            if not placed:
                unscheduled_tasks.append(sess)

    # 5. Output ICS
    timestamp = int(datetime.now().timestamp())
    filename = f"optimized_schedule_{timestamp}.ics"
    out_path = os.path.join(output_folder, filename)
    
    cal = Calendar()
    cal.add('prodid', '-//StudentOS Scheduler//mxm.dk//')
    cal.add('version', '2.0')

    for t in scheduled_tasks:
        e = Event()
        e.add('summary', f"Do: {t['assignment_name']}")
        e.add('dtstart', t['start'])
        e.add('dtend', t['end'])
        desc = f"Class: {t.get('class_name','')}\nType: {t.get('assignment_type','')}"
        e.add('description', desc)
        cal.add_component(e)
        
    with open(out_path, 'wb') as f:
        f.write(cal.to_ical())

    return {
        "status": "success",
        "ics_filename": filename,
        "scheduled_count": len(scheduled_tasks),
        "unscheduled_count": len(unscheduled_tasks)
    }
