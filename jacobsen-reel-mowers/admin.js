const STORAGE_KEY = "jacobsen-mower-admin-demo";

const starterListings = [
  {
    id: crypto.randomUUID(),
    images: ["./assets/pgm22.png", "./assets/pgm22-field-2.jpg"],
    year: "2017",
    model: "Jacobsen PGM22 Walk Reel",
    price: "$4,850",
    note: "22 inch walk-behind reel mower example. Pickup or freight quote confirmed with seller.",
    stock: "JM-017",
    status: "Available"
  },
  {
    id: crypto.randomUUID(),
    images: ["./assets/eclipse-2.png", "./assets/eclipse-2-field.jpg"],
    year: "2020",
    model: "Jacobsen Eclipse 2",
    price: "$3,950",
    note: "Battery walk mower example with room for hours, notes, and accessories.",
    stock: "JM-020",
    status: "Available"
  },
  {
    id: crypto.randomUUID(),
    images: ["./assets/pgm22.png", "./assets/pgm22-field-1.jpg"],
    year: "2019",
    model: "Jacobsen PGM22 Walk Reel",
    price: "$3,650",
    note: "Walk-behind reel mower example with room for blade count and accessories.",
    stock: "JM-019",
    status: "Pending"
  }
];

const form = document.querySelector("#listingForm");
const grid = document.querySelector("#adminGrid");
const template = document.querySelector("#listingTemplate");
const count = document.querySelector("#listingCount");
const imageInput = document.querySelector("#imageInput");
const imagePreview = document.querySelector("#imagePreview");
const imagePrompt = document.querySelector("#imagePrompt");
const imageStrip = document.querySelector("#imageStrip");
const dialog = document.querySelector("#listingDialog");
const dialogGallery = document.querySelector("#dialogGallery");
const dialogStock = document.querySelector("#dialogStock");
const dialogTitle = document.querySelector("#dialogTitle");
const dialogPrice = document.querySelector("#dialogPrice");
const dialogNote = document.querySelector("#dialogNote");

let listings = loadListings();
let uploadedImages = [];

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
    const stock = node.querySelector(".stock-pill");
    const status = node.querySelector(".status-pill");
    const remove = node.querySelector(".remove-button");
    const primaryImage = listing.images?.[0] || listing.image || "./assets/pgm22.png";

    image.src = primaryImage;
    image.alt = `${listing.year} ${listing.model}`;
    stock.textContent = listing.stock || "No stock #";
    title.textContent = `${listing.year} ${listing.model}`;
    price.textContent = listing.price;
    note.textContent = listing.note;
    status.textContent = listing.status || "Available";
    status.dataset.status = status.textContent.toLowerCase();

    card.addEventListener("click", () => openListing(listing));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openListing(listing);
      }
    });

    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      listings = listings.filter((item) => item.id !== listing.id);
      saveListings();
      renderListings();
    });

    grid.appendChild(card);
  });
}

imageInput.addEventListener("change", () => {
  const files = Array.from(imageInput.files || []);
  if (!files.length) return;

  Promise.all(files.map(readFile)).then((images) => {
    uploadedImages = images;
    imagePreview.src = uploadedImages[0];
    imagePrompt.textContent = `${uploadedImages.length} selected`;
    imagePreview.parentElement.classList.add("has-image");
    imageStrip.innerHTML = uploadedImages
      .map((src) => `<img src="${src}" alt="Selected mower preview" />`)
      .join("");
  });
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(form);
  const listing = {
    id: crypto.randomUUID(),
    images: uploadedImages.length ? uploadedImages : ["./assets/pgm22.png"],
    year: data.get("year").trim(),
    model: data.get("model").trim(),
    price: data.get("price").trim(),
    note: data.get("note").trim(),
    stock: data.get("stock").trim() || `JM-${String(Date.now()).slice(-4)}`,
    status: data.get("status")
  };

  listings = [listing, ...listings];
  saveListings();
  renderListings();
  form.reset();
  uploadedImages = [];
  imagePreview.removeAttribute("src");
  imagePreview.parentElement.classList.remove("has-image");
  imagePrompt.textContent = "Add photos";
  imageStrip.innerHTML = "";
});

function readFile(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(reader.result));
    reader.readAsDataURL(file);
  });
}

function openListing(listing) {
  const images = listing.images?.length ? listing.images : [listing.image || "./assets/pgm22.png"];
  dialogGallery.innerHTML = images.map((src) => `<img src="${src}" alt="${listing.model}" />`).join("");
  dialogStock.textContent = listing.stock || "No stock #";
  dialogTitle.textContent = `${listing.year} ${listing.model}`;
  dialogPrice.textContent = listing.price;
  dialogNote.textContent = listing.note;
  dialog.showModal();
}

document.querySelector(".dialog-close").addEventListener("click", () => dialog.close());

renderListings();
