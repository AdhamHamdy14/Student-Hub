function initializePasswordToggle() {
  const passwordInput = document.querySelector("#password");
  const toggleButton = document.querySelector("[data-password-toggle]");

  if (
    !(passwordInput instanceof HTMLInputElement)
    || !(toggleButton instanceof HTMLButtonElement)
  ) {
    return;
  }

  toggleButton.addEventListener("click", () => {
    const shouldShowPassword = passwordInput.type === "password";
    passwordInput.type = shouldShowPassword ? "text" : "password";
    toggleButton.textContent = shouldShowPassword ? "Hide" : "Show";
    toggleButton.setAttribute(
      "aria-label",
      `${shouldShowPassword ? "Hide" : "Show"} password`,
    );
    toggleButton.setAttribute("aria-pressed", String(shouldShowPassword));
  });
}

document.addEventListener("DOMContentLoaded", initializePasswordToggle);
