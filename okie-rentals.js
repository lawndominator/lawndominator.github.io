const equipment = [
  { type: 'Turf removal', name: 'Sod cutter', hourly: 70 },
  { type: 'Trenching', name: 'Small 18 in. walk-behind trencher', hourly: 65 },
  { type: 'Trailer', name: 'Dump trailer, tall wall', hourly: 110 },
  { type: 'Trailer', name: 'Dump trailer, short wall', hourly: 95 },
  { type: 'Compact equipment', name: 'Mini skid, small', hourly: 100 },
  { type: 'Compact equipment', name: 'Mini skid, large', hourly: 180 },
  { type: 'Stump work', name: 'Small stump grinder', hourly: 60 },
  { type: 'Soil prep', name: 'Tiller', hourly: 65 },
  { type: 'Topdressing', name: 'Eco 250', hourly: 135 },
  { type: 'Topdressing', name: 'Earth & Turf 100SP', hourly: 155 },
  { type: 'Aeration', name: 'Stand-on aerator', hourly: 155 },
  { type: 'Aeration', name: 'Walk-behind aerator', hourly: 65 },
  { type: 'Trailer', name: '30 ft. gooseneck', hourly: 125 },
  { type: 'Trailer', name: '20 ft. equipment hauler, 7K axles', hourly: 110 },
  { type: 'Trailer', name: '20 ft. car hauler', hourly: 85 },
];

const money = value => `$${value.toLocaleString('en-US')}`;

const rateGrid = document.getElementById('rateGrid');
if (rateGrid) {
  rateGrid.innerHTML = equipment
    .map(
      item => `
        <article class="rate-card">
          <span class="rate-card__type">${item.type}</span>
          <h3>${item.name}</h3>
          <div class="rate-card__price">
            <strong>${money(item.hourly)}</strong>
            <span>/ hr</span>
          </div>
          <div class="rate-card__day">${money(item.hourly * 8)} 8-hour day estimate</div>
        </article>
      `,
    )
    .join('');
}

const slideType = document.getElementById('slideType');
const slideName = document.getElementById('slideName');
const slideRate = document.getElementById('slideRate');
const dots = document.getElementById('carouselDots');

if (slideType && slideName && slideRate && dots) {
  const featured = equipment.slice(0, 8);
  let active = 0;

  dots.innerHTML = featured.map(() => '<span></span>').join('');
  const dotNodes = Array.from(dots.children);

  const setSlide = index => {
    const item = featured[index];
    slideType.textContent = item.type;
    slideName.textContent = item.name;
    slideRate.textContent = `${money(item.hourly)} per hour`;
    dotNodes.forEach((dot, dotIndex) => {
      dot.classList.toggle('is-active', dotIndex === index);
    });
  };

  setSlide(active);

  window.setInterval(() => {
    active = (active + 1) % featured.length;
    setSlide(active);
  }, 3200);
}
