function initializeAccountDialog() {
  const dialog = document.querySelector("#create-account-dialog");
  const trigger = document.querySelector(".role-create-trigger");
  if (!(dialog instanceof HTMLDialogElement) || !trigger) return;

  const roleSelect = dialog.querySelector("#new-role");
  const departmentSelect = dialog.querySelector("#new-department");
  roleSelect?.addEventListener("change", () => {
    if (roleSelect.value.startsWith("ta:") && departmentSelect) {
      departmentSelect.value = roleSelect.value.slice("ta:".length);
    }
  });

  trigger.addEventListener("click", () => dialog.showModal());
  dialog.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => dialog.close());
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

document.addEventListener("DOMContentLoaded", initializeAccountDialog);
