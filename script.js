const revealables = document.querySelectorAll('.reveal');
const prefersReducedMotion = window.matchMedia(
  '(prefers-reduced-motion: reduce)',
).matches;

if ('IntersectionObserver' in window) {
  const observer = new IntersectionObserver(
    entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    },
    {
      threshold: 0.18,
      rootMargin: '0px 0px -8% 0px',
    },
  );

  revealables.forEach(node => observer.observe(node));
} else {
  revealables.forEach(node => node.classList.add('is-visible'));
}

const parallaxStage = document.querySelector('[data-parallax-stage]');
const parallaxCards = parallaxStage
  ? Array.from(parallaxStage.querySelectorAll('[data-depth]'))
  : [];

if (parallaxStage && parallaxCards.length > 0 && !prefersReducedMotion) {
  const resetCards = () => {
    parallaxCards.forEach(card => {
      card.style.transform = '';
    });
  };

  parallaxStage.addEventListener('pointermove', event => {
    const rect = parallaxStage.getBoundingClientRect();
    const px = (event.clientX - rect.left) / rect.width - 0.5;
    const py = (event.clientY - rect.top) / rect.height - 0.5;

    parallaxCards.forEach(card => {
      const depth = Number(card.getAttribute('data-depth') || 0);
      const x = px * depth;
      const y = py * depth * 0.6;

      if (card.classList.contains('phone-card--primary')) {
        card.style.transform =
          `rotate(-5deg) translateX(0.6rem) translate3d(${x}px, ${y}px, 0)`;
        return;
      }

      card.style.transform =
        `rotate(9deg) translate(6.5rem, 10rem) translate3d(${x}px, ${y}px, 0)`;
    });
  });

  parallaxStage.addEventListener('pointerleave', resetCards);
}
