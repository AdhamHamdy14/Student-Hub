/* =========================================================
   STUDENT HUB - EVENTS MODULE SCRIPTS (events.js)
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {
  initEventsFeed();
  initEventDetails();
  initEventConfirmation();
});

/**
 * 1. Events Feed Page (events.html)
 * Handles instant search, category pill filtering, and no-results messaging.
 */
function initEventsFeed() {
  const searchInput = document.getElementById("eventSearchInput");
  const filterButtons = document.querySelectorAll(".filter-pill");
  const eventsGrid = document.getElementById("eventsGrid");

  if (!eventsGrid) return;

  let activeCategory = "all";

  // Create dynamic "no matching events" message if not already in DOM
  let noResultsBox = document.getElementById("noMatchingEvents");
  if (!noResultsBox) {
    noResultsBox = document.createElement("div");
    noResultsBox.id = "noMatchingEvents";
    noResultsBox.className = "empty-state-card";
    noResultsBox.style.display = "none";
    noResultsBox.innerHTML = `
      <h3>No matching events found</h3>
      <p>Try adjusting your search keywords or switching category filters.</p>
    `;
    eventsGrid.parentNode.insertBefore(noResultsBox, eventsGrid.nextSibling);
  }

  function applyFilters() {
    const query = searchInput ? searchInput.value.toLowerCase().trim() : "";
    const cards = eventsGrid.querySelectorAll(".event-card");
    let visibleCount = 0;

    cards.forEach((card) => {
      const cardCategory = (card.getAttribute("data-category") || "").toLowerCase();
      const cardSearchText = (card.getAttribute("data-search") || "").toLowerCase();

      const matchesCategory =
        activeCategory === "all" || cardCategory === activeCategory.toLowerCase();
      const matchesQuery = !query || cardSearchText.includes(query);

      if (matchesCategory && matchesQuery) {
        card.style.display = "flex";
        visibleCount++;
      } else {
        card.style.display = "none";
      }
    });

    noResultsBox.style.display = visibleCount === 0 && cards.length > 0 ? "block" : "none";
  }

  // Bind category pills
  filterButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      filterButtons.forEach((pill) => pill.classList.remove("active"));
      btn.classList.add("active");
      activeCategory = btn.getAttribute("data-category") || "all";
      applyFilters();
    });
  });

  // Bind search input
  if (searchInput) {
    searchInput.addEventListener("input", applyFilters);
  }
}

/**
 * 2. Event Details Page (event_details.html)
 * Prevents duplicate form submissions and confirms cancellation actions.
 */
function initEventDetails() {
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

  const cancelForms = document.querySelectorAll('form[action*="/cancel"]');
  cancelForms.forEach((form) => {
    form.addEventListener("submit", (e) => {
      const confirmed = window.confirm(
        "Are you sure you want to cancel your registration for this event?"
      );
      if (!confirmed) {
        e.preventDefault();
      }
    });
  });
}

/**
 * 3. Event Confirmation Page (event_registered.html)
 * Adds a quick "Copy Pass Details" button inside the ticket box.
 */
function initEventConfirmation() {
  const ticketBox = document.querySelector(".ticket-box");
  if (!ticketBox) return;

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
        const value = row.querySelector(".ticket-value")?.textContent.replace(/\s+/g, " ").trim() || "";
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