const matricNoInput = document.getElementById("matric_no");
const scanBtn = document.getElementById("scan-btn");
const stopBtn = document.getElementById("stop-btn");
const statusEl = document.getElementById("status");
const scanStatusEl = document.getElementById("scan-status");

let isScanning = false;
let statusInterval = null;

function showStatus(message, type = "info") {
  statusEl.textContent = message;
  statusEl.className = `status show ${type}`;
}

function hideStatus() {
  statusEl.className = "status";
}

function updateScanStatus(status) {
  if (status.running) {
    scanStatusEl.innerHTML = `
      <p class="hint" style="color: green">✓ RFID scanner is running</p>
      <p class="hint">Matric No: ${status.matric_no || 'N/A'}</p>
      <p class="hint">Last message: ${status.last_message || 'Waiting for card...'}</p>
    `;
  } else {
    scanStatusEl.innerHTML = `<p class="hint">RFID scanner is idle. Click "Start RFID Scan" to begin.</p>`;
  }
}

async function checkStatus() {
  try {
    const res = await fetch("/rfid/register/status");
    if (res.ok) {
      const status = await res.json();
      updateScanStatus(status);
      
      // If scanning stopped externally, update UI
      if (!status.running && isScanning) {
        stopScanning();
      }
      
      // If registration completed, show success
      if (status.registered && status.card_id) {
        stopScanning();
        showStatus(`RFID Card ${status.card_id} registered successfully!`, "success");
        scanStatusEl.innerHTML = `
          <p class="hint" style="color: green">✓ Registration successful!</p>
          <p class="hint">Card ID: ${status.card_id}</p>
          <p class="hint">Matric No: ${matricNoInput.value}</p>
        `;
      }
    }
  } catch (err) {
    console.error("Failed to check RFID status:", err);
  }
}

function startScanning() {
  const matricNo = matricNoInput.value.trim();
  
  if (!matricNo) {
    showStatus("Please enter your matric number first.", "error");
    return;
  }

  // Start the RFID scanner - backend will validate student existence
  startRFIDScan(matricNo);
}

async function startRFIDScan(matricNo) {
  try {
    const formData = new FormData();
    formData.append("matric_no", matricNo);
    
    const res = await fetch("/rfid/register/start", {
      method: "POST",
      body: formData
    });
    
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || "Failed to start RFID scanner");
    }
    
    isScanning = true;
    scanBtn.style.display = "none";
    stopBtn.style.display = "inline-block";
    matricNoInput.disabled = true;
    showStatus("RFID scanner started. Hold your card near the reader.", "success");
    
    // Start polling for status
    statusInterval = setInterval(checkStatus, 1000);
    checkStatus();
    
  } catch (err) {
    showStatus(err.message, "error");
  }
}

function stopScanning() {
  isScanning = false;
  scanBtn.style.display = "inline-block";
  stopBtn.style.display = "none";
  matricNoInput.disabled = false;
  
  if (statusInterval) {
    clearInterval(statusInterval);
    statusInterval = null;
  }
  
  // Stop the backend scanner
  fetch("/rfid/register/stop", { method: "POST" })
    .then(res => res.json())
    .then(data => {
      console.log("RFID scanner stopped:", data);
    })
    .catch(err => {
      console.error("Failed to stop RFID scanner:", err);
    });
  
  updateScanStatus({ running: false });
}

scanBtn.addEventListener("click", startScanning);
stopBtn.addEventListener("click", stopScanning);

// Initial status check
checkStatus();
