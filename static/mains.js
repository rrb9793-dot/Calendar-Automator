// --- CONFIGURATION ---
const MAJORS = ["Business", "Tech & Data Science", "Engineering", "Math", "Natural Sciences", "Social Sciences", "Arts & Humanities", "Health & Education"];
const ASSIGNMENT_TYPES = ["Problem Set", "Coding Assignment", "Research Paper", "Creative Writing/Essay", "Presentation", "Modeling", "Discussion Post", "Readings", "Case Study"];
const RESOURCES = ["Textbook / class materials", "AI / Chatgpt", "Google/internet"];
const LOCATIONS = ["At home/private setting", "School/library", "Other public setting (cafe, etc.)"];

document.addEventListener('DOMContentLoaded', () => {
    const opts = (id, arr, na) => {
        const s = document.getElementById(id); s.innerHTML = '';
        if(na) s.add(new Option("N/A", "N/A")); else s.add(new Option("-- Select --", ""));
        arr.forEach(x => s.add(new Option(x, x)));
    };
    // Initialize Dropdowns
    opts('major', MAJORS); 
    opts('second_concentration', MAJORS, true); 
    opts('minor', MAJORS, true);
    
    initTimePickers();
    addAssignmentRow();
    addPdfRow();

    document.getElementById('addAssignmentBtn').onclick = addAssignmentRow;
    document.getElementById('addPdfBtn').onclick = addPdfRow;
    document.getElementById('submitBtn').onclick = handleSubmit;
    
    // --- AUTOFILL LISTENER (The Fix) ---
    const em = document.getElementById('email');
    if(em) {
        em.addEventListener('blur', async () => {
            if(!em.value.includes('@')) return;
            em.style.opacity = "0.5"; // Visual feedback
            try {
                const r = await fetch(`/api/get-user-preferences?email=${encodeURIComponent(em.value)}`);
                if(r.ok) {
                    const d = await r.json();
                    console.log("Found User Data:", d); // Debugging

                    // 1. Simple Fields
                    if(d.year) document.getElementById('studentYear').value = d.year;
                    if(d.timezone) document.getElementById('timezone').value = d.timezone;
                    if(d.major) document.getElementById('major').value = d.major;
                    if(d.second_concentration) document.getElementById('second_concentration').value = d.second_concentration;
                    if(d.minor) document.getElementById('minor').value = d.minor;

                    // 2. Complex Time Pickers
                    setPickerValue('weekdayStart', d.weekdayStart);
                    setPickerValue('weekdayEnd', d.weekdayEnd);
                    setPickerValue('weekendStart', d.weekendStart);
                    setPickerValue('weekendEnd', d.weekendEnd);
                }
            } catch(e) { 
                console.error("Autofill Error:", e); 
            } finally { 
                em.style.opacity = "1"; 
            }
        });
    }
});

// --- HELPER: Set Time Picker Value ---
function setPickerValue(id, timeStr) {
    if (!timeStr) return;
    const parts = timeStr.split(':'); // e.g., "09:00" -> ["09", "00"]
    if (parts.length < 2) return;

    const container = document.getElementById(id);
    const selects = container.querySelectorAll('select');
    if (selects.length === 2) {
        selects[0].value = parts[0]; // Set Hour
        selects[1].value = parts[1]; // Set Minute
    }
}

// --- STANDARD INIT FUNCTIONS ---
function initTimePickers() {
    document.querySelectorAll('.time-picker').forEach(d => {
        if(d.children.length) return;
        const h = document.createElement('select'), m = document.createElement('select');
        for(let i=0;i<24;i++) h.add(new Option(i<10?'0'+i:i, i<10?'0'+i:i));
        for(let i=0;i<60;i+=15) m.add(new Option(i<10?'0'+i:i, i<10?'0'+i:i));
        
        // Default values
        const def = (d.dataset.default || "09:00").split(':'); 
        h.value = def[0]; 
        m.value = def[1];
        
        d.append(h); d.innerHTML+='<span style="margin:0 5px">:</span>'; d.append(m);
    });
}

function getPickerValue(id) { 
    const s = document.getElementById(id).querySelectorAll('select'); 
    return `${s[0].value}:${s[1].value}`; 
}

function addAssignmentRow() {
    const d = document.createElement('div'); d.className = 'syllabus-row';
    const opts = a => a.map(x => `<option value="${x}">${x}</option>`).join('');
    d.innerHTML = `
        <div class="span-2"><label style="font-size:0.7rem">Assignment Name</label><input type="text" class="a-name" placeholder="Task Name"></div>
        <div><label style="font-size:0.7rem">Due Date</label><input type="date" class="a-date"></div>
        <div><label style="font-size:0.7rem">Sessions</label><input type="number" class="a-sessions" value="1" min="1"></div>
        <div><label style="font-size:0.7rem">Type</label><select class="a-type"><option value="">Select</option>${opts(ASSIGNMENT_TYPES)}</select></div>
        <div><label style="font-size:0.7rem">Field</label><select class="a-field"><option value="">Select</option>${opts(MAJORS)}</select></div>
        <div><label style="font-size:0.7rem">Resources</label><select class="a-resource">${opts(RESOURCES)}</select></div>
        <div><label style="font-size:0.7rem">Location</label><select class="a-location">${opts(LOCATIONS)}</select></div>
        <div class="span-2 checkbox-group">
            <label style="font-size:0.75rem"><input type="checkbox" class="a-group"> Group?</label>
            <label style="font-size:0.75rem; margin-left:10px"><input type="checkbox" class="a-person"> In-Person?</label>
        </div>
        <div class="span-2" style="text-align:right"><button class="btn-delete" onclick="this.parentElement.parentElement.remove()">Remove</button></div>
    `;
    document.getElementById('assignmentsContainer').appendChild(d);
}

function addPdfRow() {
    const d = document.createElement('div'); d.className = 'syllabus-row'; d.style.gridTemplateColumns = "1fr 50px";
    d.innerHTML = `<div><label style="font-size:0.7rem">Syllabus PDF</label><input type="file" class="pdf-file" accept=".pdf"></div>
                   <div style="text-align:right; display:flex; align-items:end; justify-content:end"><button class="btn-delete" onclick="this.parentElement.parentElement.remove()">X</button></div>`;
    document.getElementById('pdfContainer').appendChild(d);
}

async function handleSubmit() {
    const btn = document.getElementById('submitBtn'); btn.textContent = "PROCESSING..."; btn.disabled = true;
    try {
        const survey = { email: document.getElementById('email').value, year: document.getElementById('studentYear').value, major: document.getElementById('major').value };
        const prefs = { timezone: document.getElementById('timezone').value, weekdayStart: getPickerValue('weekdayStart'), weekdayEnd: getPickerValue('weekdayEnd'), weekendStart: getPickerValue('weekendStart'), weekendEnd: getPickerValue('weekendEnd') };
        
        const courses = [];
        document.querySelectorAll('#assignmentsContainer .syllabus-row').forEach(r => {
            if(r.querySelector('.a-name')) courses.push({
                assignment_name: r.querySelector('.a-name').value, due_date: r.querySelector('.a-date').value,
                work_sessions: r.querySelector('.a-sessions').value, assignment_type: r.querySelector('.a-type').value,
                field_of_study: r.querySelector('.a-field').value
            });
        });

        const fd = new FormData();
        fd.append('data', JSON.stringify({ survey, courses, preferences: prefs }));
        let pIdx = 0;
        document.querySelectorAll('#pdfContainer .pdf-file').forEach(f => { if(f.files.length) fd.append(`pdf_${pIdx++}`, f.files[0]); });
        fd.append('pdf_count', pIdx);
        const ics = document.getElementById('icsUpload'); if(ics.files.length) fd.append('ics', ics.files[0]);

        const res = await fetch('/api/generate-schedule', { method: 'POST', body: fd });
        const data = await res.json();
        
        if(res.ok) {
            btn.textContent = "DONE";
            const resArea = document.getElementById('resultArea'); resArea.style.display = 'block';
            let html = '<div class="prediction-header"><h5>Workload</h5></div>';
            
            data.assignments.forEach(t => {
                const dateObj = new Date(t.due_date);
                const dateStr = dateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                const timeStr = dateObj.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
                
                html += `
                <div class="prediction-row">
                    <div class="p-info">
                        <span class="p-name">${t.name}</span>
                        <span class="p-date">Due: ${dateStr} @ ${timeStr}</span>
                    </div>
                    <span class="p-time">${t.time_estimate}h</span>
                </div>`;
            });
            
            document.getElementById('predictionList').innerHTML = html;
            const dl = document.getElementById('downloadLink'); dl.href = data.ics_url; dl.download = "Schedule.ics";
            resArea.scrollIntoView({ behavior: 'smooth' });
        } else alert(data.error);
    } catch(e) { console.error(e); alert("Error"); }
    finally { setTimeout(() => { btn.disabled=false; btn.textContent="Initialize Optimization"; }, 2000); }
}
