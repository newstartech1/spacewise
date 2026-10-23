/* Spacewise browser workflow: native upload, preview, analysis, and chat. */
(function initializeSpacewise() {
  const base = location.protocol === "file:" ? "http://127.0.0.1:8000" : location.origin;
  const photo = document.getElementById("roomPhoto"), preview = document.getElementById("roomPreview"), previewArea = document.getElementById("previewArea"), button = document.getElementById("analyzeButton");
  const views = ["analysisEmpty", "analysisLoading", "analysisError", "analysisResults"].map((id) => document.getElementById(id));
  let previewUrl;
  const show = (id) => views.forEach((view) => view.hidden = view.id !== id);
  const error = (message) => { document.getElementById("analysisErrorText").textContent = message; show("analysisError"); };
  const items = (id, values, display = String) => {
    const list = document.getElementById(id); list.replaceChildren();
    (values || []).forEach((value) => { const li = document.createElement("li"); li.textContent = display(value); list.appendChild(li); });
  };
  const clear = () => { photo.value = ""; if (previewUrl) URL.revokeObjectURL(previewUrl); previewUrl = null; preview.removeAttribute("src"); previewArea.hidden = true; };

  photo.addEventListener("change", () => {
    const file = photo.files[0]; if (!file) return;
    if (!/^image\/(jpeg|png)$/.test(file.type)) { clear(); return error("Use a JPEG or PNG room photo. These are the formats Amazon Rekognition accepts."); }
    if (file.size > 10 * 1024 * 1024) { clear(); return error("Choose an image smaller than 10 MB."); }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(file); preview.src = previewUrl; previewArea.hidden = false;
  });
  document.getElementById("clearPhoto").addEventListener("click", clear);

  function assessment(data) {
    const labels = { design_confidence: "Design Confidence", space_utilization: "Space Utilization", budget_compatibility: "Budget Compatibility", feasibility_confidence: "Feasibility Confidence", overall_compatibility: "Overall Compatibility" };
    const area = document.getElementById("assessmentMeters"); area.replaceChildren();
    Object.entries(labels).forEach(([key, label]) => {
      const score = Number(data?.scores?.[key] || 0), meter = document.createElement("div"); meter.className = "assessment-meter";
      meter.innerHTML = `<div class="assessment-meter-header"><span>${label}</span><output>${score}%</output></div><div class="meter-track"><span class="meter-fill" style="width:${score}%"></span></div>`; area.appendChild(meter);
    });
    document.getElementById("assessmentMethod").textContent = "Repeatable suitability indicators based on the selected goals and verified analysis output.";
    items("assessmentRules", data?.fallback_rules);
  }

  button.addEventListener("click", async () => {
    const file = photo.files[0], goals = [...document.querySelectorAll('input[name="goals"]:checked')].map((box) => box.value);
    if (!file) { photo.focus(); return error("Choose a JPEG or PNG room photo before analysis."); }
    if (!goals.length) return error("Select at least one improvement goal.");
    button.disabled = true; show("analysisLoading");
    const form = new FormData(); form.append("photo", file, file.name); form.append("goal", goals.join(", "));
    try {
      const response = await fetch(`${base}/analyze-room`, { method: "POST", body: form });
      const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.detail || `Analysis request failed (${response.status}).`);
      document.getElementById("resultGoal").textContent = data.selected_goal; assessment(data.assessment);
      items("inventoryList", data.detected_inventory, (item) => `${item.name} (${item.confidence}% confidence${item.instances ? `, ${item.instances} instance${item.instances === 1 ? "" : "s"}` : ""})`);
      items("recommendationList", data.recommendations); items("limitationList", data.limitations); show("analysisResults");
    } catch (err) { error(err.message || "The analysis request could not be completed."); } finally { button.disabled = false; }
  });
  fetch(`${base}/health`).then((response) => { if (!response.ok) throw Error(); document.getElementById("apiStatusText").textContent = "API is online"; document.getElementById("apiStatusDot").classList.add("is-online"); }).catch(() => { document.getElementById("apiStatusText").textContent = "API unavailable — start FastAPI on port 8000"; });

  // Existing local assistant remains explicit: it is not Alexa+.
  const assistant = document.createElement("section"); assistant.id = "spacewiseAssistant"; assistant.className = "spacewise-assistant";
  assistant.innerHTML = `<h2>Spacewise Assistant</h2><p class="assistant-note">Local rules-based room-planning assistant (not a verified Alexa+ integration).</p><div id="spacewiseConversation" role="log" aria-live="polite"></div><form><input aria-label="Room planning request" placeholder="e.g. Make my small bedroom feel spacious" required><button>Send</button></form>`;
  document.querySelector("main").appendChild(assistant); const log = assistant.querySelector("div"), say = (name, text) => { const line = document.createElement("p"); line.textContent = `${name}: ${text}`; log.appendChild(line); log.scrollTop = log.scrollHeight; };
  say("Spacewise", "Hello! Describe your room and what you want to improve.");
  assistant.querySelector("form").addEventListener("submit", (event) => { event.preventDefault(); const input = assistant.querySelector("input"), request = input.value.trim(); if (!request) return; say("You", request); input.value = ""; const q = request.toLowerCase(); say("Spacewise", /budget|cheap|affordable|cost/.test(q) ? "Start by rearranging existing furniture and using modular storage." : /small|space|storage|clutter/.test(q) ? "Try vertical storage, multi-purpose furniture, and clearer walking paths." : /light|dark|bright|window/.test(q) ? "Keep natural light clear and add layered lighting." : "Upload a room photo for a detailed analysis."); });
})();
