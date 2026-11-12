(function () {
  const yearEl = document.getElementById("year");
  if (yearEl) {
    yearEl.textContent = String(new Date().getFullYear());
  }

  const nav = document.getElementById("site-nav");
  const toggle = document.querySelector(".nav-toggle");
  if (nav && toggle) {
    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    });

    nav.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        nav.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
        toggle.setAttribute("aria-label", "Open menu");
      });
    });
  }

  const search = document.getElementById("kb-search");
  if (search) {
    const sections = Array.from(document.querySelectorAll(".kb-section"));
    const empty = document.querySelector(".kb-empty");

    const filterKnowledge = () => {
      const query = search.value.trim().toLowerCase();
      let visible = 0;

      sections.forEach((section) => {
        const tags = (section.getAttribute("data-tags") || "").toLowerCase();
        const text = section.textContent.toLowerCase();
        const match = !query || tags.includes(query) || text.includes(query);
        section.classList.toggle("is-hidden", !match);
        if (match) visible += 1;
      });

      if (empty) {
        empty.hidden = visible > 0;
      }
    };

    search.addEventListener("input", filterKnowledge);
  }

  const STORAGE_KEY = "citechs_tickets_local";

  function readTickets() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  }

  function writeTickets(tickets) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tickets));
  }

  function renderRecentTickets() {
    const list = document.getElementById("ticket-list");
    const panel = document.getElementById("recent-tickets");
    if (!list || !panel) return;

    const tickets = readTickets().slice(0, 5);
    if (!tickets.length) {
      panel.hidden = true;
      return;
    }

    panel.hidden = false;
    list.innerHTML = tickets
      .map((ticket) => {
        const chatLink = ticket.chatUrl
          ? `<br /><a href="${escapeHtml(ticket.chatUrl)}">Open chat</a>`
          : "";
        return `
        <li>
          <strong>${escapeHtml(ticket.id)}</strong><br />
          ${escapeHtml(ticket.subject)}<br />
          <span class="muted">${escapeHtml(ticket.category)} · ${escapeHtml(ticket.priority)}</span>
          ${chatLink}
        </li>`;
      })
      .join("");
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  const form = document.getElementById("support-form");
  if (form) {
    renderRecentTickets();

    const clearErrors = () => {
      form.querySelectorAll(".field").forEach((field) => field.classList.remove("has-error"));
      form.querySelectorAll(".field-error").forEach((el) => {
        el.hidden = true;
        el.textContent = "";
      });
    };

    const showError = (name, message) => {
      const field = form.querySelector(`[name="${name}"]`)?.closest(".field");
      const error = form.querySelector(`[data-error-for="${name}"]`);
      if (field) field.classList.add("has-error");
      if (error) {
        error.hidden = false;
        error.textContent = message;
      }
    };

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      clearErrors();

      const data = new FormData(form);
      const values = Object.fromEntries(data.entries());
      let valid = true;

      const required = [
        "fullName",
        "role",
        "email",
        "location",
        "category",
        "priority",
        "subject",
        "description",
      ];
      required.forEach((name) => {
        if (!String(values[name] || "").trim()) {
          showError(name, "This field is required.");
          valid = false;
        }
      });

      const email = String(values.email || "").trim();
      if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        showError("email", "Enter a valid email address.");
        valid = false;
      }

      if (!valid) return;

      const submitBtn = form.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      submitBtn.textContent = "Submitting…";

      try {
        if (!window.CitechsAPI) {
          throw new Error("Support server is not loaded. Run server.py and refresh.");
        }

        const result = await CitechsAPI.createTicket({
          fullName: values.fullName.trim(),
          schoolId: String(values.schoolId || "").trim(),
          role: values.role,
          email: email,
          phone: String(values.phone || "").trim(),
          location: values.location.trim(),
          category: values.category,
          priority: values.priority,
          subject: values.subject.trim(),
          description: values.description.trim(),
        });

        const ticket = {
          id: result.ticket.id,
          subject: result.ticket.subject,
          category: result.ticket.category,
          priority: result.ticket.priority,
          chatUrl: result.chatUrl,
          createdAt: new Date().toLocaleString(),
        };
        const tickets = readTickets();
        tickets.unshift(ticket);
        writeTickets(tickets.slice(0, 25));

        form.reset();
        renderRecentTickets();

        const success = document.getElementById("form-success");
        const ticketId = document.getElementById("ticket-id");
        const chatLink = document.getElementById("chat-link");
        if (ticketId) ticketId.textContent = ticket.id;
        if (chatLink) {
          chatLink.href = result.chatUrl;
          chatLink.hidden = false;
        }
        if (success) {
          success.hidden = false;
          success.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      } catch (err) {
        const note = document.getElementById("submit-error");
        if (note) {
          note.hidden = false;
          note.textContent =
            err.message ||
            "Could not submit ticket. Make sure the CITECHS server is running (python server.py).";
        } else {
          window.alert(err.message || "Could not submit ticket.");
        }
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Submit request";
      }
    });
  }
})();
