(function () {
  const form = document.getElementById("login-form");
  const errorEl = document.getElementById("login-error");

  const existing = CitechsAPI.getUser();
  if (CitechsAPI.getToken() && existing) {
    window.location.href = existing.role === "admin" ? "admin.html" : "technician.html";
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.hidden = true;
    errorEl.textContent = "";

    const username = form.username.value.trim();
    const password = form.password.value;
    if (!username || !password) {
      errorEl.hidden = false;
      errorEl.textContent = "Enter username and password.";
      return;
    }

    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = "Signing in…";

    try {
      const data = await CitechsAPI.login(username, password);
      window.location.href = data.user.role === "admin" ? "admin.html" : "technician.html";
    } catch (err) {
      errorEl.hidden = false;
      errorEl.textContent = err.message || "Login failed.";
      button.disabled = false;
      button.textContent = "Sign in";
    }
  });
})();
