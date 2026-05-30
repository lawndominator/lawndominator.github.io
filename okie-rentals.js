const equipment = [
  { type: 'Turf removal', name: 'Sod cutter', hourly: 70, image: './okie-equipment-fleet.png' },
  { type: 'Trenching', name: 'Small 18 in. walk-behind trencher', hourly: 65, image: './okie-equipment-fleet.png' },
  { type: 'Trailer', name: 'Dump trailer, tall wall', hourly: 110, image: './okie-equipment-fleet.png' },
  { type: 'Trailer', name: 'Dump trailer, short wall', hourly: 95, image: './okie-equipment-fleet.png' },
  { type: 'Compact equipment', name: 'Mini skid, small', hourly: 100, image: './okie-equipment-fleet.png' },
  { type: 'Compact equipment', name: 'Mini skid, large', hourly: 180, image: './okie-equipment-fleet.png' },
  { type: 'Stump work', name: 'Small stump grinder', hourly: 60, image: './okie-equipment-fleet.png' },
  { type: 'Soil prep', name: 'Tiller', hourly: 65, image: './okie-equipment-fleet.png' },
  { type: 'Topdressing', name: 'Eco 250', hourly: 135, image: './okie-equipment-fleet.png' },
  { type: 'Topdressing', name: 'Earth & Turf 100SP', hourly: 155, image: './okie-equipment-fleet.png' },
  { type: 'Aeration', name: 'Stand-on aerator', hourly: 155, image: './okie-equipment-fleet.png' },
  { type: 'Aeration', name: 'Walk-behind aerator', hourly: 65, image: './okie-equipment-fleet.png' },
  { type: 'Trailer', name: '30 ft. gooseneck', hourly: 125, image: './okie-equipment-fleet.png' },
  { type: 'Trailer', name: '20 ft. equipment hauler, 7K axles', hourly: 110, image: './okie-equipment-fleet.png' },
  { type: 'Trailer', name: '20 ft. car hauler', hourly: 85, image: './okie-equipment-fleet.png' },
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

const stage = document.getElementById('carouselStage');
const dots = document.getElementById('carouselDots');

if (stage && dots) {
  const featured = equipment.slice(0, 8);
  let active = 0;

  stage.innerHTML = featured
    .map(
      item => `
        <article class="okie-carousel__slide">
          <img src="${item.image}" alt="${item.name} available from Okie Equipment Rentals." />
          <div class="okie-carousel__shade"></div>
          <div class="okie-carousel__caption">
            <span>${item.type}</span>
            <strong>${item.name}</strong>
            <small>${money(item.hourly)} per hour</small>
          </div>
        </article>
      `,
    )
    .join('');

  dots.innerHTML = featured.map(() => '<span></span>').join('');
  const slideNodes = Array.from(stage.children);
  const dotNodes = Array.from(dots.children);

  const setSlide = index => {
    const prev = (index - 1 + featured.length) % featured.length;
    const next = (index + 1) % featured.length;

    slideNodes.forEach((slide, slideIndex) => {
      slide.classList.toggle('is-active', slideIndex === index);
      slide.classList.toggle('is-prev', slideIndex === prev);
      slide.classList.toggle('is-next', slideIndex === next);
      slide.classList.toggle(
        'is-back',
        slideIndex !== index && slideIndex !== prev && slideIndex !== next,
      );
    });

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
