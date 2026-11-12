(function () {
  const user = CitechsAPI.requireRole(["admin"]);
  if (!user) return;

  document.getElementById("admin-user-label").textContent = `${user.displayName} (admin)`;

  document.getElementById("logout-btn").addEventListener("click", async () => {
    await CitechsAPI.logout();
    window.location.href = "staff-login.html";
  });

  const passwordForm = document.getElementById("password-form");
  const passwordMsg = document.getElementById("password-msg");
  passwordForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    passwordMsg.hidden = true;
    const currentPassword = passwordForm.currentPassword.value;
    const newPassword = passwordForm.newPassword.value;
    const confirmPassword = passwordForm.confirmPassword.value;
    if (newPassword !== confirmPassword) {
      passwordMsg.hidden = false;
      passwordMsg.className = "form-status is-error";
      passwordMsg.textContent = "New passwords do not match.";
      return;
    }
    try {
      const data = await CitechsAPI.changePassword(currentPassword, newPassword);
      CitechsAPI.setSession(data.token, user);
      passwordForm.reset();
      passwordMsg.hidden = false;
      passwordMsg.className = "form-status is-success";
      passwordMsg.textContent = "Password updated successfully.";
    } catch (err) {
      passwordMsg.hidden = false;
      passwordMsg.className = "form-status is-error";
      passwordMsg.textContent = err.message || "Could not update password.";
    }
  });

  const techForm = document.getElementById("tech-form");
  const techMsg = document.getElementById("tech-msg");
  const tableBody = document.getElementById("tech-table-body");

  async function loadTechnicians() {
    tableBody.innerHTML = `<tr><td colspan="5">Loading…</td></tr>`;
    try {
      const data = await CitechsAPI.listTechnicians();
      if (!data.technicians.length) {
        tableBody.innerHTML = `<tr><td colspan="5">No technicians yet. Create one above.</td></tr>`;
        return;
      }
      tableBody.innerHTML = data.technicians
        .map((tech) => {
          const status = tech.active ? "Active" : "Disabled";
          return `
            <tr data-id="${tech.id}">
              <td>${escapeHtml(tech.username)}</td>
              <td>${escapeHtml(tech.displayName)}</td>
              <td><span class="status-pill ${tech.active ? "ok" : "off"}">${status}</span></td>
              <td>${escapeHtml(formatDate(tech.createdAt))}</td>
              <td class="actions-cell">
                <button type="button" class="btn btn-ghost btn-tiny" data-action="toggle">${tech.active ? "Disable" : "Enable"}</button>
                <button type="button" class="btn btn-ghost btn-tiny" data-action="reset">Reset password</button>
                <button type="button" class="btn btn-ghost btn-tiny danger" data-action="delete">Delete</button>
              </td>
            </tr>`;
        })
        .join("");
    } catch (err) {
      tableBody.innerHTML = `<tr><td colspan="5">${escapeHtml(err.message || "Failed to load")}</td></tr>`;
    }
  }

  techForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    techMsg.hidden = true;
    try {
      await CitechsAPI.createTechnician({
        username: techForm.techUsername.value.trim(),
        displayName: techForm.techDisplayName.value.trim(),
        password: techForm.techPassword.value,
      });
      techForm.reset();
      techMsg.hidden = false;
      techMsg.className = "form-status is-success";
      techMsg.textContent = "Technician created.";
      await loadTechnicians();
    } catch (err) {
      techMsg.hidden = false;
      techMsg.className = "form-status is-error";
      techMsg.textContent = err.message || "Could not create technician.";
    }
  });

  tableBody.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const row = button.closest("tr[data-id]");
    const id = Number(row.dataset.id);
    const action = button.dataset.action;

    try {
      if (action === "toggle") {
        const currentlyActive = button.textContent.trim() === "Disable";
        await CitechsAPI.updateTechnician(id, { active: !currentlyActive });
      } else if (action === "reset") {
        const password = window.prompt("Enter a new temporary password (min 8 characters):");
        if (!password) return;
        await CitechsAPI.updateTechnician(id, { password });
        window.alert("Password reset.");
      } else if (action === "delete") {
        if (!window.confirm("Delete this technician account?")) return;
        await CitechsAPI.deleteTechnician(id);
      }
      await loadTechnicians();
    } catch (err) {
      window.alert(err.message || "Action failed.");
    }
  });

  document.getElementById("refresh-techs").addEventListener("click", loadTechnicians);

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

  loadTechnicians();
})();
