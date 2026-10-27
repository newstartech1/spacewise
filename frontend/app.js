/* Spacewise — OpenCV room analysis frontend. */
(function initializeSpacewise() {
  "use strict";

  const base =
    location.protocol === "file:"
      ? "http://127.0.0.1:8000"
      : location.origin;

  const byId = (id) => document.getElementById(id);

  const photo = byId("roomPhoto");
  const preview = byId("roomPreview");
  const previewArea = byId("previewArea");
  const button = byId("analyzeButton");

  const viewIds = [
    "analysisEmpty",
    "analysisLoading",
    "analysisError",
    "analysisResults"
  ];

  let previewUrl = null;
  let latestAnalysis = null;

  function show(viewId) {
    for (const id of viewIds) {
      const element = byId(id);
      if (element) {
        element.hidden = id !== viewId;
      }
    }
  }

  function showError(message) {
    byId("analysisErrorText").textContent = message;
    show("analysisError");
  }

  function renderList(id, values, format = String) {
    const list = byId(id);
    list.replaceChildren();

    for (const value of values || []) {
      const item = document.createElement("li");
      item.textContent = format(value);
      list.appendChild(item);
    }
  }

  function clearPhoto() {
    photo.value = "";

    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = null;
    }

    preview.removeAttribute("src");
    previewArea.hidden = true;
  }

  photo.addEventListener("change", () => {
    const file = photo.files[0];

    if (!file) {
      clearPhoto();
      return;
    }

    if (!/^image\/(jpeg|png)$/.test(file.type)) {
      clearPhoto();
      showError("Please select a JPEG or PNG room photograph.");
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      clearPhoto();
      showError("Please choose an image smaller than 10 MB.");
      return;
    }

    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }

    previewUrl = URL.createObjectURL(file);
    preview.src = previewUrl;
    previewArea.hidden = false;
  });

  byId("clearPhoto").addEventListener("click", clearPhoto);

  function renderAssessment(data) {
    const labels = {
      design_confidence: "Design Confidence",
      space_utilization: "Space Utilization",
      budget_compatibility: "Budget Compatibility",
      feasibility_confidence: "Feasibility Confidence",
      overall_compatibility: "Overall Compatibility"
    };

    const area = byId("assessmentMeters");
    area.replaceChildren();

    for (const [key, label] of Object.entries(labels)) {
      const raw = Number(data?.scores?.[key]);
      const score = Number.isFinite(raw)
        ? Math.max(0, Math.min(100, Math.round(raw)))
        : 0;

      const meter = document.createElement("div");
      meter.className = "assessment-meter";

      const header = document.createElement("div");
      header.className = "assessment-meter-header";

      const name = document.createElement("span");
      name.textContent = label;

      const output = document.createElement("output");
      output.textContent = `${score}%`;

      header.append(name, output);

      const track = document.createElement("div");
      track.className = "meter-track";

      const fill = document.createElement("span");
      fill.className = "meter-fill";
      fill.style.width = `${score}%`;

      track.appendChild(fill);
      meter.append(header, track);
      area.appendChild(meter);
    }

    byId("assessmentMethod").textContent =
      "Deterministic suitability indicators based on selected goals " +
      "and available analysis findings. These are not calibrated probabilities.";

    renderList("assessmentRules", data?.fallback_rules);
  }

  function formatNumber(value, digits = 1) {
    const number = Number(value);

    return Number.isFinite(number)
      ? number.toFixed(digits)
      : "Unavailable";
  }

  function addVisionMetric(container, label, value, explanation) {
    const metric = document.createElement("div");
    metric.className = "vision-metric";

    const heading = document.createElement("strong");
    heading.textContent = label;

    const reading = document.createElement("div");
    reading.className = "vision-metric-value";
    reading.textContent = value;

    const note = document.createElement("small");
    note.textContent = explanation;

    metric.append(heading, reading, note);
    container.appendChild(metric);
  }

  function renderVision(data) {
    const properties = data.image_properties || {};
    const metrics = byId("visionMetrics");

    metrics.replaceChildren();

    addVisionMetric(
      metrics,
      "Image resolution",
      properties.width && properties.height
        ? `${properties.width} × ${properties.height}`
        : "Unavailable",
      "Image pixels, not room dimensions"
    );

    addVisionMetric(
      metrics,
      "Lighting",
      properties.lighting_classification || "Unavailable",
      "Classification derived from image brightness"
    );

    addVisionMetric(
      metrics,
      "Brightness",
      formatNumber(properties.brightness),
      "Average grayscale intensity, 0–255"
    );

    addVisionMetric(
      metrics,
      "Contrast",
      formatNumber(properties.contrast),
      "Standard deviation of grayscale intensity"
    );

    addVisionMetric(
      metrics,
      "Edge density",
      `${formatNumber(properties.edge_density_percent, 2)}%`,
      "Percentage of pixels marked as edges"
    );

    addVisionMetric(
      metrics,
      "Visual contours",
      properties.meaningful_contours != null
        ? String(properties.meaningful_contours)
        : "Unavailable",
      "Contours above the configured area threshold"
    );

    addVisionMetric(
      metrics,
      "Sharpness indicator",
      properties.quality?.sharpness != null
        ? `${properties.quality.sharpness}/100`
        : "Unavailable",
      "Heuristic based on Laplacian variance"
    );

    addVisionMetric(
      metrics,
      "Contrast indicator",
      properties.quality?.contrast != null
        ? `${properties.quality.contrast}/100`
        : "Unavailable",
      "Heuristic image-quality score"
    );

    const method = data.analysis_method || "unknown";

    byId("visionMethod").textContent =
      method === "opencv-bedrock"
        ? "Analysis: OpenCV image measurements with Amazon Bedrock " +
          "visual interpretation."
        : "Analysis: local OpenCV processing with transparent " +
          "rule-based recommendations. AI object recognition is not active.";

    renderList("visionFacts", data.detected_facts);
  }

  function renderInventory(data) {
    const inventory = Array.isArray(data.detected_inventory)
      ? data.detected_inventory
      : [];

    renderList("inventoryList", inventory, (item) => {
      const name = item?.name || "Unidentified object";

      const quantity =
        Number.isInteger(item?.instances) && item.instances > 0
          ? ` — ${item.instances} visible`
          : "";

      const confidence =
        typeof item?.confidence === "number" &&
        Number.isFinite(item.confidence)
          ? ` (${Math.round(item.confidence)}% model-reported confidence)`
          : "";

      return `${name}${quantity}${confidence}`;
    });

    byId("inventoryStatus").textContent =
      inventory.length > 0
        ? "Objects identified by the configured vision model. " +
          "Review the photograph to confirm each finding."
        : "No semantic objects identified. Local OpenCV processing " +
          "measures visual features but does not independently " +
          "recognize furniture.";
  }

  function renderResults(data) {
    latestAnalysis = data;

    byId("resultGoal").textContent =
      data.selected_goal || "Room improvement";

    renderAssessment(data.assessment || {});
    renderVision(data);
    renderInventory(data);

    renderList("recommendationList", data.recommendations);
    renderList("limitationList", data.limitations);

    show("analysisResults");
  }

  button.addEventListener("click", async () => {
    const file = photo.files[0];

    const goals = [
      ...document.querySelectorAll('input[name="goals"]:checked')
    ].map((checkbox) => checkbox.value);

    if (!file) {
      photo.focus();
      showError("Choose a JPEG or PNG room photo before analysis.");
      return;
    }

    if (!goals.length) {
      showError("Select at least one improvement goal.");
      return;
    }

    const form = new FormData();
    form.append("photo", file, file.name);
    form.append("goal", goals.join(", "));

    button.disabled = true;
    show("analysisLoading");

    try {
      const response = await fetch(`${base}/analyze-room`, {
        method: "POST",
        body: form
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        const detail =
          typeof data.detail === "string"
            ? data.detail
            : `Analysis failed (HTTP ${response.status}).`;

        throw new Error(detail);
      }

      renderResults(data);
    } catch (error) {
      showError(
        error.message || "The analysis request could not be completed."
      );
    } finally {
      button.disabled = false;
    }
  });

  fetch(`${base}/health`)
    .then((response) => {
      if (!response.ok) {
        throw new Error("API unavailable");
      }

      return response.json();
    })
    .then((data) => {
      const version = data.opencv_version
        ? ` — OpenCV ${data.opencv_version}`
        : "";

      byId("apiStatusText").textContent =
        `Analysis API online${version}`;

      byId("apiStatusDot").classList.add("is-online");
    })
    .catch(() => {
      byId("apiStatusText").textContent =
        "Analysis API unavailable — start FastAPI on port 8000";
    });

  // Local assistant: transparent rule-based guidance.
  const assistant = document.createElement("section");
  assistant.id = "spacewiseAssistant";
  assistant.className = "spacewise-assistant";

  assistant.innerHTML = `
    <h2>Spacewise Assistant</h2>
    <p class="assistant-note">
      Local room-planning guidance. Not a live AI chat integration.
    </p>
    <div
      id="spacewiseConversation"
      role="log"
      aria-live="polite"
    ></div>
    <form>
      <input
        aria-label="Room planning request"
        placeholder="e.g. Make my small bedroom feel spacious"
        required
      />
      <button type="submit">Send</button>
    </form>
  `;

  document.querySelector("main").appendChild(assistant);

  const log = byId("spacewiseConversation");

  function say(speaker, message) {
    const line = document.createElement("p");
    line.textContent = `${speaker}: ${message}`;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  say(
    "Spacewise",
    "Hello! Upload a room photo or describe what you want to improve."
  );

  assistant.querySelector("form").addEventListener("submit", (event) => {
    event.preventDefault();

    const input = assistant.querySelector("input");
    const request = input.value.trim();

    if (!request) return;

    say("You", request);
    input.value = "";

    const q = request.toLowerCase();
    let answer;

    if (/budget|cheap|affordable|cost/.test(q)) {
      answer =
        "Start with rearranging existing furniture before buying " +
        "new items.";
    } else if (/small|space|storage|clutter/.test(q)) {
      answer =
        "Consider vertical storage, multipurpose furniture, " +
        "and unobstructed walking paths.";
    } else if (/light|dark|bright|window/.test(q)) {
      answer =
        "Keep natural-light sources clear and consider layered lighting.";
    } else if (latestAnalysis?.recommendations?.length) {
      answer = latestAnalysis.recommendations[0];
    } else {
      answer =
        "Upload a room photograph for measurable visual findings " +
        "and tailored goal-based recommendations.";
    }

    say("Spacewise", answer);
  });
})();