(function (global) {
  const TOKEN_KEY = "citechs_staff_token";
  const USER_KEY = "citechs_staff_user";

  async function request(path, options = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) headers.Authorization = `Bearer ${token}`;

    const response = await fetch(path, {
      ...options,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });

    let data = null;
    const text = await response.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { error: text };
      }
    }

    if (!response.ok) {
      const error = new Error((data && data.error) || "Request failed");
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  const api = {
    TOKEN_KEY,
    USER_KEY,

    getToken() {
      return localStorage.getItem(TOKEN_KEY);
    },

    getUser() {
      try {
        return JSON.parse(localStorage.getItem(USER_KEY) || "null");
      } catch {
        return null;
      }
    },

    setSession(token, user) {
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    },

    clearSession() {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    },

    async login(username, password) {
      const data = await request("/api/auth/login", {
        method: "POST",
        body: { username, password },
      });
      api.setSession(data.token, data.user);
      return data;
    },

    async logout() {
      try {
        await request("/api/auth/logout", { method: "POST", body: {} });
      } catch {
        /* ignore */
      }
      api.clearSession();
    },

    async me() {
      return request("/api/auth/me");
    },

    changePassword(currentPassword, newPassword) {
      return request("/api/admin/change-password", {
        method: "POST",
        body: { currentPassword, newPassword },
      });
    },

    listTechnicians() {
      return request("/api/admin/technicians");
    },

    createTechnician(payload) {
      return request("/api/admin/technicians", { method: "POST", body: payload });
    },

    updateTechnician(id, payload) {
      return request(`/api/admin/technicians/${id}`, { method: "PATCH", body: payload });
    },

    deleteTechnician(id) {
      return request(`/api/admin/technicians/${id}`, { method: "DELETE" });
    },

    createTicket(payload) {
      return request("/api/tickets", { method: "POST", body: payload });
    },

    listTickets(status) {
      const q = status ? `?status=${encodeURIComponent(status)}` : "";
      return request(`/api/tickets${q}`);
    },

    getTicket(id, chatToken) {
      const q = chatToken ? `?chatToken=${encodeURIComponent(chatToken)}` : "";
      return request(`/api/tickets/${encodeURIComponent(id)}${q}`);
    },

    getMessages(ticketId, { chatToken, afterId } = {}) {
      const params = new URLSearchParams();
      if (chatToken) params.set("chatToken", chatToken);
      if (afterId) params.set("afterId", String(afterId));
      const q = params.toString() ? `?${params}` : "";
      return request(`/api/tickets/${encodeURIComponent(ticketId)}/messages${q}`);
    },

    sendMessage(ticketId, body, chatToken) {
      const payload = { body };
      if (chatToken) payload.chatToken = chatToken;
      return request(`/api/tickets/${encodeURIComponent(ticketId)}/messages`, {
        method: "POST",
        body: payload,
      });
    },

    closeTicket(ticketId) {
      return request(`/api/tickets/${encodeURIComponent(ticketId)}/close`, {
        method: "POST",
        body: {},
      });
    },

    reopenTicket(ticketId) {
      return request(`/api/tickets/${encodeURIComponent(ticketId)}/reopen`, {
        method: "POST",
        body: {},
      });
    },

    lookupTicket(ticketId, email) {
      return request("/api/tickets/lookup", {
        method: "POST",
        body: { ticketId, email },
      });
    },

    requireRole(roles) {
      const user = api.getUser();
      const token = api.getToken();
      if (!token || !user || !roles.includes(user.role)) {
        window.location.href = "staff-login.html";
        return null;
      }
      return user;
    },
  };

  global.CitechsAPI = api;
})(window);
