function initializeMobileNavigation() {
  const navbar = document.querySelector(".navbar");
  const toggle = navbar?.querySelector(".mobile-menu-toggle");
  const menu = navbar?.querySelector("#primary-navigation");
  if (!navbar || !toggle || !menu) return;

  const setOpen = (open, returnFocus = false) => {
    navbar.classList.toggle("menu-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute(
      "aria-label",
      open ? "Close navigation menu" : "Open navigation menu",
    );
    if (returnFocus) toggle.focus();
  };

  toggle.addEventListener("click", () => {
    setOpen(toggle.getAttribute("aria-expanded") !== "true");
  });

  document.addEventListener("click", (event) => {
    if (!navbar.contains(event.target)) setOpen(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
      setOpen(false, true);
    }
  });

  menu.querySelectorAll("a[href]").forEach((link) => {
    link.addEventListener("click", () => setOpen(false));
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 1100) setOpen(false);
  });
}

document.addEventListener("DOMContentLoaded", initializeMobileNavigation);