#!/usr/bin/env python3
"""
Lawn Dominator - Weed Image and Product Label Finder

Console workflow modeled after scraper/find_links.py.

Usage:
  python scraper/find_identification_assets.py
  python scraper/find_identification_assets.py --kind weeds
  python scraper/find_identification_assets.py --kind labels --ids 31,32,33
  python scraper/find_identification_assets.py --refind
  python scraper/find_identification_assets.py --output C:\\Users\\Brian\\Downloads\\aso\\identification_assets.json

Browser workflow:
  Use the fixed top-right Lawn Dominator panel.
  - Record Link saves the current page URL.
  - Record Image saves the largest visible image URL.
  - Next opens the next item without saving.
  - Skip marks the current item skipped.
  - Quit saves and exits.
"""

import argparse
import json
import queue
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path


WEEDS = """
1. Tall Fescue Clumps
2. Ryegrass Escape
3. Nimblewill
4. Creeping Bentgrass
5. Quackgrass
6. Orchardgrass
7. Bahiagrass
8. Smutgrass
9. Johnsongrass
10. Foxtail
11. Barnyardgrass / Signalgrass
12. Chamberbitter
13. Virginia Copperleaf
14. Mallow
15. Smartweed
16. Black Medic
17. Asiatic Hawksbeard / False Dandelion
18. Healall / Self-Heal
19. Speedwell
20. Bedstraw / Cleavers
21. Yellow Nutsedge
22. Purple Nutsedge
"""


PRODUCTS = """
1. Fertilizers / Nutrients | Scotts Turf Builder WinterGuard Fall Lawn Food
2. Fertilizers / Nutrients | Scotts Turf Builder SummerGuard with Insect Control
3. Fertilizers / Nutrients | Scotts Turf Builder Starter Food for New Grass
4. Fertilizers / Nutrients | Milorganite Organic Nitrogen Fertilizer
5. Fertilizers / Nutrients | The Andersons PGF Complete
6. Fertilizers / Nutrients | Lesco 30-0-10 Professional Fertilizer
7. Fertilizers / Nutrients | Simple Lawn Solutions 16-4-8 Liquid
8. Fertilizers / Nutrients | Simple Lawn Solutions 28-0-0 Liquid Nitrogen
9. Fertilizers / Nutrients | GreenView Fairway Formula Spring Fertilizer
10. Fertilizers / Nutrients | Jonathan Green Veri-Green Nitrogen Fertilizer
11. Fertilizers / Nutrients | Ringer Lawn Restore
12. Fertilizers / Nutrients | Sunday Custom Lawn Nutrient Plan
13. Fertilizers / Nutrients | Sta-Green Performance Max Lawn Fertilizer
14. Fertilizers / Nutrients | Vigoro All Season Lawn Fertilizer
15. Fertilizers / Nutrients | Purely Organic Lawn Food
16. Fertilizers / Nutrients | Lebanon Pro Fertilizer
17. Fertilizers / Nutrients | Scotts Green Max Lawn Food
18. Fertilizers / Nutrients | Scotts Turf Builder Triple Action
19. Fertilizers / Nutrients | The Andersons Deep Green 24-0-11
20. Fertilizers / Nutrients | Miracle-Gro Lawn Food
21. Fertilizers / Nutrients | Yard Mastery Flagship 24-0-6 with Iron
22. Fertilizers / Nutrients | Yard Mastery Stress Blend 7-0-20
23. Fertilizers / Nutrients | Yard Mastery Double Dark 16-0-0
24. Fertilizers / Nutrients | Down to Earth Organic Bio-Turf 8-3-5
25. Fertilizers / Nutrients | Simple Lawn Solutions Superior 15-0-15 Liquid
26. Fertilizers / Nutrients | Sustane 8-2-4 Organic Fertilizer
27. Fertilizers / Nutrients | PetraMax Neighbor's Envy 7-in-1 Liquid Fertilizer
28. Fertilizers / Nutrients | GCI Turf 5-0-5 Liquid Fertilizer
29. Fertilizers / Nutrients | Espoma Spring Lawn Booster
30. Fertilizers / Nutrients | Lesco 24-2-11 Professional Fertilizer
31. Fungicides | Armada 50 WDG
32. Fungicides | Pillar SC Intrinsic Brand Fungicide
33. Fungicides | Clearys 3336 F
34. Fungicides | Propiconazole 14.3 / Banner Maxx
35. Fungicides | Spectracide Immunox Lawn Disease Control
36. Fungicides | Eagle 20EW
37. Fungicides | Daconil / Chlorothalonil
38. Fungicides | Bonide Infuse Lawn & Landscape
39. Fungicides | Emerald / Boscalid
40. Fungicides | Medallion WDG / Fludioxonil
41. Fungicides | Heritage / Azoxystrobin
42. Fungicides | Liquid Copper Fungicide / Bonide
43. Fungicides | Jonathan Green Lawn Fungus Control
44. Fungicides | Subdue Maxx / Mefenoxam
45. Fungicides | Velista / Penthiopyrad
46. Herbicides / Pre-emergents | Scotts Halts Crabgrass & Grassy Weed Preventer
47. Herbicides / Pre-emergents | Dimension 2EW / Dithiopyr
48. Herbicides / Pre-emergents | Pendulum 2G / Pendimethalin
49. Herbicides / Pre-emergents | Gallery 75 DF / Isoxaben
50. Herbicides / Pre-emergents | Specticle G / Indaziflam
51. Herbicides / Pre-emergents | Corn Gluten Meal
52. Herbicides / Pre-emergents | Scotts Weed B Gon Weed Killer
53. Herbicides / Pre-emergents | Tenacity / Mesotrione
54. Herbicides / Pre-emergents | Drive XLR8 / Quinclorac
55. Herbicides / Pre-emergents | Turflon Ester / Triclopyr
56. Herbicides / Pre-emergents | SedgeHammer+ / Halosulfuron
57. Herbicides / Pre-emergents | Dismiss / Sulfentrazone
58. Herbicides / Pre-emergents | Roundup / Glyphosate
59. Herbicides / Pre-emergents | Pylex / Topramezone
60. Herbicides / Pre-emergents | MSMA Target 6 Plus
61. Herbicides / Pre-emergents | BioAdvanced All-in-One Lawn Weed & Crabgrass Killer
62. Herbicides / Pre-emergents | Fiesta Lawn Weed Killer
63. Herbicides / Pre-emergents | Certainty Turf Herbicide / Sulfosulfuron
64. Herbicides / Pre-emergents | Southern Ag Amine 2,4-D Weed Killer
65. Herbicides / Pre-emergents | SpeedZone Lawn Weed Killer
66. Herbicides / Pre-emergents | Q4 Plus Turf Herbicide
67. Herbicides / Pre-emergents | Trimec Classic / Trimec Southern
68. Herbicides / Pre-emergents | Image Kills Nutsedge
69. Herbicides / Pre-emergents | Green Gobbler Vinegar Weed & Grass Killer
70. Herbicides / Pre-emergents | Preen One LawnCare Weed & Feed
71. Herbicides / Pre-emergents | Hi-Yield Turf & Ornamental Weed & Grass Stopper with Dimension
72. Insecticides | Bifen I/T
73. Insecticides | Acelepryn SC
74. Insecticides | Acelepryn G
75. Insecticides | Scotts GrubEx1 Season Long Grub Killer
76. Insecticides | Dylox 6.2 Granules
77. Insecticides | Imidacloprid 0.5G
78. Insecticides | Ortho BugClear Lawn Insect Killer
79. Insecticides | Spectracide Triazicide Insect Killer for Lawns
80. Insecticides | Sevin Insect Killer Lawn Granules
81. Insecticides | BioAdvanced Complete Insect Killer for Soil & Turf
82. Insecticides | Spinosad / Captain Jack's / Monterey
83. Insecticides | Bacillus thuringiensis var. kurstaki / Bt
84. Insecticides | Milky Spore Powder
85. Insecticides | Beneficial Nematodes
86. Insecticides | Amdro Fire Ant Yard Treatment Bait
87. Insecticides | Neem Oil / Azadirachtin
88. Insecticides | Meridian 0.33G
89. Insecticides | Atticus Fervid Insecticide/Miticide
90. Insecticides | Kontos
91. Insecticides | Movento / Movento MPC
92. Insecticides | Ortho Home Defense Insect Killer for Lawns
93. Insecticides | BioAdvanced 24hr Grub Killer Plus
94. Insecticides | Arena 0.25G / Clothianidin
95. Insecticides | Demand CS / Lambda-Cyhalothrin
96. Insecticides | Zylam Liquid Systemic Insecticide / Dinotefuran
97. Soil / Amendments / Micros / PGRs | Chelated Liquid Iron
98. Soil / Amendments / Micros / PGRs | The Andersons Humic DG
99. Soil / Amendments / Micros / PGRs | Pelletized Lime / Calcitic
100. Soil / Amendments / Micros / PGRs | Pelletized Dolomitic Lime
101. Soil / Amendments / Micros / PGRs | Pelletized Gypsum
102. Soil / Amendments / Micros / PGRs | Elemental Sulfur
103. Soil / Amendments / Micros / PGRs | Epsom Salt / Magnesium Sulfate
104. Soil / Amendments / Micros / PGRs | Seaweed / Kelp Extract / Maxicrop
105. Soil / Amendments / Micros / PGRs | Hydretain Root Zone Moisture Manager
106. Soil / Amendments / Micros / PGRs | Revolution Soil Surfactant
107. Soil / Amendments / Micros / PGRs | MycoApply Mycorrhizal Inoculant
108. Soil / Amendments / Micros / PGRs | Biochar Soil Amendment
109. Soil / Amendments / Micros / PGRs | Potassium Sulfate / SOP 0-0-50
110. Soil / Amendments / Micros / PGRs | Manganese Sulfate
111. Soil / Amendments / Micros / PGRs | Diatomaceous Earth
112. Soil / Amendments / Micros / PGRs | Sul-Po-Mag / K-Mag
113. Soil / Amendments / Micros / PGRs | N-Ext RGS Root Growth Stimulator
114. Soil / Amendments / Micros / PGRs | N-Ext 0-0-2 MicroGreene
115. Soil / Amendments / Micros / PGRs | N-Ext Air-8 Soil Penetrant
116. Soil / Amendments / Micros / PGRs | N-Ext Humic12 Liquid Humic Acid
117. Soil / Amendments / Micros / PGRs | Simple Lawn Solutions Lawn Energizer Micronutrient Booster
118. Soil / Amendments / Micros / PGRs | Primo Maxx / T-Nex
119. Soil / Amendments / Micros / PGRs | Trimmit 2SC / Paclobutrazol
120. Soil / Amendments / Micros / PGRs | Cutless / Flurprimidol
121. Soil / Amendments / Micros / PGRs | Anuew / Prohexadione Calcium
122. Soil / Amendments / Micros / PGRs | Proxy / Embark / Mefluidide
123. Soil / Amendments / Micros / PGRs | Ethephon
124. Soil / Amendments / Micros / PGRs | Astro / Trinexapac-ethyl / PBI Gordon
125. Soil / Amendments / Micros / PGRs | Pramaxis MEC / Trinexapac-ethyl
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_weeds() -> list[dict]:
    items = []
    for line in WEEDS.strip().splitlines():
        match = re.match(r"(\d+)\.\s+(.+)", line.strip())
        if not match:
            continue
        item_id, name = match.groups()
        items.append({
            "id": int(item_id),
            "kind": "weed",
            "name": name,
            "category": "Weed image",
        })
    return items


def parse_products() -> list[dict]:
    items = []
    for line in PRODUCTS.strip().splitlines():
        match = re.match(r"(\d+)\.\s+([^|]+)\|\s+(.+)", line.strip())
        if not match:
            continue
        item_id, category, name = match.groups()
        items.append({
            "id": int(item_id),
            "kind": "label",
            "name": name.strip(),
            "category": category.strip(),
        })
    return items


def google_url(query: str, images: bool = False) -> str:
    params = {"q": query}
    if images:
        params["tbm"] = "isch"
    return "https://www.google.com/search?" + urllib.parse.urlencode(params)


def search_url(item: dict) -> str:
    if item["kind"] == "weed":
        return google_url(f"{item['name']} lawn weed identification extension", images=True)
    return google_url(f"{item['name']} label pdf OR specimen label OR product label")


def backup_search_url(item: dict) -> str:
    if item["kind"] == "weed":
        return google_url(f"{item['name']} turf weed identification", images=True)
    return google_url(f"{item['name']} SDS pdf")


def default_output_path(root: Path) -> Path:
    return Path.home() / "Downloads" / "aso" / "identification_assets.json"


def load_output(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"schema_version": "1.0", "updated_at": None, "weeds": {}, "labels": {}}


def save_output(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def find_brave_executable() -> str | None:
    candidates = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        str(Path.home() / r"AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def launch_browser_context(pw, root: Path, profile_dir: str):
    common = {
        "user_data_dir": str(root / profile_dir),
        "headless": False,
        "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        "viewport": {"width": 1360, "height": 920},
    }
    brave = find_brave_executable()
    if brave:
        print(f"Using Brave: {brave}")
        return pw.chromium.launch_persistent_context(executable_path=brave, **common)
    print("Brave not found. Falling back to Playwright Chromium.")
    return pw.chromium.launch_persistent_context(**common)


def capture_largest_image(page) -> str:
    return page.evaluate("""
        () => {
          const visible = img => {
            const r = img.getBoundingClientRect();
            return r.width > 80 && r.height > 60 && r.bottom > 0 && r.right > 0;
          };
          const imgs = [...document.images]
            .filter(img => visible(img) && (img.currentSrc || img.src))
            .sort((a, b) => (b.naturalWidth * b.naturalHeight) - (a.naturalWidth * a.naturalHeight));
          return imgs[0]?.currentSrc || imgs[0]?.src || "";
        }
    """)


def capture_current_page(page) -> dict:
    return {
        "url": page.url,
        "title": page.title(),
    }


def save_asset(data: dict, item: dict, asset_url: str, page_url: str, title: str, notes: str, output_path: Path):
    bucket_name = "weeds" if item["kind"] == "weed" else "labels"
    bucket = data.setdefault(bucket_name, {})
    bucket[str(item["id"])] = {
        "id": item["id"],
        "name": item["name"],
        "category": item["category"],
        "url": asset_url,
        "source_page": page_url,
        "title": title,
        "notes": notes,
        "last_seen": now_iso(),
    }
    save_output(output_path, data)


def save_skip(data: dict, item: dict, output_path: Path):
    bucket_name = "weeds" if item["kind"] == "weed" else "labels"
    bucket = data.setdefault(bucket_name, {})
    bucket[str(item["id"])] = {
        "id": item["id"],
        "name": item["name"],
        "category": item["category"],
        "url": "",
        "source_page": "",
        "title": "",
        "notes": "skipped",
        "skipped": True,
        "last_seen": now_iso(),
    }
    save_output(output_path, data)


OVERLAY_SCRIPT = r"""
(() => {
  const state = window.__ldAssetState || {};
  if (document.getElementById('ld-asset-panel')) return;

  const style = document.createElement('style');
  style.textContent = `
    #ld-asset-panel {
      position: fixed;
      top: 12px;
      right: 12px;
      z-index: 2147483647;
      width: 300px;
      box-sizing: border-box;
      padding: 10px;
      border: 2px solid #245c29;
      border-radius: 8px;
      background: #f7fbef;
      color: #152112;
      font: 13px/1.35 Arial, sans-serif;
      box-shadow: 0 12px 40px rgba(0,0,0,.28);
    }
    #ld-asset-panel * { box-sizing: border-box; }
    #ld-asset-panel strong { display: block; font-size: 14px; margin-bottom: 3px; }
    #ld-asset-panel .ld-meta { color: #52604c; margin-bottom: 8px; }
    #ld-asset-panel .ld-buttons { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
    #ld-asset-panel button {
      border: 1px solid #7d8d70;
      border-radius: 6px;
      background: #fff;
      color: #152112;
      padding: 8px 7px;
      font: 700 12px Arial, sans-serif;
      cursor: pointer;
    }
    #ld-asset-panel button.ld-primary { background: #2f6b2f; color: white; border-color: #2f6b2f; }
    #ld-asset-panel button.ld-danger { background: #7d2f1e; color: white; border-color: #7d2f1e; }
    #ld-asset-panel input {
      width: 100%;
      margin-top: 7px;
      border: 1px solid #bac7b0;
      border-radius: 6px;
      padding: 7px;
      font: 12px Arial, sans-serif;
    }
  `;
  document.documentElement.appendChild(style);

  const panel = document.createElement('div');
  panel.id = 'ld-asset-panel';
  panel.innerHTML = `
    <strong>Lawn Dominator Capture</strong>
    <div class="ld-meta">
      <div>${state.index || ''}/${state.total || ''} ${state.kind || ''}</div>
      <div>${state.name || ''}</div>
    </div>
    <div class="ld-buttons">
      <button class="ld-primary" data-command="record-link">Record Link</button>
      <button class="ld-primary" data-command="record-image">Record Image</button>
      <button data-command="next">Next</button>
      <button data-command="skip">Skip</button>
      <button data-command="reopen">Reopen Search</button>
      <button class="ld-danger" data-command="quit">Quit</button>
    </div>
    <input id="ld-asset-notes" placeholder="Optional notes">
  `;
  document.body.appendChild(panel);

  function largestImageUrl() {
    const visible = img => {
      const r = img.getBoundingClientRect();
      return r.width > 80 && r.height > 60 && r.bottom > 0 && r.right > 0;
    };
    const imgs = [...document.images]
      .filter(img => visible(img) && (img.currentSrc || img.src))
      .sort((a, b) => (b.naturalWidth * b.naturalHeight) - (a.naturalWidth * a.naturalHeight));
    return imgs[0]?.currentSrc || imgs[0]?.src || '';
  }

  panel.addEventListener('click', event => {
    const button = event.target.closest('button[data-command]');
    if (!button || !window.ldAssetCommand) return;
    const command = button.dataset.command;
    const notes = document.getElementById('ld-asset-notes')?.value || '';
    const payload = {
      command,
      url: command === 'record-image' ? largestImageUrl() : location.href,
      pageUrl: location.href,
      title: document.title,
      notes,
    };
    window.ldAssetCommand(payload);
  });
})();
"""


def set_overlay_state(page, item: dict, index: int, total: int):
    state = {
        "index": index,
        "total": total,
        "kind": "weed image" if item["kind"] == "weed" else "product label",
        "name": item["name"],
    }
    try:
        page.evaluate(
            """state => {
                window.__ldAssetState = state;
                const old = document.getElementById('ld-asset-panel');
                if (old) old.remove();
            }""",
            state,
        )
        page.evaluate(OVERLAY_SCRIPT)
    except Exception as exc:
        print(f"  overlay injection failed on {page.url[:80]}: {exc.__class__.__name__}")


def set_overlay_state_all(ctx, item: dict, index: int, total: int):
    for open_page in ctx.pages:
        set_overlay_state(open_page, item, index, total)


def wait_for_overlay_command(
    ctx,
    command_queue: "queue.Queue[dict]",
    item: dict,
    index: int,
    total: int,
) -> dict:
    while True:
        try:
            command = command_queue.get(timeout=0.75)
            if command.get("item_id") == item["id"] and command.get("kind") == item["kind"]:
                return command
        except queue.Empty:
            set_overlay_state_all(ctx, item, index, total)


def process_item(ctx, page, command_queue: "queue.Queue[dict]", data: dict, item: dict, index: int, total: int, output_path: Path) -> bool:
    print(f"\n[{index}/{total}] {item['name']}  ({item['category']})")
    page.goto(search_url(item), wait_until="domcontentloaded", timeout=30000)
    set_overlay_state_all(ctx, item, index, total)

    while True:
        command = wait_for_overlay_command(ctx, command_queue, item, index, total)
        action = command.get("command")
        if action == "quit":
            return False
        if action == "next":
            return True
        if action == "skip":
            save_skip(data, item, output_path)
            print("  skipped")
            return True
        if action == "reopen":
            page.goto(search_url(item), wait_until="domcontentloaded", timeout=30000)
            set_overlay_state_all(ctx, item, index, total)
            continue
        if action in ("record-link", "record-image"):
            asset_url = command.get("url", "")
            if not asset_url:
                print("  no URL found, click a result or use Record Link")
                continue
            save_asset(
                data,
                item,
                asset_url,
                command.get("pageUrl", page.url),
                command.get("title", ""),
                command.get("notes", ""),
                output_path,
            )
            print(f"  saved: {asset_url[:110]}")
            return True


def existing_for(data: dict, item: dict) -> dict | None:
    bucket = data.get("weeds" if item["kind"] == "weed" else "labels", {})
    return bucket.get(str(item["id"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["all", "weeds", "labels"], default="all")
    parser.add_argument("--ids", help="Comma-separated IDs for the selected kind")
    parser.add_argument("--refind", action="store_true", help="Revisit items that already have a saved URL")
    parser.add_argument("--reset", action="store_true", help="Delete the output JSON before starting")
    parser.add_argument("--output", help="Output JSON path")
    parser.add_argument("--profile-dir", default="scraper/google-asset-profile")
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    output_path = Path(args.output) if args.output else default_output_path(root)
    if args.reset and output_path.exists():
        output_path.unlink()
        print(f"Reset: deleted {output_path}")

    data = load_output(output_path)
    items = []
    if args.kind in ("all", "weeds"):
        items.extend(parse_weeds())
    if args.kind in ("all", "labels"):
        items.extend(parse_products())
    if args.ids:
        wanted = {int(part.strip()) for part in args.ids.split(",") if part.strip()}
        items = [item for item in items if item["id"] in wanted]

    if not items:
        print("No matching items.")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed. Run: pip install playwright && playwright install chromium")
        return

    print(f"Lawn Dominator - Identification Asset Finder ({len(items)} item(s))")
    print(f"Output: {output_path}")
    print("Use the top-right browser panel: Record Link, Record Image, Next, Skip, Quit.")

    with sync_playwright() as pw:
        ctx = launch_browser_context(pw, root, args.profile_dir)
        command_queue: queue.Queue[dict] = queue.Queue()
        current = {"id": None, "kind": None}
        overlay_state = {"item": None, "index": 0, "total": len(items)}

        def handle_command(source, payload):
            payload = dict(payload or {})
            payload["item_id"] = current["id"]
            payload["kind"] = current["kind"]
            command_queue.put(payload)

        ctx.expose_binding("ldAssetCommand", handle_command)
        ctx.add_init_script(OVERLAY_SCRIPT)
        def wire_overlay_events(new_page):
            def refresh_overlay():
                if overlay_state["item"]:
                    set_overlay_state(new_page, overlay_state["item"], overlay_state["index"], overlay_state["total"])

            new_page.on("domcontentloaded", refresh_overlay)
            new_page.on("load", refresh_overlay)
            new_page.on(
                "framenavigated",
                lambda frame: frame == new_page.main_frame and refresh_overlay(),
            )

        ctx.on("page", wire_overlay_events)
        page = ctx.new_page()
        wire_overlay_events(page)
        for index, item in enumerate(items, 1):
            if existing_for(data, item) and not args.refind:
                print(f"[{item['id']}] {item['name']} - skipped (already saved)")
                continue
            current["id"] = item["id"]
            current["kind"] = item["kind"]
            overlay_state["item"] = item
            overlay_state["index"] = index
            keep_going = process_item(ctx, page, command_queue, data, item, index, len(items), output_path)
            if not keep_going:
                break
        page.close()
        ctx.close()

    weeds_done = len(data.get("weeds", {}))
    labels_done = len(data.get("labels", {}))
    print("\nDone.")
    print(f"  Weed images: {weeds_done}/22")
    print(f"  Product labels: {labels_done}/125")
    print(f"  Saved to: {output_path}")


if __name__ == "__main__":
    main()
