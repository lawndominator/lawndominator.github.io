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

Commands while running:
  c        capture current page URL
  i        capture largest image URL on the current page
  p        paste/type a URL manually
  o URL    open a URL in the browser
  r        reopen the search page
  n        skip this item
  q        quit and save
"""

import argparse
import json
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


def prompt_for_item(ctx, page, data: dict, item: dict, output_path: Path) -> bool:
    print(f"\n[{item['id']}] {item['name']}  ({item['category']})")
    print(f"Search: {search_url(item)}")
    page.goto(search_url(item), wait_until="domcontentloaded", timeout=30000)

    while True:
        command = input("  c=current URL, i=largest image, p=paste, o URL=open, r=reopen, n=skip, q=quit > ").strip()
        if command == "q":
            return False
        if command == "n":
            return True
        if command == "r":
            page.goto(search_url(item), wait_until="domcontentloaded", timeout=30000)
            continue
        if command.startswith("o "):
            page.goto(command[2:].strip(), wait_until="domcontentloaded", timeout=30000)
            continue

        page_info = capture_current_page(page)
        asset_url = ""
        if command == "c":
            asset_url = page_info["url"]
        elif command == "i":
            asset_url = capture_largest_image(page)
            if not asset_url:
                print("  No image found on current page.")
                continue
        elif command == "p":
            asset_url = input("  URL > ").strip()
            page_info["url"] = input("  Source page, optional > ").strip() or page_info["url"]
        else:
            print("  Unknown command.")
            continue

        notes = input("  Notes, optional > ").strip()
        save_asset(data, item, asset_url, page_info["url"], page_info["title"], notes, output_path)
        print(f"  OK saved: {asset_url[:110]}")
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
    print("Click the result you want in the browser, then use c or i in this terminal.")

    with sync_playwright() as pw:
        ctx = launch_browser_context(pw, root, args.profile_dir)
        page = ctx.new_page()
        for item in items:
            if existing_for(data, item) and not args.refind:
                print(f"[{item['id']}] {item['name']} - skipped (already saved)")
                continue
            keep_going = prompt_for_item(ctx, page, data, item, output_path)
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
