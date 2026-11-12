(function () {
  const params = new URLSearchParams(window.location.search);
  const ticketId = params.get("ticket");
  const chatToken = params.get("token");

  const blocked = document.getElementById("chat-blocked");
  const chat = document.getElementById("client-chat");
  const messageList = document.getElementById("client-message-list");
  const title = document.getElementById("client-chat-title");
  const meta = document.getElementById("client-chat-meta");
  const status = document.getElementById("client-status");
  const form = document.getElementById("client-reply-form");
  const bodyInput = document.getElementById("client-reply-body");

  let lastMessageId = 0;

  if (!ticketId || !chatToken) {
    blocked.hidden = false;
    return;
  }

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
    if (messages.length) messageList.scrollTop = messageList.scrollHeight;
  }

  async function bootstrap() {
    try {
      const data = await CitechsAPI.getMessages(ticketId, { chatToken });
      chat.hidden = false;
      title.textContent = `${data.ticket.id} — ${data.ticket.subject}`;
      meta.textContent = `${data.ticket.status.toUpperCase()} · ${data.ticket.category} · ${data.ticket.location}`;
      appendMessages(data.messages);
      if (data.ticket.status === "closed") {
        status.textContent = "Closed";
        status.className = "status-pill off";
        bodyInput.disabled = true;
        form.querySelector("button").disabled = true;
      }
      setInterval(async () => {
        try {
          const poll = await CitechsAPI.getMessages(ticketId, {
            chatToken,
            afterId: lastMessageId,
          });
          appendMessages(poll.messages);
          if (poll.ticket.status === "closed") {
            status.textContent = "Closed";
            status.className = "status-pill off";
            bodyInput.disabled = true;
            form.querySelector("button").disabled = true;
          }
        } catch {
          /* ignore transient errors */
        }
      }, 2500);
    } catch (err) {
      blocked.hidden = false;
      blocked.querySelector("h1").textContent = "Unable to open chat";
      blocked.querySelector("p").textContent =
        err.message || "This chat link is invalid or expired. Please submit a new support request.";
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = bodyInput.value.trim();
    if (!body) return;
    try {
      const data = await CitechsAPI.sendMessage(ticketId, body, chatToken);
      bodyInput.value = "";
      appendMessages([data.message]);
    } catch (err) {
      window.alert(err.message || "Failed to send message");
    }
  });

  bootstrap();
})();
