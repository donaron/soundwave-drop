(() => {
  const inspectForm = document.getElementById("inspect-form");
  const urlInput = document.getElementById("url-input");
  const clearUrlBtn = document.getElementById("clear-url-btn");
  const fetchBtn = document.getElementById("fetch-btn");

  const errorBanner = document.getElementById("error-banner");
  const errorText = document.getElementById("error-text");
  const errorClose = document.getElementById("error-close");

  const previewCard = document.getElementById("preview-card");
  const thumbImg = document.getElementById("thumb-img");
  const thumbFallback = document.getElementById("thumb-fallback");
  const mediaTitle = document.getElementById("media-title");
  const mediaMeta = document.getElementById("media-meta");
  const playlistNote = document.getElementById("playlist-note");

  const btnMp3 = document.getElementById("format-mp3");
  const btnMp4 = document.getElementById("format-mp4");
  const qualityLabel = document.getElementById("quality-label");
  const qualitySelect = document.getElementById("quality-select");
  const hdCodecHint = document.getElementById("hd-codec-hint");

  const statusText = document.getElementById("status-text");
  const percentText = document.getElementById("percent-text");
  const progressBar = document.getElementById("progress-bar");
  const progressTrack = document.getElementById("progress-track");

  const downloadBtn = document.getElementById("download-btn");
  const cancelBtn = document.getElementById("cancel-btn");
  const downloadAnotherBtn = document.getElementById("download-another-btn");

  const historyCount = document.getElementById("history-count");
  const historyEmpty = document.getElementById("history-empty");
  const historyList = document.getElementById("history-list");

  const MP3_LABELS = {
    320: "320 kbps (Best)",
    192: "192 kbps (Standard)",
    128: "128 kbps (Compact)",
  };

  const MP4_LABELS = {
    2160: "2160p (4K)",
    1440: "1440p (2K)",
    1080: "1080p (Full HD)",
    720: "720p (HD)",
    480: "480p",
    360: "360p",
    240: "240p",
    144: "144p",
    best: "Best available",
  };

  let inspectedMedia = null;
  let currentFormat = "mp3";
  let activeEventSource = null;
  let activeJobId = null;
  let inspectRequestId = 0;
  let activeInspectController = null;
  let sessionCount = 0;

  function showError(message) {
    errorText.textContent = message;
    errorBanner.hidden = false;
  }

  function hideError() {
    errorBanner.hidden = true;
    errorText.textContent = "";
  }

  function formatDuration(seconds) {
    if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) {
      return "Unknown length";
    }
    const total = Math.floor(seconds);
    const hrs = Math.floor(total / 3600);
    const mins = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return hrs > 0 ? `${hrs}:${pad(mins)}:${pad(secs)}` : `${mins}:${pad(secs)}`;
  }

  function formatBytes(bytes) {
    if (typeof bytes !== "number" || bytes <= 0) return "";
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function setProgress(pct, label, isReady = false) {
    const clamped = Math.max(0, Math.min(100, Number(pct) || 0));
    progressBar.style.width = `${clamped}%`;
    progressBar.classList.toggle("is-ready", isReady);
    progressTrack.setAttribute("aria-valuenow", String(Math.round(clamped)));
    percentText.textContent = clamped > 0 ? `${Math.round(clamped)}%` : "";
    statusText.textContent = label;
    statusText.classList.toggle("is-ready", isReady);
  }

  function closeActiveStream() {
    if (activeEventSource) {
      activeEventSource.close();
      activeEventSource = null;
    }
  }

  function setBusy(isBusy) {
    urlInput.disabled = isBusy;
    fetchBtn.disabled = isBusy;
    btnMp3.disabled = isBusy;
    btnMp4.disabled = isBusy;
    qualitySelect.disabled = isBusy;
    downloadBtn.disabled = isBusy;
    cancelBtn.hidden = !isBusy || !activeJobId;
  }

  function updateCodecHint() {
    const val = qualitySelect.value;
    const show = currentFormat === "mp4" && (val === "2160" || val === "1440");
    hdCodecHint.hidden = !show;
  }

  function populateQualityOptions() {
    if (!inspectedMedia) return;
    qualitySelect.innerHTML = "";
    if (currentFormat === "mp3") {
      qualityLabel.textContent = "Bitrate";
      const bitrates = inspectedMedia.mp3_bitrates || [320, 192, 128];
      for (const rate of bitrates) {
        const opt = document.createElement("option");
        opt.value = String(rate);
        opt.textContent = MP3_LABELS[rate] || `${rate} kbps`;
        qualitySelect.appendChild(opt);
      }
    } else {
      qualityLabel.textContent = "Resolution";
      const heights = inspectedMedia.mp4_heights || ["best"];
      for (const h of heights) {
        const opt = document.createElement("option");
        opt.value = String(h);
        opt.textContent = MP4_LABELS[h] || `${h}p`;
        qualitySelect.appendChild(opt);
      }
      if (heights.includes(1080)) {
        qualitySelect.value = "1080";
      }
    }
    downloadBtn.textContent = currentFormat === "mp3" ? "Download MP3" : "Download MP4";
    updateCodecHint();
  }

  function setFormat(nextFmt) {
    currentFormat = nextFmt;
    const isMp3 = nextFmt === "mp3";
    btnMp3.classList.toggle("active", isMp3);
    btnMp3.setAttribute("aria-pressed", String(isMp3));
    btnMp4.classList.toggle("active", !isMp3);
    btnMp4.setAttribute("aria-pressed", String(!isMp3));
    populateQualityOptions();
  }

  function triggerBrowserSave(jobId, filename) {
    const link = document.createElement("a");
    link.href = `/api/jobs/${encodeURIComponent(jobId)}/file`;
    if (filename) {
      link.download = filename;
    }
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function appendHistoryItem(jobId, filename, fmt, quality, sizeBytes) {
    sessionCount += 1;
    historyCount.textContent = String(sessionCount);
    historyEmpty.hidden = true;

    const li = document.createElement("li");
    li.className = "history-item";

    const main = document.createElement("div");
    main.className = "history-item-main";

    const nameEl = document.createElement("div");
    nameEl.className = "history-item-name";
    nameEl.textContent = filename || `${fmt.toUpperCase()} download`;

    const metaEl = document.createElement("div");
    metaEl.className = "history-item-meta";
    const qualityLabelText = fmt === "mp3" ? `${quality} kbps` : (quality === "best" ? "Best" : `${quality}p`);
    const parts = [fmt.toUpperCase(), qualityLabelText];
    const sizeText = formatBytes(sizeBytes);
    if (sizeText) parts.push(sizeText);
    parts.push(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
    metaEl.textContent = parts.join(" • ");

    main.appendChild(nameEl);
    main.appendChild(metaEl);

    const saveLink = document.createElement("a");
    saveLink.className = "history-save-link";
    saveLink.href = `/api/jobs/${encodeURIComponent(jobId)}/file`;
    saveLink.download = filename || "";
    saveLink.textContent = "Save again";
    saveLink.addEventListener("click", async (event) => {
      event.preventDefault();
      hideError();
      try {
        const probe = await fetch(saveLink.href, { method: "HEAD" });
        if (!probe.ok) {
          const expiredBadge = document.createElement("span");
          expiredBadge.className = "history-expired";
          expiredBadge.textContent = "Expired";
          saveLink.replaceWith(expiredBadge);
          showError("This temporary file expired from cache — paste the link again to re-download.");
          return;
        }
        triggerBrowserSave(jobId, filename);
      } catch {
        showError("Could not reach the local server to re-save this file.");
      }
    });

    li.appendChild(main);
    li.appendChild(saveLink);
    historyList.prepend(li);
  }

  function setPreviewControlsDisabled(disabled) {
    btnMp3.disabled = disabled;
    btnMp4.disabled = disabled;
    qualitySelect.disabled = disabled;
    downloadBtn.disabled = disabled;
  }

  function resetForAnother() {
    inspectRequestId += 1;
    if (activeInspectController) {
      activeInspectController.abort();
      activeInspectController = null;
    }
    closeActiveStream();
    activeJobId = null;
    inspectedMedia = null;
    urlInput.value = "";
    clearUrlBtn.hidden = true;
    previewCard.hidden = true;
    downloadAnotherBtn.hidden = true;
    setProgress(0, "Ready to download");
    hideError();
    setBusy(false);
    urlInput.disabled = false;
    fetchBtn.disabled = false;
    fetchBtn.textContent = "Fetch";
    urlInput.focus();
  }

  thumbImg.addEventListener("error", () => {
    thumbImg.hidden = true;
    thumbFallback.hidden = false;
  });

  urlInput.addEventListener("input", () => {
    clearUrlBtn.hidden = urlInput.value.length === 0;
  });

  clearUrlBtn.addEventListener("click", () => {
    urlInput.value = "";
    clearUrlBtn.hidden = true;
    urlInput.focus();
  });

  errorClose.addEventListener("click", hideError);
  btnMp3.addEventListener("click", () => setFormat("mp3"));
  btnMp4.addEventListener("click", () => setFormat("mp4"));
  qualitySelect.addEventListener("change", updateCodecHint);
  downloadAnotherBtn.addEventListener("click", resetForAnother);

  inspectForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const rawUrl = urlInput.value.trim();
    if (!rawUrl) {
      showError("Please paste a media URL first.");
      urlInput.focus();
      return;
    }

    hideError();
    closeActiveStream();
    activeJobId = null;
    if (activeInspectController) {
      activeInspectController.abort();
    }
    inspectRequestId += 1;
    const requestId = inspectRequestId;
    const controller = new AbortController();
    activeInspectController = controller;

    downloadAnotherBtn.hidden = true;
    fetchBtn.disabled = true;
    fetchBtn.textContent = "Fetching...";
    urlInput.disabled = true;
    setPreviewControlsDisabled(true);

    try {
      const resp = await fetch("/api/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: rawUrl }),
        signal: controller.signal,
      });
      if (requestId !== inspectRequestId) return;
      const data = await resp.json();
      if (requestId !== inspectRequestId) return;
      if (!resp.ok) {
        throw new Error(data.detail || "Could not inspect this URL.");
      }

      inspectedMedia = data;
      mediaTitle.textContent = data.title || "Untitled media";
      mediaMeta.textContent = `${formatDuration(data.duration)} • ${data.extractor || "media"}`;
      playlistNote.hidden = !data.is_playlist_url;

      if (typeof data.thumbnail === "string" && /^https?:\/\//i.test(data.thumbnail)) {
        thumbFallback.hidden = true;
        thumbImg.hidden = false;
        thumbImg.src = data.thumbnail;
      } else {
        thumbImg.hidden = true;
        thumbFallback.hidden = false;
      }

      populateQualityOptions();
      setProgress(0, "Choose MP3 or MP4 and click Download");
      previewCard.hidden = false;
    } catch (err) {
      if (requestId !== inspectRequestId || err.name === "AbortError") {
        return;
      }
      previewCard.hidden = true;
      inspectedMedia = null;
      showError(err.message || "Failed to inspect URL.");
    } finally {
      if (requestId === inspectRequestId) {
        activeInspectController = null;
        urlInput.disabled = false;
        fetchBtn.disabled = false;
        fetchBtn.textContent = "Fetch";
        setPreviewControlsDisabled(false);
      }
    }
  });

  downloadBtn.addEventListener("click", async () => {
    if (!inspectedMedia) return;
    hideError();
    closeActiveStream();
    downloadAnotherBtn.hidden = true;

    const chosenFmt = currentFormat;
    const chosenQuality = qualitySelect.value;

    setProgress(2, "Starting job...");
    activeJobId = null;
    setBusy(true);

    try {
      const resp = await fetch("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: inspectedMedia.url,
          format: chosenFmt,
          quality: chosenQuality,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || "Could not start download.");
      }

      activeJobId = data.job_id;
      cancelBtn.hidden = false;

      const source = new EventSource(`/api/jobs/${encodeURIComponent(activeJobId)}/events`);
      activeEventSource = source;

      source.onmessage = (msg) => {
        let payload;
        try {
          payload = JSON.parse(msg.data);
        } catch {
          return;
        }

        if (payload.status === "ready") {
          closeActiveStream();
          const doneJobId = payload.job_id;
          activeJobId = null;
          setBusy(false);
          setProgress(100, `Saved: ${payload.filename || "file ready"}`, true);
          downloadAnotherBtn.hidden = false;
          triggerBrowserSave(doneJobId, payload.filename);
          appendHistoryItem(doneJobId, payload.filename, chosenFmt, chosenQuality, payload.size_bytes);
        } else if (payload.status === "error") {
          closeActiveStream();
          activeJobId = null;
          setBusy(false);
          setProgress(0, "Download failed");
          showError(payload.error || "Download failed.");
        } else if (payload.status === "cancelled") {
          closeActiveStream();
          activeJobId = null;
          setBusy(false);
          setProgress(0, "Cancelled");
          downloadAnotherBtn.hidden = false;
        } else {
          setProgress(payload.progress, payload.stage_label || "Working...");
        }
      };

      source.onerror = () => {
        if (!activeJobId) return;
        closeActiveStream();
        activeJobId = null;
        setBusy(false);
        setProgress(0, "Connection lost");
        showError("Lost progress stream from local server.");
      };
    } catch (err) {
      activeJobId = null;
      setBusy(false);
      setProgress(0, "Failed to start");
      showError(err.message || "Could not start download.");
    }
  });

  cancelBtn.addEventListener("click", async () => {
    if (!activeJobId) return;
    const jobToCancel = activeJobId;
    cancelBtn.disabled = true;
    try {
      await fetch(`/api/jobs/${encodeURIComponent(jobToCancel)}/cancel`, { method: "POST" });
    } catch {
      // SSE stream or cleanup handles remaining state
    } finally {
      cancelBtn.disabled = false;
    }
  });
})();
