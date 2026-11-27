function initializeAccountDialog() {
  document.querySelectorAll("dialog.role-create-dialog").forEach((dialog) => {
    if (!(dialog instanceof HTMLDialogElement)) return;

    const roleSelect = dialog.querySelector('select[name="role"]');
    const departmentSelect = dialog.querySelector('select[name="department"]');
    roleSelect?.addEventListener("change", () => {
      if (roleSelect.value.startsWith("ta:") && departmentSelect) {
        departmentSelect.value = roleSelect.value.slice("ta:".length);
      }
    });

    dialog.querySelectorAll("[data-close-dialog]").forEach((button) => {
      button.addEventListener("click", () => dialog.close());
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  document.querySelector(".role-create-trigger")?.addEventListener("click", () => {
    document.querySelector("#create-account-dialog")?.showModal();
  });
  document.querySelectorAll("[data-edit-dialog]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      const dialogId = trigger.getAttribute("data-edit-dialog");
      const dialog = dialogId && document.getElementById(dialogId);
      if (dialog instanceof HTMLDialogElement) dialog.showModal();
    });
  });

  const search = document.querySelector("#account-search");
  const roleFilter = document.querySelector("#account-role-filter");
  const accountRows = [...document.querySelectorAll("[data-account-row]")];
  const accountCount = document.querySelector("[data-account-count]");
  const emptyState = document.querySelector("[data-empty-state]");

  const filterAccounts = () => {
    const searchTerm = search?.value.trim().toLowerCase() || "";
    const selectedRole = roleFilter?.value || "";
    let visibleCount = 0;

    accountRows.forEach((row) => {
      const matchesSearch = row.dataset.accountSearch
        .toLowerCase()
        .includes(searchTerm);
      const matchesRole = !selectedRole || row.dataset.accountRole === selectedRole;
      const isVisible = matchesSearch && matchesRole;
      row.hidden = !isVisible;
      if (isVisible) visibleCount += 1;
    });

    if (accountCount) {
      accountCount.textContent = `${visibleCount} ${visibleCount === 1 ? "account" : "accounts"}`;
    }
    if (emptyState) emptyState.hidden = visibleCount > 0;
  };

  search?.addEventListener("input", filterAccounts);
  roleFilter?.addEventListener("change", filterAccounts);

  document.querySelectorAll("[data-confirm-delete]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const accountName = form.getAttribute("data-confirm-delete");
      if (!window.confirm(`Delete the account for "${accountName}" and its related data?`)) {
        event.preventDefault();
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", initializeAccountDialog);
