// Configure API base if needed (default: same host on port 8000)
const API_BASE = localStorage.getItem('OPEN_SHORTS_API') || 'http://localhost:8000';

const $ = (q)=>document.querySelector(q);
const clipsEl = $('#clips');
const projectIdEl = $('#projectId');

let PROJECT_ID = null;

$('#newProject').onclick = async () => {
  const res = await fetch(`${API_BASE}/api/projects`, { method: 'POST' });
  const data = await res.json();
  PROJECT_ID = data.project_id;
  projectIdEl.textContent = `Project: ${PROJECT_ID}`;
};

$('#ingestBtn').onclick = async () => {
  if (!PROJECT_ID) return alert('Create a project first.');
  const url = $('#url').value.trim();
  if (!url) return alert('Paste a URL.');
  const fd = new FormData();
  fd.append('project_id', PROJECT_ID);
  fd.append('url', url);
  const res = await fetch(`${API_BASE}/api/ingest_url`, { method: 'POST', body: fd });
  const data = await res.json();
  if (!data.ok) return alert('Ingest failed');
  alert('URL ingested.');
};

$('#uploadBtn').onclick = async () => {
  if (!PROJECT_ID) return alert('Create a project first.');
  const f = $('#fileInput').files[0];
  if (!f) return alert('Choose a file.');
  const fd = new FormData();
  fd.append('project_id', PROJECT_ID);
  fd.append('file', f);
  const res = await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: fd });
  const data = await res.json();
  if (!data.ok) return alert('Upload failed');
  alert('File uploaded.');
};

$('#processBtn').onclick = async () => {
  if (!PROJECT_ID) return alert('Create a project first.');
  const clip_length_sec = parseInt($('#clipLen').value || '15', 10);
  const max_clips = parseInt($('#maxClips').value || '6', 10);
  const aspect = $('#aspect').value;
  const style = $('#style').value;

  const payload = {
    project_id: PROJECT_ID,
    clip_length_sec,
    max_clips,
    aspect,
    style
  };
  const res = await fetch(`${API_BASE}/api/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  if (!data.ok) {
    alert('Process failed: ' + (data.detail || ''));
    return;
  }
  renderClips();
};

async function renderClips() {
  if (!PROJECT_ID) return;
  const res = await fetch(`${API_BASE}/api/projects/${PROJECT_ID}/clips`);
  const data = await res.json();
  clipsEl.innerHTML = '';
  data.clips.forEach(name => {
    const url = `${API_BASE}/api/projects/${PROJECT_ID}/clips/${encodeURIComponent(name)}`;
    const div = document.createElement('div');
    div.className = 'clip';
    div.innerHTML = `
      <video src="${url}" controls playsinline></video>
      <div class="meta"><span>${name}</span></div>
    `;
    clipsEl.appendChild(div);
  });
}

// Auto-create a project on load for convenience
(async () => {
  if (!PROJECT_ID) {
    const res = await fetch(`${API_BASE}/api/projects`, { method: 'POST' });
    const data = await res.json();
    PROJECT_ID = data.project_id;
    projectIdEl.textContent = `Project: ${PROJECT_ID}`;
  }
  setInterval(renderClips, 4000);
})();
