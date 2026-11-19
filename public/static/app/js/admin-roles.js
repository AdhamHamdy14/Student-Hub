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
}

document.addEventListener("DOMContentLoaded", initializeAccountDialog);
