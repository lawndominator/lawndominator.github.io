const products = {
  greens: {
    image: "./assets/pgm22-field-1.jpg",
    alt: "2017 Jacobsen PGM22 Walk Reel",
    title: "2017 Jacobsen PGM22 Walk Reel",
    price: "$4,850.00",
    specs: [
      ["Year", "2017"],
      ["Model", "Jacobsen PGM22"],
      ["Number of blades", "11 blade example reel"],
      ["Cutting width", "22 in. width of cut"],
      ["Height of cut", "0.1 - 1.42"],
      ["Engine hours", "Example hours"],
      ["Included accessories", "Roller, catcher, transport wheels"],
      ["Condition", "Used. Example condition notes for the seller to replace."]
    ]
  },
  eclipse: {
    image: "./assets/eclipse-2-field.jpg",
    alt: "2020 Jacobsen Eclipse 2",
    title: "2020 Jacobsen Eclipse 2",
    price: "$3,950.00",
    specs: [
      ["Year", "2020"],
      ["Model", "Jacobsen Eclipse 2"],
      ["Power", "Battery walk mower example"],
      ["Cutting width", "22 in. width of cut"],
      ["Runtime", "Example runtime"],
      ["Included accessories", "Charger, catcher, roller"],
      ["Condition", "Used. Example listing notes for a real uploaded mower."]
    ]
  },
  pgm: {
    image: "./assets/pgm22-field-2.jpg",
    alt: "2019 Jacobsen PGM 22 Walk Reel",
    title: "2019 Jacobsen PGM 22 Walk Reel",
    price: "$3,650.00",
    specs: [
      ["Year", "2019"],
      ["Model", "Jacobsen PGM 22 example"],
      ["Type", "Walk-behind reel mower"],
      ["Cutting width", "22 in. width of cut"],
      ["Engine hours", "Example hours"],
      ["Included accessories", "Catcher, roller, transport wheels"],
      ["Condition", "Used. Example condition notes for a walk reel mower."]
    ]
  },
  greens2: {
    image: "./assets/pgm22.png",
    alt: "2018 Jacobsen PGM22 Walk Reel",
    title: "2018 Jacobsen PGM22 Walk Reel",
    price: "$5,250.00",
    specs: [
      ["Year", "2018"],
      ["Model", "Jacobsen PGM22 example"],
      ["Number of blades", "Example blade count"],
      ["Cutting width", "22 in. width of cut"],
      ["Engine hours", "Example hours"],
      ["Included accessories", "Example accessories"],
      ["Condition", "Used. Placeholder for seller uploaded listing notes."]
    ]
  }
};

const detailPanel = document.querySelector("#details");
const detailImage = document.querySelector("#detailImage");
const detailTitle = document.querySelector("#detailTitle");
const detailPrice = document.querySelector("#detailPrice");
const detailSpecs = document.querySelector("#detailSpecs");
const detailMessage = document.querySelector("#detailMessage");
const detailThumbs = document.querySelectorAll(".detail-thumb img");

function openProduct(key) {
  const product = products[key];
  if (!product || !detailPanel) return;

  detailImage.src = product.image;
  detailImage.alt = product.alt;
  detailTitle.textContent = product.title;
  detailPrice.textContent = product.price;
  detailMessage.value = `I am interested in the ${product.title}.`;
  detailSpecs.innerHTML = product.specs
    .map(([term, value]) => `<div><dt>${term}:</dt><dd>${value}</dd></div>`)
    .join("");
  detailThumbs.forEach((thumb) => {
    thumb.src = product.image;
    thumb.alt = product.alt;
  });

  detailPanel.classList.add("is-open");
  detailPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

document.querySelectorAll("[data-product]").forEach((card) => {
  card.addEventListener("click", () => openProduct(card.dataset.product));
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openProduct(card.dataset.product);
    }
  });
});

document.querySelector(".close-detail")?.addEventListener("click", () => {
  detailPanel.classList.remove("is-open");
});

document.querySelector(".inline-inquiry button")?.addEventListener("click", (event) => {
  const button = event.currentTarget;
  button.textContent = "Inquiry drafted";
  window.setTimeout(() => {
    button.textContent = "Send inquiry";
  }, 2200);
});
