(function () {
  const user = CitechsAPI.requireRole(["admin", "technician"]);
  if (!user) return;

  document.getElementById("tech-user-label").textContent = `${user.displayName} (${user.role})`;
  if (user.role === "admin") {
    document.getElementById("admin-link").hidden = false;
  }

  document.getElementById("logout-btn").addEventListener("click", async () => {
    await CitechsAPI.logout();
    window.location.href = "staff-login.html";
  });

  const ticketList = document.getElementById("ticket-list");
  const statusFilter = document.getElementById("status-filter");
  const chatEmpty = document.getElementById("chat-empty");
  const chatActive = document.getElementById("chat-active");
  const messageList = document.getElementById("message-list");
  const chatTitle = document.getElementById("chat-title");
  const chatMeta = document.getElementById("chat-meta");
  const replyForm = document.getElementById("reply-form");
  const replyBody = document.getElementById("reply-body");
  const closeBtn = document.getElementById("close-ticket-btn");
  const reopenBtn = document.getElementById("reopen-ticket-btn");

  let selectedTicketId = null;
  let lastMessageId = 0;
  let pollTimer = null;

  async function loadTickets() {
    const status = statusFilter.value;
    const data = await CitechsAPI.listTickets(status || undefined);
    if (!data.tickets.length) {
      ticketList.innerHTML = `<li class="ticket-empty">No tickets found.</li>`;
      return;
    }
    ticketList.innerHTML = data.tickets
      .map((ticket) => {
        const active = ticket.id === selectedTicketId ? "active" : "";
        return `
          <li>
            <button type="button" class="ticket-item ${active}" data-id="${escapeHtml(ticket.id)}">
              <strong>${escapeHtml(ticket.id)}</strong>
              <span>${escapeHtml(ticket.subject)}</span>
              <small>${escapeHtml(ticket.priority)} · ${escapeHtml(ticket.status)} · ${escapeHtml(ticket.fullName)}</small>
            </button>
          </li>`;
      })
      .join("");
  }

  async function openTicket(ticketId) {
    selectedTicketId = ticketId;
    lastMessageId = 0;
    messageList.innerHTML = "";
    chatEmpty.hidden = true;
    chatActive.hidden = false;

    const data = await CitechsAPI.getMessages(ticketId);
    const ticket = data.ticket;
    chatTitle.textContent = `${ticket.id} — ${ticket.subject}`;
    chatMeta.textContent = `${ticket.fullName} (${ticket.role}) · ${ticket.location} · ${ticket.category} · ${ticket.priority} · ${ticket.status}`;
    const closed = ticket.status === "closed";
    closeBtn.hidden = closed;
    reopenBtn.hidden = !closed;
    replyBody.disabled = closed;
    replyForm.querySelector("button").disabled = closed;
    appendMessages(data.messages);
    await loadTickets();
    startPolling();
  }

  function appendMessages(messages) {
    messages.forEach((msg) => {
      lastMessageId = Math.max(lastMessageId, msg.id);
      const el = document.createElement("div");
      el.className = `bubble bubble-${msg.senderType}`;
      el.innerHTML = `
        <div class="bubble-meta">${escapeHtml(msg.senderName)} · ${escapeHtml(formatDate(msg.createdAt))}</div>
        <div class="bubble-body">${escapeHtml(msg.body)}</div>`;
      messageList.appendChild(el);
    });
    if (messages.length) {
      messageList.scrollTop = messageList.scrollHeight;
    }
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      if (!selectedTicketId) return;
      try {
        const data = await CitechsAPI.getMessages(selectedTicketId, { afterId: lastMessageId });
        appendMessages(data.messages);
      } catch {
        /* keep polling */
      }
    }, 2500);
  }

  ticketList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-id]");
    if (!button) return;
    openTicket(button.dataset.id).catch((err) => window.alert(err.message));
  });

  replyForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!selectedTicketId) return;
    const body = replyBody.value.trim();
    if (!body) return;
    try {
      const data = await CitechsAPI.sendMessage(selectedTicketId, body);
      replyBody.value = "";
      appendMessages([data.message]);
    } catch (err) {
      window.alert(err.message || "Failed to send");
    }
  });

  closeBtn.addEventListener("click", async () => {
    if (!selectedTicketId) return;
    if (!window.confirm("Close this ticket?")) return;
    try {
      await CitechsAPI.closeTicket(selectedTicketId);
      await openTicket(selectedTicketId);
      await loadTickets();
    } catch (err) {
      window.alert(err.message || "Failed to close ticket");
    }
  });

  reopenBtn.addEventListener("click", async () => {
    if (!selectedTicketId) return;
    try {
      await CitechsAPI.reopenTicket(selectedTicketId);
      await openTicket(selectedTicketId);
      await loadTickets();
    } catch (err) {
      window.alert(err.message || "Failed to reopen ticket");
    }
  });

  document.getElementById("refresh-tickets").addEventListener("click", () => {
    loadTickets().catch((err) => window.alert(err.message));
  });
  statusFilter.addEventListener("change", () => {
    loadTickets().catch((err) => window.alert(err.message));
  });

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatDate(value) {
    try {
      return new Date(value).toLocaleString();
    } catch {
      return value;
    }
  }

  loadTickets().catch((err) => {
    ticketList.innerHTML = `<li class="ticket-empty">${escapeHtml(err.message)}</li>`;
  });
})();
