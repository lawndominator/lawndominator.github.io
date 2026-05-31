const products = {
  greens: {
    image: "./assets/greens-king-iv-plus.png",
    alt: "Jacobsen Greens King IV Plus",
    status: "Available now",
    title: "2017 Jacobsen Greens King IV Plus",
    price: "$4,850.00",
    lot: "LOT 0417",
    specs: [
      ["Year", "2017"],
      ["Model", "Greens King IV Plus"],
      ["Reel", "11 blade example reel"],
      ["Cutting width", "22 in."],
      ["Engine hours", "Example hours shown here"],
      ["Included", "Roller, catcher, transport wheels"],
      ["Condition", "Used. Example listing copy for photos, notes, and buyer questions."]
    ]
  },
  eclipse: {
    image: "./assets/eclipse-2.png",
    alt: "Jacobsen Eclipse 2 walking reel mower",
    status: "Example walk mower",
    title: "2020 Jacobsen Eclipse 2",
    price: "$3,950.00",
    lot: "LOT 0920",
    specs: [
      ["Year", "2020"],
      ["Model", "Eclipse 2"],
      ["Power", "Battery walk mower example"],
      ["Cutting width", "22 in."],
      ["Hours", "Example runtime shown here"],
      ["Included", "Charger, catcher, roller"],
      ["Condition", "Used. Example sales copy with final inspection notes added by admin."]
    ]
  },
  gp: {
    image: "./assets/gp400.png",
    alt: "Jacobsen GP400 triplex reel mower",
    status: "Triplex example",
    title: "2019 Jacobsen GP400",
    price: "$12,900.00",
    lot: "LOT 3019",
    specs: [
      ["Year", "2019"],
      ["Model", "GP400"],
      ["Type", "Triplex greens mower example"],
      ["Cutting width", "Approx. 62 in."],
      ["Engine hours", "Example hours shown here"],
      ["Included", "Three cutting units, operator platform, turf tires"],
      ["Condition", "Used. Example listing text for large-property and course buyers."]
    ]
  }
};

const revealObserver = new IntersectionObserver(
  (entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        revealObserver.unobserve(entry.target);
      }
    }
  },
  { threshold: 0.12 }
);

document.querySelectorAll("[data-reveal]").forEach((element) => {
  revealObserver.observe(element);
});

const activeImage = document.querySelector("#activeImage");
const activeStatus = document.querySelector("#activeStatus");
const activeTitle = document.querySelector("#activeTitle");
const activePrice = document.querySelector("#activePrice");
const activeLot = document.querySelector("#activeLot");
const activeSpecs = document.querySelector("#activeSpecs");

function setProduct(key) {
  const product = products[key];
  if (!product || !activeImage || !activeSpecs) return;

  activeImage.classList.remove("is-swapping");
  void activeImage.offsetWidth;
  activeImage.classList.add("is-swapping");
  activeImage.src = product.image;
  activeImage.alt = product.alt;
  activeStatus.textContent = product.status;
  activeTitle.textContent = product.title;
  activePrice.textContent = product.price;
  activeLot.textContent = product.lot;
  activeSpecs.innerHTML = product.specs
    .map(([term, detail]) => `<div><dt>${term}</dt><dd>${detail}</dd></div>`)
    .join("");

  document.querySelectorAll("[data-product]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.product === key);
  });
}

document.querySelectorAll("[data-product]").forEach((button) => {
  button.addEventListener("click", () => setProduct(button.dataset.product));
});

document.querySelectorAll("[data-product-row]").forEach((row) => {
  row.addEventListener("click", () => {
    setProduct(row.dataset.productRow);
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
});

document.querySelector(".lead-form button")?.addEventListener("click", (event) => {
  const button = event.currentTarget;
  button.textContent = "Inquiry drafted";
  window.setTimeout(() => {
    button.textContent = "Send mower inquiry";
  }, 2200);
});
