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
    opts('major', MAJORS); opts('second_concentration', MAJORS, true); opts('minor', MAJORS, true);
    
    initTimePickers();
    addAssignmentRow();
    addPdfRow();

    document.getElementById('addAssignmentBtn').onclick = addAssignmentRow;
    document.getElementById('addPdfBtn').onclick = addPdfRow;
    document.getElementById('submitBtn').onclick = handleSubmit;
});

function initTimePickers() {
    document.querySelectorAll('.time-picker').forEach(d => {
        if(d.children.length) return;
        const h = document.createElement('select'), m = document.createElement('select');
        for(let i=0;i<24;i++) h.add(new Option(i<10?'0'+i:i, i<10?'0'+i:i));
        for(let i=0;i<60;i+=15) m.add(new Option(i<10?'0'+i:i, i<10?'0'+i:i));
        const def = d.dataset.default.split(':'); h.value=def[0]; m.value=def[1];
        d.append(h); d.innerHTML+='<span style="margin:0 5px">:</span>'; d.append(m);
    });
}
function getPickerValue(id) { const s = document.getElementById(id).querySelectorAll('select'); return `${s[0].value}:${s[1].value}`; }

function addAssignmentRow() {
    const d = document.createElement('div'); d.className = 'syllabus-row';
    const opts = a => a.map(x => `<option value="${x}">${x}</option>`).join('');
    
    // UPDATED: Changed label from "In-Person?" to "Submitted in Person?"
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
            <label style="font-size:0.75rem; margin-left:10px"><input type="checkbox" class="a-person"> Submitted in Person?</label>
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
            
            // UPDATED: Date formatting and display logic
            data.assignments.forEach(t => {
                let dateDisplay = "";
                if (t.due_date) {
                    // Create a readable date format (e.g., "Mon, Jan 15")
                    const d = new Date(t.due_date);
                    // Check if date is valid
                    if (!isNaN(d.getTime())) {
                        const dateStr = d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
                        dateDisplay = `<span style="font-weight:normal; font-size:0.8em; opacity:0.65; margin-left:10px; font-family:var(--font-body); letter-spacing:0;">(Due: ${dateStr})</span>`;
                    } else {
                        // Fallback for raw string if parsing fails
                        dateDisplay = `<span style="font-weight:normal; font-size:0.8em; opacity:0.65; margin-left:10px;">(Due: ${t.due_date.split(' ')[0]})</span>`;
                    }
                }

                html += `<div class="prediction-row">
                            <span class="p-name">${t.name} ${dateDisplay}</span>
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

const em = document.getElementById('email');
if(em) {
    em.addEventListener('blur', async () => {
        if(!em.value.includes('@')) return;
        em.style.opacity = "0.5";
        try {
            const r = await fetch(`/api/get-user-preferences?email=${encodeURIComponent(em.value)}`);
            if(r.ok) {
                const d = await r.json();
                document.getElementById('studentYear').value = d.year;
                document.getElementById('timezone').value = d.timezone;
            }
        } catch(e) { console.error(e); }
        finally { em.style.opacity = "1"; }
    });
}
