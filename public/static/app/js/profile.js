function initializeProfilePage() {
  const file = document.getElementById("photo-file");
  const photoForm = document.getElementById("photo-form");
  const photoError = document.getElementById("photo-error");

  const openPhotoPicker = () => file?.click();
  document.getElementById("upload")?.addEventListener("click", openPhotoPicker);
  document.getElementById("photo-edit")?.addEventListener("click", openPhotoPicker);

  file?.addEventListener("change", () => {
    const selectedFile = file.files?.[0];
    if (!selectedFile) return;

    if (!["image/png", "image/jpeg"].includes(selectedFile.type) || selectedFile.size > 2 * 1024 * 1024) {
      photoError.textContent = "Choose a JPG or PNG photo up to 2MB.";
      photoError.hidden = false;
      file.value = "";
      return;
    }

    photoError.hidden = true;
    photoForm?.requestSubmit();
  });

  document.getElementById("remove")?.addEventListener("click", (event) => {
    if (!window.confirm("Remove your profile photo?")) event.preventDefault();
  });

  document.getElementById("focus-backup")?.addEventListener("click", () => {
    document.getElementById("backup-email")?.focus();
  });

  document.querySelectorAll(".toggle[data-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.target);
      if (!(input instanceof HTMLInputElement)) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      const label = button.getAttribute("aria-label") || "";
      button.setAttribute("aria-label", `${show ? "Hide" : "Show"}${label.replace(/^(Show|Hide)/, "")}`);
    });
  });

  document.querySelector(".security")?.addEventListener("submit", (event) => {
    const newPassword = document.getElementById("new");
    const confirmPassword = document.getElementById("confirm");
    if (!(newPassword instanceof HTMLInputElement) || !(confirmPassword instanceof HTMLInputElement)) return;

    newPassword.setCustomValidity(/[0-9\W_]/.test(newPassword.value) ? "" : "Include at least 1 number or symbol.");
    confirmPassword.setCustomValidity(
      newPassword.value === confirmPassword.value ? "" : "Passwords do not match.",
    );
    if (!newPassword.reportValidity() || !confirmPassword.reportValidity()) {
      event.preventDefault();
    }
  });
}

document.addEventListener("DOMContentLoaded", initializeProfilePage);
