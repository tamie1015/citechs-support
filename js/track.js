(function () {
  const form = document.getElementById("track-form");
  if (!form) return;

  const result = document.getElementById("track-result");
  const title = document.getElementById("track-result-title");
  const meta = document.getElementById("track-result-meta");
  const chatLink = document.getElementById("track-chat-link");
  const errorEl = document.getElementById("track-error");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.hidden = true;
    result.hidden = true;

    const ticketId = document.getElementById("ticketId").value.trim();
    const email = document.getElementById("email").value.trim();
    if (!ticketId || !email) {
      errorEl.hidden = false;
      errorEl.textContent = "Enter both ticket ID and email.";
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.textContent = "Looking up…";

    try {
      const data = await CitechsAPI.lookupTicket(ticketId, email);
      title.textContent = `${data.ticket.id} — ${data.ticket.status.toUpperCase()}`;
      meta.textContent = `${data.ticket.subject} · ${data.ticket.category} · ${data.ticket.location}`;
      chatLink.href = data.chatUrl;
      result.hidden = false;
      result.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      errorEl.hidden = false;
      errorEl.textContent =
        err.message || "Ticket not found. Check the ID and email, and make sure the CITECHS server is running.";
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Find ticket";
    }
  });
})();
