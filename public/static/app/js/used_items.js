/* =========================================================
   STUDENT HUB - USED ITEMS INTERACTIONS (used_items.js)
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {
  // 1. Listing Option toggle (Free Donation vs For Sale + Price input)
  const typeBoxes = document.querySelectorAll("[data-type-box]");
  const priceFieldLabel = document.getElementById("priceFieldLabel");
  const priceInput = document.getElementById("priceInput");

  typeBoxes.forEach((box) => {
    const radio = box.querySelector('input[type="radio"]');
    if (!radio) return;

    radio.addEventListener("change", () => {
      typeBoxes.forEach((b) => b.classList.remove("selected-free", "selected-sale"));
      const isSale = radio.value === "sale";
      box.classList.add(isSale ? "selected-sale" : "selected-free");

      if (priceFieldLabel) {
        priceFieldLabel.textContent = isSale ? "Price (EGP) *" : "Price (Free Donation)";
      }
      if (priceInput) {
        priceInput.disabled = !isSale;
        priceInput.required = isSale;
        priceInput.placeholder = isSale ? "e.g., 250" : "0 EGP (Free)";
        if (isSale) {
          priceInput.focus();
        } else {
          priceInput.value = "";
        }
      }
    });
  });

  // 2. Anonymous toggle live preview
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

  // 3. WhatsApp mode toggle (Account number vs Temporary number)
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

  // 5. Confirmation prompt for Delete & Mark as Sold / Given Away
  document.querySelectorAll(".js-confirm-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const msg = form.getAttribute("data-confirm") || "Are you sure?";
      if (!window.confirm(msg)) {
        event.preventDefault();
      }
    });
  });
});