(() => {
  const subscribeButton = document.getElementById("subscribe-button");
  const modal = document.getElementById("subscribe-modal");
  const closeButton = document.getElementById("close-modal");
  const googleLink = document.getElementById("google-link");
  const appleLink = document.getElementById("apple-link");
  const otherLink = document.getElementById("other-link");
  let lastFocusedElement = null;

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
    const googleUrl = `https://calendar.google.com/calendar/r?cid=${encodeURIComponent(httpsUrl)}`;
    googleLink.href = googleUrl;
    appleLink.href = webcalUrl;
    otherLink.href = webcalUrl;
  }

  function openModal() {
    lastFocusedElement = document.activeElement;
    updateSubscriptionLinks();
    modal.hidden = false;
    document.body.classList.add("modal-open");
    closeButton.focus();
  }

  function closeModal() {
    modal.hidden = true;
    document.body.classList.remove("modal-open");
    if (lastFocusedElement) {
      lastFocusedElement.focus();
    }
  }

  subscribeButton.addEventListener("click", openModal);
  closeButton.addEventListener("click", closeModal);
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
