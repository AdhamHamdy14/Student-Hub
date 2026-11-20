/* =========================================================
   STUDENT HUB - LOST & FOUND INTERACTIONS (lost_found.js)
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {
  // 1. Report Type visual toggle (Found vs Lost)
  const typeBoxes = document.querySelectorAll("[data-type-box]");
  typeBoxes.forEach((box) => {
    const radio = box.querySelector('input[type="radio"]');
    if (!radio) return;

    radio.addEventListener("change", () => {
      typeBoxes.forEach((b) => b.classList.remove("selected-found", "selected-lost"));
      if (radio.value === "found") {
        box.classList.add("selected-found");
      } else {
        box.classList.add("selected-lost");
      }
    });
  });

  // 2. WhatsApp mode toggle (Account number vs Temporary number)
  const waRadios = document.querySelectorAll('input[name="whatsapp_mode"]');
  const waAccountCard = document.getElementById("waAccountCard");
  const waCustomCard = document.getElementById("waCustomCard");
  const tempWhatsappBox = document.getElementById("tempWhatsappBox");
  const tempWhatsappInput = document.getElementById("tempWhatsappInput");

  waRadios.forEach((radio) => {
    radio.addEventListener("change", () => {
      const isCustom = radio.value === "custom";
      if (waAccountCard) waAccountCard.classList.toggle("active", !isCustom);
      if (waCustomCard) waCustomCard.classList.toggle("active", isCustom);
      if (tempWhatsappBox) tempWhatsappBox.hidden = !isCustom;
      if (tempWhatsappInput) {
        tempWhatsappInput.required = isCustom;
        if (isCustom) tempWhatsappInput.focus();
      }
    });
  });

  // 3. Anonymous toggle live preview
  const anonCheck = document.getElementById("isAnonymousCheck");
  const previewText = document.getElementById("publisherPreviewText");
  if (anonCheck && previewText) {
    const userName = previewText.dataset.userName || "Student";
    const renderPreview = () => {
      previewText.textContent = "Displayed as: ";
      const strong = document.createElement("strong");
      strong.textContent = anonCheck.checked ? "Anonymous member" : userName;
      previewText.appendChild(strong);
    };
    renderPreview();
    anonCheck.addEventListener("change", renderPreview);
  }

  // 4. Photo file input label update
  const photoInput = document.getElementById("photoInput");
  const photoLabelText = document.getElementById("photoLabelText");
  if (photoInput && photoLabelText) {
    photoInput.addEventListener("change", () => {
      if (photoInput.files && photoInput.files[0]) {
        photoLabelText.textContent = `📷 Selected: ${photoInput.files[0].name}`;
      }
    });
  }

  // 5. Confirmation prompt for Delete & Mark as Returned (Auto-delete)
  document.querySelectorAll(".js-confirm-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const msg = form.getAttribute("data-confirm") || "Are you sure?";
      if (!window.confirm(msg)) {
        event.preventDefault();
      }
    });
  });
});