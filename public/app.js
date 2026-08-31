(() => {
  const subscribeButton = document.getElementById("subscribe-button");
  const modal = document.getElementById("subscribe-modal");
  const closeButton = document.getElementById("close-modal");
  const googleOption = document.getElementById("google-option");
  const appleLink = document.getElementById("apple-link");
  const subscribeOptions = document.querySelector(".subscribe-options");
  const modalPlaceholder = document.getElementById("modal-placeholder");
  const googleGuide = document.getElementById("google-guide");
  const modalTitle = document.getElementById("modal-title");
  const backToOptions = document.getElementById("back-to-options");
  const feedUrl = document.getElementById("feed-url");
  const copyFeedUrlButton = document.getElementById("copy-feed-url");
  const copyFeedback = document.getElementById("copy-feedback");
  let lastFocusedElement = null;
  let feedbackTimeoutId = null;

  function publicCalendarUrl() {
    const calendarUrl = new URL("penya.ics", window.location.href);
    calendarUrl.protocol = "https:";
    calendarUrl.search = "";
    calendarUrl.hash = "";
    return calendarUrl.href;
  }

  function updateSubscriptionLinks() {
    const httpsUrl = publicCalendarUrl();
    const webcalUrl = httpsUrl.replace(/^https:/, "webcal:");
    feedUrl.textContent = httpsUrl;
    appleLink.href = webcalUrl;
  }

  function showOptions() {
    subscribeOptions.hidden = false;
    modalPlaceholder.hidden = false;
    googleGuide.hidden = true;
    googleOption.setAttribute("aria-expanded", "false");
    googleOption.setAttribute("aria-pressed", "false");
    googleOption.classList.remove("is-active");
    modalTitle.textContent = "Tria el teu calendari";
  }

  function showGoogleGuide() {
    subscribeOptions.hidden = false;
    modalPlaceholder.hidden = true;
    googleGuide.hidden = false;
    googleOption.setAttribute("aria-expanded", "true");
    googleOption.setAttribute("aria-pressed", "true");
    googleOption.classList.add("is-active");
    modalTitle.textContent = "Google Calendar";
    backToOptions.focus();
  }

  function returnToOptions() {
    showOptions();
    googleOption.focus();
  }

  async function copyFeedUrl() {
    const url = feedUrl.textContent;
    let copied = false;

    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(url);
        copied = true;
      }
    } catch {
      copied = false;
    }

    if (!copied) {
      const textArea = document.createElement("textarea");
      textArea.value = url;
      textArea.setAttribute("readonly", "");
      textArea.style.position = "fixed";
      textArea.style.opacity = "0";
      document.body.append(textArea);
      textArea.select();
      try {
        copied = document.execCommand("copy");
      } catch {
        copied = false;
      }
      textArea.remove();
    }

    copyFeedback.textContent = copied
      ? "Enllaç copiat"
      : "No s'ha pogut copiar l'enllaç.";
    copyFeedback.hidden = false;
    window.clearTimeout(feedbackTimeoutId);
    feedbackTimeoutId = window.setTimeout(() => {
      copyFeedback.hidden = true;
    }, 2400);
  }

  function openModal() {
    lastFocusedElement = document.activeElement;
    updateSubscriptionLinks();
    showOptions();
    modal.hidden = false;
    document.body.classList.add("modal-open");
    closeButton.focus();
  }

  function closeModal() {
    modal.hidden = true;
    window.clearTimeout(feedbackTimeoutId);
    copyFeedback.hidden = true;
    document.body.classList.remove("modal-open");
    if (lastFocusedElement) {
      lastFocusedElement.focus();
    }
  }

  subscribeButton.addEventListener("click", openModal);
  closeButton.addEventListener("click", closeModal);
  googleOption.addEventListener("click", showGoogleGuide);
  backToOptions.addEventListener("click", returnToOptions);
  copyFeedUrlButton.addEventListener("click", copyFeedUrl);
  modal.addEventListener("click", (event) => {
    if (event.target.hasAttribute("data-close-modal")) {
      closeModal();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      closeModal();
    }
  });
})();
