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

document.addEventListener('DOMContentLoaded', () => {
    // 1. Populate Dropdowns
    const majorSel = document.getElementById('major');
    const secSel = document.getElementById('second_concentration');
    const minorSel = document.getElementById('minor');

    const addOpts = (sel, includeNA=false) => {
        sel.innerHTML = ''; 
        if(includeNA) sel.add(new Option("N/A", "N/A"));
        else sel.add(new Option("-- Select --", ""));
        MAJORS.forEach(m => sel.add(new Option(m, m)));
    };

    addOpts(majorSel, false);
    addOpts(secSel, true);
    addOpts(minorSel, true);

    // Init Time Pickers
    initTimePickers();
    // Add first row
    addAssignmentRow();
});

// --- TIME PICKERS ---
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
        const defTime = container.dataset.default.split(':');
        hourSel.value = defTime[0]; minSel.value = defTime[1]; 
        container.appendChild(hourSel);
        container.innerHTML += '<span style="margin:0 5px; font-weight:bold;">:</span>';
        container.appendChild(minSel);
    });
}
function getPickerValue(id) {
    const container = document.getElementById(id);
    const selects = container.querySelectorAll('select');
    return `${selects[0].value}:${selects[1].value}`;
}

// --- ASSIGNMENT ROW GENERATOR ---
const assignmentsContainer = document.getElementById('assignmentsContainer');

function addAssignmentRow() {
    const div = document.createElement('div');
    div.className = 'syllabus-row';
    
    // Helper to build options
    const buildOpts = (arr) => arr.map(x => `<option value="${x}">${x}</option>`).join('');

    div.innerHTML = `
        <div class="span-2">
            <label style="font-size:0.7rem;">Assignment Name</label>
            <input type="text" class="a-name" placeholder="Task Name">
        </div>
        <div>
            <label style="font-size:0.7rem;">Due Date</label>
            <input type="date" class="a-date">
        </div>
        <div>
            <label style="font-size:0.7rem;">Sessions Needed</label>
            <input type="number" class="a-sessions" value="1" min="1">
        </div>

        <div>
            <label style="font-size:0.7rem;">Type</label>
            <select class="a-type"><option value="">Select...</option>${buildOpts(ASSIGNMENT_TYPES)}</select>
        </div>
        <div>
            <label style="font-size:0.7rem;">Field of Study</label>
            <select class="a-field"><option value="">Select...</option>${buildOpts(MAJORS)}</select>
        </div>
        <div>
            <label style="font-size:0.7rem;">Resources</label>
            <select class="a-resource">${buildOpts(RESOURCES)}</select>
        </div>
        <div>
            <label style="font-size:0.7rem;">Location</label>
            <select class="a-location">${buildOpts(LOCATIONS)}</select>
        </div>

        <div class="span-2 checkbox-group">
            <label style="font-size:0.75rem; display:flex; align-items:center; cursor:pointer;">
                <input type="checkbox" class="a-group" style="width:auto; margin-right:5px;"> Work in Group?
            </label>
            <label style="font-size:0.75rem; display:flex; align-items:center; cursor:pointer;">
                <input type="checkbox" class="a-person" style="width:auto; margin-right:5px;"> Submit In-Person?
            </label>
        </div>

        <div class="span-2" style="text-align:right;">
            <button class="btn-delete" onclick="this.parentElement.parentElement.remove()">Remove Task</button>
        </div>
    `;
    assignmentsContainer.appendChild(div);
}
document.getElementById('addAssignmentBtn').addEventListener('click', addAssignmentRow);
// --- ADD THIS FUNCTION ---
const pdfContainer = document.getElementById('pdfContainer');

function addPdfRow() {
    const div = document.createElement('div');
    div.className = 'syllabus-row'; 
    div.style.gridTemplateColumns = "1fr 1fr 50px"; 
    
    div.innerHTML = `
        <div>
            <label style="font-size:0.7rem;">Course Name</label>
            <input type="text" class="pdf-course-name" placeholder="e.g. Quantum Mechanics">
        </div>
        <div>
            <label style="font-size:0.7rem;">Syllabus PDF</label>
            <input type="file" class="pdf-file" accept=".pdf">
        </div>
        <div style="text-align:right; display:flex; align-items:end; justify-content:end;">
            <button class="btn-delete" onclick="this.parentElement.parentElement.remove()">X</button>
        </div>
    `;
    pdfContainer.appendChild(div);
}

document.getElementById('addPdfBtn').addEventListener('click', addPdfRow);

// OPTIONAL: Add one empty row on load
document.addEventListener('DOMContentLoaded', () => {
    // ... existing code ...
    addPdfRow(); // <--- Add this
});

// --- SUBMIT ---
document.getElementById('submitBtn').addEventListener('click', async () => {
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
        document.querySelectorAll('.syllabus-row').forEach(row => {
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
            
            if (item.assignment_name && item.due_date) {
                courses.push(item);
            }
        });

        const formData = new FormData();
        formData.append('data', JSON.stringify({ survey: surveyData, courses: courses, preferences: preferences }));

        //const pdfInput = document.getElementById('pdfUpload');
        //for(let i=0; i<pdfInput.files.length; i++) formData.append('pdfs', pdfInput.files[i]);
        let pdfIndex = 0;
        document.querySelectorAll('#pdfContainer .syllabus-row').forEach(row => {
            const fileInput = row.querySelector('.pdf-file');
            const nameInput = row.querySelector('.pdf-course-name');
    
            if (fileInput.files.length > 0) {
                formData.append(`pdf_${pdfIndex}`, fileInput.files[0]);
                // Use user input or fallback to "Unknown"
                formData.append(`course_name_${pdfIndex}`, nameInput.value || "Unknown Course");
                pdfIndex++;
            }
});
formData.append('pdf_count', pdfIndex);

        const icsInput = document.getElementById('icsUpload');
        if(icsInput.files.length > 0) formData.append('ics', icsInput.files[0]);

        const response = await fetch('/api/generate-schedule', {
            method: 'POST',
            body: formData
        });
        
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
                    html += `
                        <div class="prediction-row">
                            <span class="p-name">${task.name}</span>
                            <span class="p-time">${task.time_estimate} hours</span>
                        </div>
                    `;
                });
                predictionList.innerHTML = html;
            }

            if (result.ics_url) {
                downloadLink.href = result.ics_url;
                downloadLink.download = "My_Study_Schedule.ics";
            }
            resultArea.scrollIntoView({ behavior: 'smooth' });
        } else {
            alert("Error: " + (result.error || "Unknown"));
        }
    } catch (e) {
        console.error(e);
        alert("Request failed. See console.");
    } finally {
        setTimeout(() => { btn.disabled = false; btn.textContent = "Initialize Optimization"; }, 2000);
    }
});

// --- NEW: AUTOFILL FEATURE ---
// Listens for when the user finishes typing their email
const emailInput = document.getElementById('email');

if (emailInput) {
    emailInput.addEventListener('blur', () => {
        const email = emailInput.value;
        // Only try if it looks like an email
        if (email && email.includes('@')) {
            console.log("Checking for saved preferences...");
            
            fetch(`/api/get-user-preferences?email=${encodeURIComponent(email)}`)
                .then(res => {
                    if (res.ok) return res.json();
                    throw new Error('User not found');
                })
                .then(data => {
                    console.log("Found user data:", data);

                    // 1. Fill Dropdowns (if data exists)
                    if(data.year) document.getElementById('studentYear').value = data.year;
                    if(data.timezone) document.getElementById('timezone').value = data.timezone;
                    if(data.major) document.getElementById('major').value = data.major;
                    if(data.second_concentration) document.getElementById('second_concentration').value = data.second_concentration;
                    if(data.minor) document.getElementById('minor').value = data.minor;

                    // 2. Fill Time Pickers (Helper function to split 09:00 into 09 and 00)
                    const setTime = (id, val) => {
                        if(!val) return;
                        const [h, m] = val.split(':');
                        const el = document.getElementById(id);
                        if(el) {
                            const selects = el.querySelectorAll('select');
                            if(selects.length === 2) { 
                                selects[0].value = h; 
                                selects[1].value = m; 
                            }
                        }
                    };

                    setTime('weekdayStart', data.weekdayStart);
                    setTime('weekdayEnd', data.weekdayEnd);
                    setTime('weekendStart', data.weekendStart);
                    setTime('weekendEnd', data.weekendEnd);
                })
                .catch(err => {
                    // It's normal to fail if it's a new user, so we just log silently
                    console.log('No saved preferences found for this email.');
                });
        }
    });
}
