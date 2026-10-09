(() => {
  const descriptions = document.getElementById("method-descriptions");
  if (descriptions) {
    const data = JSON.parse(descriptions.textContent);
    for (const field of ["identity_method", "fusion_method"]) {
      const select = document.getElementById(field);
      const target = document.querySelector(`[data-method-description="${field}"]`);
      if (select && target) {
        const update = () => { target.textContent = data[field][select.value] || "Chưa có dữ liệu"; };
        select.addEventListener("change", update);
        update();
      }
    }
  }

  for (const input of document.querySelectorAll('input[type="file"]')) {
    const target = document.querySelector(`[data-file-list-for="${input.id}"]`);
    if (!target) continue;
    input.addEventListener("change", () => {
      target.textContent = [...input.files].map(file => file.name).join(" · ");
    });
  }

  for (const formId of ["speaker-form", "meeting-form"]) {
    const form = document.getElementById(formId);
    if (!form) continue;
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const message = form.querySelector(".form-message");
      const button = form.querySelector('button[type="submit"]');
      message.classList.remove("error");
      message.textContent = formId === "speaker-form" ? "Đang tạo hồ sơ giọng…" : "Đang tải tệp…";
      button.disabled = true;
      try {
        const response = await fetch(form.action, {method: "POST", body: new FormData(form)});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "Không thể hoàn tất yêu cầu.");
        if (formId === "speaker-form") window.location.reload();
        else window.location.href = `/runs/${payload.job_id}`;
      } catch (error) {
        message.classList.add("error");
        message.textContent = error.message;
        button.disabled = false;
      }
    });
  }

  const state = document.querySelector("[data-job-status]");
  if (state && ["queued", "running"].includes(state.dataset.jobStatus)) {
    const jobId = window.location.pathname.split("/").pop();
    const poll = async () => {
      try {
        const response = await fetch(`/api/runs/${jobId}`);
        const payload = await response.json();
        if (["succeeded", "failed"].includes(payload.status)) window.location.reload();
        else window.setTimeout(poll, 3000);
      } catch { window.setTimeout(poll, 5000); }
    };
    window.setTimeout(poll, 3000);
  }

  const search = document.getElementById("search");
  const speaker = document.getElementById("speaker-filter");
  const sourceFilter = document.getElementById("source-filter");
  const review = document.getElementById("review-only");
  if (search && speaker && review) {
    const update = () => {
      const query = search.value.trim().toLocaleLowerCase("vi");
      let visible = 0;
      for (const card of document.querySelectorAll(".segment")) {
        const matched = (!query || card.dataset.search.toLocaleLowerCase("vi").includes(query))
          && (!speaker.value || card.dataset.speaker === speaker.value)
          && (!sourceFilter || !sourceFilter.value || card.dataset.source === sourceFilter.value)
          && (!review.checked || card.dataset.review === "true");
        card.hidden = !matched;
        if (matched) visible++;
      }
      document.getElementById("filter-empty").hidden = visible !== 0;
    };
    for (const element of [search, speaker, sourceFilter, review].filter(Boolean)) {
      element.addEventListener("input", update);
    }
  }

  for (const button of document.querySelectorAll(".rename-button")) {
    button.addEventListener("click", async () => {
      const speakerId = button.dataset.speakerId;
      const input = document.getElementById(`rename-input-${speakerId}`);
      if (!input || !input.value.trim()) return;
      const newLabel = input.value.trim();
      const jobId = window.location.pathname.split("/").pop();
      button.disabled = true;
      button.textContent = "Đang lưu…";
      try {
        const res = await fetch(`/api/runs/${jobId}/rename-speaker`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({meeting_speaker_id: speakerId, new_label: newLabel}),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Đổi tên thất bại");
        window.location.reload();
      } catch (err) {
        alert(err.message);
        button.disabled = false;
        button.textContent = "Lưu";
      }
    });
  }

  // Handle template upload
  const templateForm = document.getElementById("template-upload-form");
  if (templateForm) {
    templateForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fileInput = document.getElementById("template-file");
      if (!fileInput || !fileInput.files.length) return;
      const file = fileInput.files[0];
      const jobId = window.location.pathname.split("/").pop();
      const statusSpan = document.getElementById("upload-status");
      const submitBtn = document.getElementById("btn-upload-template");
      if (statusSpan) statusSpan.textContent = "Đang phân tích mẫu và điền Word…";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Đang xử lý…";
      }
      const formData = new FormData();
      formData.append("template", file);
      const minutesOptions = getMinutesOptions();
      formData.append("use_model", String(minutesOptions.use_model));
      formData.append("minutes_mode", minutesOptions.mode);
      formData.append("use_fcm", String(minutesOptions.use_fcm));
      formData.append("correct_transcript", String(minutesOptions.correct_transcript));
      if (minutesOptions.content_field_id) {
        formData.append("content_field_id", minutesOptions.content_field_id);
      }
      try {
        const res = await fetch(`/api/runs/${jobId}/template`, {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Xử lý biểu mẫu thất bại");
        if (statusSpan) statusSpan.textContent = "Thành công! Đang tải lại…";
        window.location.reload();
      } catch (err) {
        alert(err.message);
        if (statusSpan) statusSpan.textContent = "Lỗi: " + err.message;
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Xử lý biểu mẫu";
        }
      }
    });
  }

  function getMinutesOptions() {
    return {
      mode: document.getElementById("minutes-mode")?.value || "detailed",
      use_model: document.getElementById("minutes-use-model")?.checked || false,
      use_fcm: document.getElementById("minutes-fcm")?.checked ?? true,
      correct_transcript: document.getElementById("minutes-correct")?.checked ?? true,
      content_field_id: document.getElementById("minutes-content-field")?.value || null,
    };
  }

  const regenerateBtn = document.getElementById("btn-regenerate-minutes");
  regenerateBtn?.addEventListener("click", async () => {
    const jobId = window.location.pathname.split("/").pop();
    const statusSpan = document.getElementById("upload-status");
    regenerateBtn.disabled = true;
    statusSpan.textContent = "Đang tạo biên bản từ transcript đã có…";
    try {
      const res = await fetch(`/api/runs/${jobId}/minutes/regenerate`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(getMinutesOptions()),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Không tạo được biên bản");
      window.location.reload();
    } catch (err) {
      statusSpan.textContent = "Lỗi: " + err.message;
      regenerateBtn.disabled = false;
    }
  });

  // Handle saving edited facts
  const saveFactsBtn = document.getElementById("btn-save-facts");
  if (saveFactsBtn) {
    saveFactsBtn.addEventListener("click", async () => {
      const jobId = window.location.pathname.split("/").pop();
      const statusSpan = document.getElementById("save-facts-status");
      const factInputs = document.querySelectorAll(".fact-value-input");
      const facts = [];
      for (const input of factInputs) {
        const fieldId = input.dataset.fieldId;
        const val = input.value;
        facts.push({
          field_id: fieldId,
          value: val.trim() ? val : null,
          status: val.trim() ? "supported" : "unknown",
          user_edited: true,
        });
      }
      saveFactsBtn.disabled = true;
      saveFactsBtn.textContent = "Đang lưu…";
      if (statusSpan) statusSpan.textContent = "Đang cập nhật Word & manifest…";
      try {
        const res = await fetch(`/api/runs/${jobId}/minutes/facts`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({facts: facts}),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Lưu thất bại");
        if (statusSpan) statusSpan.textContent = "Đã lưu thành công!";
        setTimeout(() => window.location.reload(), 700);
      } catch (err) {
        alert(err.message);
        if (statusSpan) statusSpan.textContent = "Lỗi: " + err.message;
        saveFactsBtn.disabled = false;
        saveFactsBtn.textContent = "Lưu chỉnh sửa & Điền lại Word";
      }
    });
  }

  // Handle editing individual transcript segments
  for (const button of document.querySelectorAll(".edit-transcript-button")) {
    button.addEventListener("click", async () => {
      const segIdx = button.dataset.segmentIndex;
      const input = button.parentElement.querySelector(".edit-transcript-input");
      if (!input) return;
      const newText = input.value.trim();
      const jobId = window.location.pathname.split("/").pop();
      button.disabled = true;
      button.textContent = "…";
      try {
        const res = await fetch(`/api/runs/${jobId}/edit-transcript`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({segment_index: parseInt(segIdx, 10), new_text: newText}),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Sửa transcript thất bại");
        window.location.reload();
      } catch (err) {
        alert(err.message);
        button.disabled = false;
        button.textContent = "Lưu";
      }
    });
  }

  // Listening to one source at a time avoids accidental simultaneous playback.
  document.addEventListener("play", event => {
    if (!(event.target instanceof HTMLAudioElement)) return;
    for (const audio of document.querySelectorAll("audio")) {
      if (audio !== event.target) audio.pause();
    }
  }, true);
})();
