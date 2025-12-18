// --- CONFIGURATION ---
const MAJORS = [
    "Business", "Tech & Data Science", "Engineering", "Math", "Natural Sciences", 
    "Social Sciences", "Arts & Humanities", "Health & Education"
];

const ASSIGNMENT_TYPES = [
    "Problem Set", "Coding Assignment", "Research Paper", "Creative Writing/Essay", 
    "Presentation", "Modeling", "Discussion Post", "Readings", "Case Study"
];

const RESOURCES = ["Textbook / class materials", "AI / Chatgpt", "Google/internet"];
const LOCATIONS = ["At home/private setting", "School/library", "Other public setting (cafe, etc.)"];

// --- MAIN INITIALIZATION ---
document.addEventListener('DOMContentLoaded', () => {
    console.log("🚀 ParselAI Frontend Initialized");

    const majorSel = document.getElementById('major');
    const secSel = document.getElementById('second_concentration');
    const minorSel = document.getElementById('minor');

    const addOpts = (sel, includeNA=false) => {
        if(!sel) return;
        sel.innerHTML = ''; 
        if(includeNA) sel.add(new Option("N/A", "N/A"));
        else sel.add(new Option("-- Select --", ""));
        MAJORS.forEach(m => sel.add(new Option(m, m)));
    };

    addOpts(majorSel, false);
    addOpts(secSel, true);
    addOpts(minorSel, true);

    initTimePickers();
    addAssignmentRow();
    addPdfRow();

    const addAssignBtn = document.getElementById('addAssignmentBtn');
    if (addAssignBtn) addAssignBtn.addEventListener('click', addAssignmentRow);

    const addPdfBtn = document.getElementById('addPdfBtn');
    if (addPdfBtn) addPdfBtn.addEventListener('click', addPdfRow);

    const submitBtn = document.getElementById('submitBtn');
    if (submitBtn) submitBtn.addEventListener('click', handleSubmit);

    const emailInput = document.getElementById('email');
    if (emailInput) {
        emailInput.addEventListener('blur', () => fetchUserPreferences(emailInput));
        emailInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault(); 
                fetchUserPreferences(emailInput);
                emailInput.blur(); 
            }
        });
    }
});

async function fetchUserPreferences(emailInput) {
    const email = emailInput.value.trim();
    if (!email || !email.includes('@')) return;

    emailInput.style.opacity = "0.5"; 
    try {
        const res = await fetch(`/api/get-user-preferences?email=${encodeURIComponent(email)}`);
        if (!res.ok) { emailInput.style.opacity = "1"; return; }
        const data = await res.json();

        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (el && val && val !== 'null') el.value = val;
        };

        setVal('studentYear', data.year);
        setVal('timezone', data.timezone);
        setVal('major', data.major);
        setVal('second_concentration', data.second_concentration);
        setVal('minor', data.minor);

        const setTime = (id, val) => {
            if(!val || val === 'null') return;
            let [h, m] = val.split(':');
            if (h.length === 1) h = '0' + h;
            const el = document.getElementById(id);
            if(el) {
                const selects = el.querySelectorAll('select');
                if(selects.length === 2) { selects[0].value = h; selects[1].value = m; }
            }
        };

        setTime('weekdayStart', data.weekdayStart);
        setTime('weekdayEnd', data.weekdayEnd);
        setTime('weekendStart', data.weekendStart);
        setTime('weekendEnd', data.weekendEnd);
        emailInput.style.borderColor = "#10b981";

    } catch (err) { console.error(err); } finally { emailInput.style.opacity = "1"; }
}

function initTimePickers() {
    document.querySelectorAll('.time-picker').forEach(container => {
        if(container.children.length > 0) return;
        const hourSel = document.createElement('select');
        const minSel = document.createElement('select');
        for(let i=0; i<24; i++) {
            let val = i < 10 ? '0'+i : i;
            hourSel.add(new Option(val, val));
        }
        for(let i=0; i<60; i+=15) { 
            let val = i < 10 ? '0'+i : i;
            minSel.add(new Option(val, val));
        }
        const defTime = (container.dataset.default || "09:00").split(':');
        hourSel.value = defTime[0]; 
        minSel.value = defTime[1]; 
        container.appendChild(hourSel);
        container.innerHTML += '<span style="margin:0 5px; font-weight:bold;">:</span>';
        container.appendChild(minSel);
    });
}

function getPickerValue(id) {
    const container = document.getElementById(id);
    if (!container) return "00:00";
    const selects = container.querySelectorAll('select');
    return selects.length < 2 ? "00:00" : `${selects[0].value}:${selects[1].value}`;
}

function addAssignmentRow() {
    const assignmentsContainer = document.getElementById('assignmentsContainer');
    if (!assignmentsContainer) return;
    const div = document.createElement('div');
    div.className = 'syllabus-row';
    const buildOpts = (arr) => arr.map(x => `<option value="${x}">${x}</option>`).join('');

    div.innerHTML = `
        <div class="span-2"><label style="font-size:0.7rem;">Assignment Name</label><input type="text" class="a-name" placeholder="Task Name"></div>
        <div><label style="font-size:0.7rem;">Due Date</label><input type="date" class="a-date"></div>
        <div><label style="font-size:0.7rem;">Sessions Needed</label><input type="number" class="a-sessions" value="1" min="1"></div>
        <div><label style="font-size:0.7rem;">Type</label><select class="a-type"><option value="">Select...</option>${buildOpts(ASSIGNMENT_TYPES)}</select></div>
        <div><label style="font-size:0.7rem;">Field of Study</label><select class="a-field"><option value="">Select...</option>${buildOpts(MAJORS)}</select></div>
        <div><label style="font-size:0.7rem;">Resources</label><select class="a-resource">${buildOpts(RESOURCES)}</select></div>
        <div><label style="font-size:0.7rem;">Location</label><select class="a-location">${buildOpts(LOCATIONS)}</select></div>
        <div class="span-2 checkbox-group">
            <label style="font-size:0.75rem; display:flex; align-items:center; cursor:pointer;"><input type="checkbox" class="a-group" style="width:auto; margin-right:5px;"> Work in Group?</label>
            <label style="font-size:0.75rem; display:flex; align-items:center; cursor:pointer;"><input type="checkbox" class="a-person" style="width:auto; margin-right:5px;"> Submit In-Person?</label>
        </div>
        <div class="span-2" style="text-align:right;"><button class="btn-delete" onclick="this.parentElement.parentElement.remove()">Remove Task</button></div>
    `;
    assignmentsContainer.appendChild(div);
}

function addPdfRow() {
    const pdfContainer = document.getElementById('pdfContainer');
    if (!pdfContainer) return;
    const div = document.createElement('div');
    div.className = 'syllabus-row'; 
    div.style.gridTemplateColumns = "1fr 50px"; 
    div.innerHTML = `<div><label style="font-size:0.7rem;">Syllabus PDF</label><input type="file" class="pdf-file" accept=".pdf"></div>
        <div style="text-align:right; display:flex; align-items:end; justify-content:end;"><button class="btn-delete" onclick="this.parentElement.parentElement.remove()">X</button></div>`;
    pdfContainer.appendChild(div);
}

async function handleSubmit() {
    const btn = document.getElementById('submitBtn');
    btn.textContent = "PROCESSING...";
    btn.disabled = true;

    try {
        const surveyData = {
            email: document.getElementById('email').value,
            year: document.getElementById('studentYear').value,
            major: document.getElementById('major').value,
            second_concentration: document.getElementById('second_concentration').value,
            minor: document.getElementById('minor').value
        };

        const preferences = {
            timezone: document.getElementById('timezone').value, 
            weekdayStart: getPickerValue('weekdayStart'),
            weekdayEnd: getPickerValue('weekdayEnd'),
            weekendStart: getPickerValue('weekendStart'),
            weekendEnd: getPickerValue('weekendEnd')
        };

        const courses = [];
        document.querySelectorAll('#assignmentsContainer .syllabus-row').forEach(row => {
            if (row.querySelector('.a-name')) {
                const item = {
                    assignment_name: row.querySelector('.a-name').value,
                    due_date: row.querySelector('.a-date').value,
                    work_sessions: parseInt(row.querySelector('.a-sessions').value) || 1,
                    assignment_type: row.querySelector('.a-type').value,
                    field_of_study: row.querySelector('.a-field').value,
                    external_resources: row.querySelector('.a-resource').value,
                    work_location: row.querySelector('.a-location').value,
                    work_in_group: row.querySelector('.a-group').checked ? "Yes" : "No",
                    submitted_in_person: row.querySelector('.a-person').checked ? "Yes" : "No"
                };
                if (item.assignment_name && item.due_date) courses.push(item);
            }
        });

        const formData = new FormData();
        formData.append('data', JSON.stringify({ survey: surveyData, courses: courses, preferences: preferences }));

        let pdfIndex = 0;
        document.querySelectorAll('#pdfContainer .syllabus-row').forEach(row => {
            const fileInput = row.querySelector('.pdf-file');
            if (fileInput && fileInput.files.length > 0) {
                formData.append(`pdf_${pdfIndex}`, fileInput.files[0]);
                pdfIndex++;
            }
        });
        formData.append('pdf_count', pdfIndex);

        // UPDATED: Multi-calendar support
        const icsInput = document.getElementById('icsUpload');
        if(icsInput && icsInput.files.length > 0) {
            for (let i = 0; i < icsInput.files.length; i++) {
                formData.append('ics', icsInput.files[i]);
            }
        }

        const response = await fetch('/api/generate-schedule', { method: 'POST', body: formData });
        const result = await response.json();

        if (response.ok) {
            btn.textContent = "DONE";
            const resultArea = document.getElementById('resultArea');
            const downloadLink = document.getElementById('downloadLink');
            const predictionList = document.getElementById('predictionList');
            resultArea.style.display = 'block';

            if (result.assignments && result.assignments.length > 0) {
                let html = '<div class="prediction-header"><h5>Calculated Workloads</h5></div>';
                result.assignments.forEach(task => {
                    const dateObj = new Date(task.due_date);
                    const dateStr = dateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                    const timeStr = dateObj.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
                    html += `<div class="prediction-row"><div class="p-info"><span class="p-name">${task.name}</span><span class="p-date">Due: ${dateStr} @ ${timeStr}</span></div><span class="p-time">${task.time_estimate}h</span></div>`;
                });
                predictionList.innerHTML = html;
            }
            if (result.ics_url) { downloadLink.href = result.ics_url; downloadLink.download = "My_Study_Schedule.ics"; }
            resultArea.scrollIntoView({ behavior: 'smooth' });
        } else { alert("Error: " + (result.error || "Unknown")); }
    } catch (e) { console.error(e); alert("Request failed."); } finally { setTimeout(() => { btn.disabled = false; btn.textContent = "Initialize Optimization"; }, 2000); }
}
