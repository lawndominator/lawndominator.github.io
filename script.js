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
      const baseTransform =
        getComputedStyle(card).getPropertyValue('--card-transform').trim();

      card.style.transform =
        `${baseTransform} translate3d(${x}px, ${y}px, 0)`;
    });
  });

  parallaxStage.addEventListener('pointerleave', resetCards);
}

const dallasSoilTemp = document.getElementById('dallas-soil-temp');
if (dallasSoilTemp) {
  const soilUrl =
    'https://api.open-meteo.com/v1/forecast?latitude=32.7767&longitude=-96.797' +
    '&hourly=soil_temperature_6cm&temperature_unit=fahrenheit&timezone=America%2FChicago' +
    '&forecast_days=1&past_days=1';

  fetch(soilUrl)
    .then(response => {
      if (!response.ok) throw new Error('soil');
      return response.json();
    })
    .then(data => {
      const times = data.hourly && data.hourly.time;
      const values = data.hourly && data.hourly.soil_temperature_6cm;
      if (!times || !values) throw new Error('soil');
      const now = new Date();
      const stamp = [
        now.getFullYear(),
        String(now.getMonth() + 1).padStart(2, '0'),
        String(now.getDate()).padStart(2, '0'),
      ].join('-') + 'T' + String(now.getHours()).padStart(2, '0');
      let latest = null;
      for (let i = 0; i < times.length; i += 1) {
        if (times[i].slice(0, 13) <= stamp && values[i] != null) latest = values[i];
      }
      if (latest == null) throw new Error('soil');
      dallasSoilTemp.textContent = (Math.round(latest * 10) / 10) + '°F';
    })
    .catch(() => {
      dallasSoilTemp.textContent = 'unavailable';
    });
}
