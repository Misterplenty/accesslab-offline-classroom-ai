(() => {
  const statusRegion = document.getElementById("status-region");
  const readableModeStorageKey = "accesslab-readable-mode";
  const a11yModeStorageKey = "accesslab-inclusive-classroom-mode";
  const a11yModes = {
    "large-text": "a11y-large-text",
    "high-contrast": "a11y-high-contrast",
    "plain-language": "a11y-plain-language",
    "reduce-motion": "a11y-reduce-motion",
    keyboard: "a11y-keyboard-mode",
  };
  const dropzoneDefaultLabel = "Choose a file.";
  let activeEvidenceTarget = null;

  document.documentElement.classList.add("js");

  function announceStatus(message) {
    if (!statusRegion || !message) {
      return;
    }
    statusRegion.textContent = message;
    statusRegion.classList.remove("is-hidden");
  }

  function readA11yPreferences() {
    try {
      const rawValue = window.localStorage.getItem(a11yModeStorageKey);
      if (!rawValue) {
        return {};
      }
      const parsed = JSON.parse(rawValue);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  function writeA11yPreferences(preferences) {
    try {
      window.localStorage.setItem(a11yModeStorageKey, JSON.stringify(preferences));
    } catch {
      // Keep the current page state even when storage is unavailable.
    }
  }

  function updatePlainLanguageInputs() {
    const enabled = document.body.classList.contains(a11yModes["plain-language"]);
    document.querySelectorAll("[data-a11y-plain-input]").forEach((input) => {
      if (input instanceof HTMLInputElement) {
        input.value = enabled ? "1" : "0";
      }
    });
  }

  function syncA11yToolbar(preferences) {
    document.querySelectorAll("[data-a11y-toggle]").forEach((button) => {
      const mode = button.dataset.a11yToggle;
      if (!mode || !(mode in a11yModes)) {
        return;
      }
      const enabled = Boolean(preferences[mode]);
      button.setAttribute("aria-pressed", enabled ? "true" : "false");
      button.classList.toggle("is-active", enabled);
    });
  }

  function applyA11yPreferences(preferences, announceMode = "") {
    Object.entries(a11yModes).forEach(([mode, className]) => {
      document.body.classList.toggle(className, Boolean(preferences[mode]));
    });
    updatePlainLanguageInputs();
    syncA11yToolbar(preferences);

    const status = document.getElementById("a11y-mode-status");
    if (status && announceMode) {
      const isEnabled = Boolean(preferences[announceMode]);
      status.textContent = `${announceMode.replace("-", " ")} ${isEnabled ? "on" : "off"}.`;
    }
  }

  function enhanceA11yToolbar() {
    const preferences = readA11yPreferences();
    applyA11yPreferences(preferences);

    document.querySelectorAll("[data-a11y-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const mode = button.dataset.a11yToggle;
        if (!mode || !(mode in a11yModes)) {
          return;
        }
        const nextPreferences = readA11yPreferences();
        nextPreferences[mode] = !Boolean(nextPreferences[mode]);
        writeA11yPreferences(nextPreferences);
        applyA11yPreferences(nextPreferences, mode);
      });
    });
  }

  function detectMathMLSupport() {
    try {
      const probe = document.createElement("div");
      probe.style.position = "absolute";
      probe.style.visibility = "hidden";
      probe.style.pointerEvents = "none";
      probe.style.inset = "-9999px auto auto -9999px";
      probe.innerHTML =
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><mfrac><mi>x</mi><mi>y</mi></mfrac></math>';
      document.body.appendChild(probe);
      const math = probe.querySelector("math");
      const supported = Boolean(
        math &&
          math.getBoundingClientRect().width > 0 &&
          math.getBoundingClientRect().height > 0
      );
      probe.remove();
      if (supported) {
        document.documentElement.classList.add("mathml-supported");
      }
    } catch {
      // Keep readable TeX fallbacks visible when MathML probing fails.
    }
  }

  function enhanceStatusForms() {
    document.querySelectorAll("form[data-status]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        const submitter =
          event.submitter instanceof HTMLElement
            ? event.submitter
            : form.querySelector('button[type="submit"], input[type="submit"]');
        updatePlainLanguageInputs();
        announceStatus(form.dataset.status || "Working...");
        const pendingCard = renderPendingState(form);
        startPendingProgress(pendingCard);
        form.setAttribute("aria-busy", "true");
        form.classList.add("is-submitting");

        form.querySelectorAll("input, textarea, select, button").forEach((field) => {
          if (!(field instanceof HTMLElement)) {
            return;
          }
          field.setAttribute("aria-disabled", "true");
        });

        if (
          submitter instanceof HTMLButtonElement &&
          form.dataset.submitLabel &&
          !submitter.dataset.originalLabel
        ) {
          submitter.dataset.originalLabel = submitter.textContent || "";
          submitter.textContent = form.dataset.submitLabel;
        }
      });
    });
  }

  function buildPendingSteps(form) {
    return (form.dataset.statusSteps || "")
      .split("|")
      .map((step) => step.trim())
      .filter(Boolean);
  }

  function setPendingStep(pendingCard, steps, activeIndex) {
    steps.forEach((step, index) => {
      step.classList.toggle("is-complete", index < activeIndex);
      step.classList.toggle("is-active", index === activeIndex);
      if (index === activeIndex) {
        step.setAttribute("aria-current", "step");
      } else {
        step.removeAttribute("aria-current");
      }
    });

    const currentStep = steps[activeIndex];
    const currentLabel = currentStep ? currentStep.textContent || "" : "";
    const current = pendingCard.querySelector("[data-pending-current]");
    if (current && currentLabel) {
      current.textContent = currentLabel;
    }

    const progress = pendingCard.querySelector("[data-pending-progress]");
    if (progress instanceof HTMLElement && steps.length > 0) {
      const percent = Math.round(((activeIndex + 1) / steps.length) * 100);
      progress.style.width = `${percent}%`;
    }
  }

  function startPendingProgress(pendingCard) {
    if (!pendingCard) {
      return;
    }
    const steps = Array.from(pendingCard.querySelectorAll(".pending-state__step"));
    if (steps.length === 0) {
      return;
    }

    const schedule = [0, 900, 2400, 4800, 8000];
    steps.forEach((_, index) => {
      window.setTimeout(() => {
        setPendingStep(pendingCard, steps, index);
      }, schedule[index] || (index + 1) * 1800);
    });
  }

  function renderPendingState(form) {
    const existing = form.querySelector(".pending-state");
    if (existing) {
      return existing;
    }

    const pendingCard = document.createElement("div");
    pendingCard.className = "pending-state";
    pendingCard.setAttribute("role", "status");
    pendingCard.setAttribute("aria-live", "polite");

    const visual = document.createElement("div");
    visual.className = "pending-state__visual";
    visual.setAttribute("aria-hidden", "true");

    const ring = document.createElement("span");
    ring.className = "pending-state__ring";
    visual.appendChild(ring);

    const mark = document.createElement("span");
    mark.className = "pending-state__mark";
    mark.textContent = "G4";
    visual.appendChild(mark);

    pendingCard.appendChild(visual);

    const eyebrow = document.createElement("p");
    eyebrow.className = "pending-state__eyebrow";
    eyebrow.textContent = "In progress";
    pendingCard.appendChild(eyebrow);

    const title = document.createElement("p");
    title.className = "pending-state__title";
    title.textContent = form.dataset.pendingTitle || form.dataset.status || "Working...";
    pendingCard.appendChild(title);

    if (form.dataset.pendingDetail) {
      const detail = document.createElement("p");
      detail.className = "pending-state__body";
      detail.textContent = form.dataset.pendingDetail;
      pendingCard.appendChild(detail);
    }

    const steps = buildPendingSteps(form);
    if (steps.length > 0) {
      const current = document.createElement("p");
      current.className = "pending-state__current";
      current.dataset.pendingCurrent = "true";
      current.textContent = steps[0];
      pendingCard.appendChild(current);

      const track = document.createElement("div");
      track.className = "pending-state__progress";
      track.setAttribute("aria-hidden", "true");
      const bar = document.createElement("span");
      bar.className = "pending-state__progress-bar";
      bar.dataset.pendingProgress = "true";
      track.appendChild(bar);
      pendingCard.appendChild(track);

      const list = document.createElement("ol");
      list.className = "pending-state__steps";

      steps.forEach((step, index) => {
        const item = document.createElement("li");
        item.className = "pending-state__step";
        if (index === 0) {
          item.classList.add("is-active");
        }
        item.textContent = step;
        list.appendChild(item);
      });

      pendingCard.appendChild(list);
    }

    form.prepend(pendingCard);
    return pendingCard;
  }

  function readReadableModePreference() {
    try {
      return window.localStorage.getItem(readableModeStorageKey) === "on";
    } catch {
      return false;
    }
  }

  function writeReadableModePreference(enabled) {
    try {
      window.localStorage.setItem(readableModeStorageKey, enabled ? "on" : "off");
    } catch {
      // Ignore storage failures and keep the toggle in-memory only.
    }
  }

  function syncReadableToggleLabels(enabled) {
    document.querySelectorAll("[data-readable-toggle]").forEach((button) => {
      button.setAttribute("aria-pressed", enabled ? "true" : "false");
      button.textContent = enabled
        ? button.dataset.readableLabelOn || "Standard view"
        : button.dataset.readableLabelOff || "Readable mode";
    });
  }

  function setReadableMode(enabled) {
    document.body.classList.toggle("readable-mode", enabled);
    syncReadableToggleLabels(enabled);
  }

  function enhanceReadableMode() {
    const buttons = document.querySelectorAll("[data-readable-toggle]");
    if (buttons.length === 0) {
      document.body.classList.remove("readable-mode");
      return;
    }

    setReadableMode(readReadableModePreference());

    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        const nextState = !document.body.classList.contains("readable-mode");
        setReadableMode(nextState);
        writeReadableModePreference(nextState);
      });
    });
  }

  function readTargetText(targetId) {
    const target = document.getElementById(targetId);
    if (!target) {
      return "";
    }
    return (target.innerText || target.textContent || "").replace(/\s+/g, " ").trim();
  }

  function setReadAloudStatus(button, message) {
    const statusId = button.dataset.readAloudStatus;
    const status = statusId ? document.getElementById(statusId) : null;
    if (status) {
      status.textContent = message;
    }
  }

  function enhanceReadAloud() {
    document.querySelectorAll("[data-read-aloud-target]").forEach((button) => {
      button.addEventListener("click", () => {
        const targetId = button.dataset.readAloudTarget;
        if (!targetId) {
          return;
        }
        const text = readTargetText(targetId);
        if (!text) {
          setReadAloudStatus(button, "No readable text is available.");
          return;
        }
        if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") {
          setReadAloudStatus(button, "Read aloud is not available in this browser.");
          return;
        }

        if (window.speechSynthesis.speaking) {
          window.speechSynthesis.cancel();
          setReadAloudStatus(button, "Read aloud stopped.");
          return;
        }

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 0.92;
        utterance.onstart = () => setReadAloudStatus(button, "Reading aloud.");
        utterance.onend = () => setReadAloudStatus(button, "Read aloud finished.");
        utterance.onerror = () => setReadAloudStatus(button, "Read aloud stopped.");
        window.speechSynthesis.speak(utterance);
      });
    });
  }

  function syncDisclosureButton(button, target) {
    const isOpen = !target.hidden;
    button.setAttribute("aria-expanded", isOpen ? "true" : "false");
    button.textContent = isOpen
      ? button.dataset.labelHide || "Hide"
      : button.dataset.labelShow || "Show";
  }

  function enhanceDisclosures() {
    document.querySelectorAll("[data-disclosure-target]").forEach((button) => {
      const targetId = button.dataset.disclosureTarget;
      if (!targetId) {
        return;
      }

      const target = document.getElementById(targetId);
      if (!target) {
        return;
      }

      target.hidden = true;
      syncDisclosureButton(button, target);

      button.addEventListener("click", () => {
        target.hidden = !target.hidden;
        syncDisclosureButton(button, target);
      });
    });
  }

  function clearEvidenceTarget() {
    if (!activeEvidenceTarget) {
      return;
    }
    activeEvidenceTarget.classList.remove("is-targeted");
    activeEvidenceTarget = null;
  }

  function targetEvidenceCard(targetId, focus = false) {
    if (!targetId) {
      clearEvidenceTarget();
      return;
    }

    const nextTarget = document.getElementById(targetId);
    if (!nextTarget || !nextTarget.classList.contains("evidence-item")) {
      clearEvidenceTarget();
      return;
    }

    if (activeEvidenceTarget && activeEvidenceTarget !== nextTarget) {
      activeEvidenceTarget.classList.remove("is-targeted");
    }

    activeEvidenceTarget = nextTarget;
    activeEvidenceTarget.classList.add("is-targeted");

    if (focus) {
      activeEvidenceTarget.focus({ preventScroll: true });
    }
  }

  function enhanceCitationTargets() {
    const applyCurrentHash = (focus = false) => {
      const hash = window.location.hash.replace(/^#/, "");
      if (!hash) {
        clearEvidenceTarget();
        return;
      }
      targetEvidenceCard(decodeURIComponent(hash), focus);
    };

    document.addEventListener("click", (event) => {
      const link = event.target.closest(".citation-link");
      if (!link) {
        return;
      }

      const targetId = link.dataset.evidenceTarget;
      if (!targetId) {
        return;
      }

      window.requestAnimationFrame(() => {
        targetEvidenceCard(targetId, true);
      });
    });

    window.addEventListener("hashchange", () => applyCurrentHash(true));
    applyCurrentHash(false);
  }

  function enhanceAutofocus() {
    const focusTargetId = document.body.dataset.focusTarget;
    if (!focusTargetId) {
      return;
    }

    const target = document.getElementById(focusTargetId);
    if (!(target instanceof HTMLElement)) {
      return;
    }

    const focusTarget = (attempt = 0) => {
      target.scrollIntoView({ block: "start", inline: "nearest" });
      target.focus({ preventScroll: true });
      if (document.activeElement === target || attempt >= 3) {
        return;
      }
      window.setTimeout(() => {
        focusTarget(attempt + 1);
      }, 60);
    };

    window.requestAnimationFrame(() => {
      focusTarget();
    });
  }

  function updateDropzoneLabel(dropzone, input, label) {
    if (!label) {
      return;
    }

    const [file] = Array.from(input.files || []);
    label.textContent = file ? file.name : dropzoneDefaultLabel;
    dropzone.classList.toggle("upload-surface--selected", Boolean(file));
  }

  function enhanceDropzones() {
    document.querySelectorAll("[data-dropzone]").forEach((dropzone) => {
      const input = dropzone.querySelector('input[type="file"]');
      const label = dropzone.querySelector("[data-dropzone-label]");
      if (!(input instanceof HTMLInputElement)) {
        return;
      }

      let dragDepth = 0;

      const clearDragState = () => {
        dragDepth = 0;
        dropzone.classList.remove("drag-over");
      };

      dropzone.addEventListener("dragenter", (event) => {
        event.preventDefault();
        dragDepth += 1;
        dropzone.classList.add("drag-over");
      });

      dropzone.addEventListener("dragover", (event) => {
        event.preventDefault();
        dropzone.classList.add("drag-over");
      });

      dropzone.addEventListener("dragleave", (event) => {
        event.preventDefault();
        dragDepth = Math.max(0, dragDepth - 1);
        if (dragDepth === 0) {
          dropzone.classList.remove("drag-over");
        }
      });

      dropzone.addEventListener("drop", (event) => {
        event.preventDefault();
        clearDragState();
        const files = event.dataTransfer?.files;
        if (!files || files.length === 0) {
          return;
        }

        input.files = files;
        updateDropzoneLabel(dropzone, input, label);
      });

      input.addEventListener("change", () => {
        updateDropzoneLabel(dropzone, input, label);
        if (input.files && input.files.length > 0) {
          dropzone.closest("form").submit();
        }
      });

      updateDropzoneLabel(dropzone, input, label);
    });
  }

  detectMathMLSupport();
  enhanceA11yToolbar();
  enhanceStatusForms();
  enhanceReadableMode();
  enhanceReadAloud();
  enhanceDisclosures();
  enhanceCitationTargets();
  enhanceDropzones();
  enhanceAutofocus();
})();
