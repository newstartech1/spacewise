const API_BASE_URL = "http://localhost:8000";

const apiStatusDot = document.querySelector("#apiStatusDot");
const apiStatusText = document.querySelector("#apiStatusText");
const roomPhotoInput = document.querySelector("#roomPhoto");
const previewArea = document.querySelector("#previewArea");
const roomPreview = document.querySelector("#roomPreview");
const clearPhotoButton = document.querySelector("#clearPhoto");
const analyzeButton = document.querySelector("#analyzeButton");
const analysisEmpty = document.querySelector("#analysisEmpty");
const analysisLoading = document.querySelector("#analysisLoading");
const analysisSummary = document.querySelector("#analysisSummary");
const analysisError = document.querySelector("#analysisError");
const analysisErrorText = document.querySelector("#analysisErrorText");
const analysisResults = document.querySelector("#analysisResults");
const resultGoal = document.querySelector("#resultGoal");
const inventoryList = document.querySelector("#inventoryList");
const recommendationList = document.querySelector("#recommendationList");
const limitationList = document.querySelector("#limitationList");

async function checkApiHealth() {
  try {
    const response = await fetch(`${API_BASE_URL}/health`);
    if (!response.ok) {
      throw new Error("Health check failed");
    }

    const data = await response.json();
    apiStatusDot.classList.add("is-online");
    apiStatusText.textContent = data.message;
  } catch {
    apiStatusDot.classList.remove("is-online");
    apiStatusText.textContent = "API offline until the backend is running";
  }
}

function getSelectedGoals() {
  return Array.from(document.querySelectorAll('input[name="goals"]:checked')).map(
    (input) => input.value,
  );
}

function updatePreview(file) {
  if (!file) {
    previewArea.hidden = true;
    roomPreview.removeAttribute("src");
    return;
  }

  const previewUrl = URL.createObjectURL(file);
  roomPreview.src = previewUrl;
  previewArea.hidden = false;

  roomPreview.onload = () => URL.revokeObjectURL(previewUrl);
}

roomPhotoInput.addEventListener("change", (event) => {
  updatePreview(event.target.files[0]);
});

clearPhotoButton.addEventListener("click", () => {
  roomPhotoInput.value = "";
  updatePreview(null);
});

analyzeButton.addEventListener("click", async () => {
  const selectedGoals = getSelectedGoals();
  const photo = roomPhotoInput.files[0];

  if (!photo) {
    showError("Please upload a room photo before starting analysis.");
    return;
  }

  if (!selectedGoals.length) {
    showError("Please select at least one improvement goal.");
    return;
  }

  analysisEmpty.hidden = true;
  analysisLoading.hidden = false;
  analysisError.hidden = true;
  analysisResults.hidden = true;
  analyzeButton.disabled = true;
  analyzeButton.textContent = "Analyzing...";

  const formData = new FormData();
  formData.append("photo", photo);
  formData.append("goal", selectedGoals.join(", "));

  try {
    const response = await fetch(`${API_BASE_URL}/analyze-room`, {
      method: "POST",
      body: formData,
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Analysis failed.");
    }

    renderAnalysis(payload);
  } catch (error) {
    showError(error.message || "Spacewise could not complete the analysis.");
  } finally {
    analyzeButton.disabled = false;
    analyzeButton.textContent = "Analyze room";
  }
});

function renderAnalysis(data) {
  analysisLoading.hidden = true;
  analysisError.hidden = true;
  analysisResults.hidden = false;

  resultGoal.textContent = data.selected_goal || "Overall improvement";

  renderInventory(data.detected_inventory || []);
  renderList(recommendationList, data.recommendations || [], "No recommendations returned.");
  renderList(
    limitationList,
    data.limitations || [],
    "No limitations returned. Treat detections as approximate.",
  );
}

function renderInventory(items) {
  inventoryList.replaceChildren();

  if (!items.length) {
    inventoryList.appendChild(createListItem("No room objects were confidently detected."));
    return;
  }

  items.forEach((item) => {
    const confidence = Number.isFinite(item.confidence)
      ? `, ${item.confidence}% confidence`
      : "";
    const count = item.instances ? ` (${item.instances} visible instance${item.instances === 1 ? "" : "s"})` : "";
    inventoryList.appendChild(createListItem(`${item.name}${count}${confidence}`));
  });
}

function renderList(target, items, emptyText) {
  target.replaceChildren();
  const values = items.length ? items : [emptyText];
  values.forEach((item) => target.appendChild(createListItem(item)));
}

function createListItem(text) {
  const item = document.createElement("li");
  item.textContent = text;
  return item;
}

function showError(message) {
  analysisEmpty.hidden = true;
  analysisLoading.hidden = true;
  analysisResults.hidden = true;
  analysisError.hidden = false;
  analysisErrorText.textContent = message;
}

checkApiHealth();
