const STORAGE_KEY = "jacobsen-mower-admin-demo";

const starterListings = [
  {
    id: crypto.randomUUID(),
    image: "./assets/pgm22.png",
    year: "2017",
    model: "Jacobsen PGM22 Walk Reel",
    price: "$4,850",
    note: "22 inch walk-behind reel mower example. Pickup or freight quote confirmed with seller.",
    hours: "312",
    width: "22 in.",
    included: "Catcher, roller, transport wheels"
  },
  {
    id: crypto.randomUUID(),
    image: "./assets/eclipse-2.png",
    year: "2020",
    model: "Jacobsen Eclipse 2",
    price: "$3,950",
    note: "Battery walk mower example with room for hours, notes, and accessories.",
    hours: "184",
    width: "22 in.",
    included: "Charger, catcher, roller"
  },
  {
    id: crypto.randomUUID(),
    image: "./assets/pgm22.png",
    year: "2019",
    model: "Jacobsen PGM22 Walk Reel",
    price: "$3,650",
    note: "Walk-behind reel mower example with room for blade count and accessories.",
    hours: "428",
    width: "22 in.",
    included: "Catcher, roller"
  }
];

const form = document.querySelector("#listingForm");
const grid = document.querySelector("#adminGrid");
const template = document.querySelector("#listingTemplate");
const count = document.querySelector("#listingCount");
const imageInput = document.querySelector("#imageInput");
const imagePreview = document.querySelector("#imagePreview");
const imagePrompt = document.querySelector("#imagePrompt");

let listings = loadListings();
let uploadedImage = "";

function loadListings() {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored ? JSON.parse(stored) : starterListings;
}

function saveListings() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(listings));
}

function renderListings() {
  grid.innerHTML = "";
  count.textContent = `${listings.length} active`;

  listings.forEach((listing) => {
    const node = template.content.cloneNode(true);
    const card = node.querySelector(".admin-card");
    const image = node.querySelector(".card-image");
    const title = node.querySelector("h2");
    const price = node.querySelector(".card-price");
    const note = node.querySelector("p");
    const specs = node.querySelector("dl");
    const remove = node.querySelector(".remove-button");

    image.src = listing.image;
    image.alt = `${listing.year} ${listing.model}`;
    title.textContent = `${listing.year} ${listing.model}`;
    price.textContent = listing.price;
    note.textContent = listing.note;
    specs.innerHTML = [
      ["Hours", listing.hours || "Not listed"],
      ["Width", listing.width || "Not listed"],
      ["Included", listing.included || "Not listed"]
    ]
      .map(([term, value]) => `<div><dt>${term}:</dt><dd>${value}</dd></div>`)
      .join("");

    remove.addEventListener("click", () => {
      listings = listings.filter((item) => item.id !== listing.id);
      saveListings();
      renderListings();
    });

    grid.appendChild(card);
  });
}

imageInput.addEventListener("change", () => {
  const file = imageInput.files?.[0];
  if (!file) return;

  const reader = new FileReader();
  reader.addEventListener("load", () => {
    uploadedImage = reader.result;
    imagePreview.src = uploadedImage;
    imagePrompt.textContent = "Change photo";
    imagePreview.parentElement.classList.add("has-image");
  });
  reader.readAsDataURL(file);
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(form);
  const listing = {
    id: crypto.randomUUID(),
    image: uploadedImage || "./assets/pgm22.png",
    year: data.get("year").trim(),
    model: data.get("model").trim(),
    price: data.get("price").trim(),
    note: data.get("note").trim(),
    hours: data.get("hours").trim(),
    width: data.get("width").trim(),
    included: data.get("included").trim()
  };

  listings = [listing, ...listings];
  saveListings();
  renderListings();
  form.reset();
  uploadedImage = "";
  imagePreview.removeAttribute("src");
  imagePreview.parentElement.classList.remove("has-image");
  imagePrompt.textContent = "Add photo";
});

renderListings();
