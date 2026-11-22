/* =========================================================
   STUDENT HUB - CAMPUS EVENTS INTERACTIONS (events.js)
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {
  // 1. Prefetch event details on hover for faster navigation
  const prefetched = new Set();
  document.querySelectorAll('.event-card a[href*="/events/"]').forEach((link) => {
    const prefetch = () => {
      const url = link.href;
      if (prefetched.has(url)) return;
      prefetched.add(url);

      const hint = document.createElement("link");
      hint.rel = "prefetch";
      hint.href = url;
      document.head.appendChild(hint);
    };

    link.addEventListener("mouseenter", prefetch, { passive: true });
    link.addEventListener("touchstart", prefetch, { passive: true });
  });

  // 2. Prevent duplicate registration submission on details page
  const registerForm = document.querySelector(".register-form");
  if (registerForm) {
    registerForm.addEventListener("submit", () => {
      const submitBtn = registerForm.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Reserving your seat...";
      }
    });
  }

  // 3. Copy Pass Summary button on confirmation page
  const ticketBox = document.querySelector(".ticket-box");
  if (ticketBox) {
    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "btn-event-secondary";
    copyBtn.style.marginTop = "8px";
    copyBtn.style.width = "100%";
    copyBtn.textContent = "Copy Pass Summary";

    copyBtn.addEventListener("click", async () => {
      const rows = Array.from(ticketBox.querySelectorAll(".ticket-row"))
        .map((row) => {
          const label = row.querySelector(".ticket-label")?.textContent.trim() || "";
          const value =
            row.querySelector(".ticket-value")?.textContent.replace(/\s+/g, " ").trim() || "";
          return `${label}: ${value}`;
        })
        .join("\n");

      try {
        await navigator.clipboard.writeText(`Student Hub FOE-AU Event Pass\n${rows}`);
        copyBtn.textContent = "✓ Copied to Clipboard";
        setTimeout(() => {
          copyBtn.textContent = "Copy Pass Summary";
        }, 2000);
      } catch {
        copyBtn.textContent = "Unable to copy";
      }
    });

    ticketBox.appendChild(copyBtn);
  }

  // 4. Confirmation prompt for Cancel Registration
  document.querySelectorAll(".js-confirm-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const msg =
        form.getAttribute("data-confirm") ||
        "Are you sure you want to cancel your registration for this event?";
      if (!window.confirm(msg)) {
        event.preventDefault();
      }
    });
  });
});