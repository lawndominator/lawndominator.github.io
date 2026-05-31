const revealObserver = new IntersectionObserver(
  (entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        revealObserver.unobserve(entry.target);
      }
    }
  },
  { threshold: 0.16 }
);

document.querySelectorAll("[data-reveal]").forEach((element) => {
  revealObserver.observe(element);
});

document.querySelector(".lead-form button")?.addEventListener("click", () => {
  const button = document.querySelector(".lead-form button");
  if (!button) return;

  button.textContent = "Request drafted";
  window.setTimeout(() => {
    button.textContent = "Send request";
  }, 2200);
});
