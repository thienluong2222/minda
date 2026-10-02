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
  const review = document.getElementById("review-only");
  if (search && speaker && review) {
    const update = () => {
      const query = search.value.trim().toLocaleLowerCase("vi");
      let visible = 0;
      for (const card of document.querySelectorAll(".segment")) {
        const matched = (!query || card.dataset.search.toLocaleLowerCase("vi").includes(query))
          && (!speaker.value || card.dataset.speaker === speaker.value)
          && (!review.checked || card.dataset.review === "true");
        card.hidden = !matched;
        if (matched) visible++;
      }
      document.getElementById("filter-empty").hidden = visible !== 0;
    };
    for (const element of [search, speaker, review]) element.addEventListener("input", update);
  }

  // Listening to one source at a time avoids accidental simultaneous playback.
  document.addEventListener("play", event => {
    if (!(event.target instanceof HTMLAudioElement)) return;
    for (const audio of document.querySelectorAll("audio")) {
      if (audio !== event.target) audio.pause();
    }
  }, true);
})();
