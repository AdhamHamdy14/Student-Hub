document.addEventListener("DOMContentLoaded", () => {
  const markReadBtn = document.getElementById("markAllReadBtn");
  const unreadBadge = document.getElementById("notifUnreadBadge");
  const notifCards = document.querySelectorAll("#notificationsList .notif");

  if (!markReadBtn) return;

  markReadBtn.addEventListener("click", async () => {
    const endpoint = markReadBtn.getAttribute("data-url");
    const csrfToken = markReadBtn.getAttribute("data-csrf") || "";
    if (!endpoint || markReadBtn.disabled) return;

    markReadBtn.disabled = true;

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRF-Token": csrfToken,
        },
      });

      if (response.ok) {
        if (unreadBadge) {
          unreadBadge.hidden = true;
        }
        notifCards.forEach((card) => {
          card.classList.remove("notif-blue", "notif-green", "notif-amber", "notif-purple");
          card.classList.add("is-read");
        });
      } else {
        markReadBtn.disabled = false;
      }
    } catch {
      markReadBtn.disabled = false;
    }
  });
});