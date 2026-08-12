import json
import urllib.request
import csv
from pathlib import Path

URL = "https://wger.de/api/v2/exercise/?limit=300&language=2"

req = urllib.request.Request(URL, headers={"Accept": "application/json"})
data = json.loads(urllib.request.urlopen(req).read())

# Manual curated list of ~150 common lifts
# Mapped from wger's dataset by selecting exercises by category + name filtering
common_exercises = set()

# Category-based selection
categories_of_interest = {
    "chest": ["bench press", "push up", "chest fly", "dumbbell bench", "incline bench",
              "decline bench", "pectoral", "cable crossover", "chest dip", "pullover"],
    "back": ["deadlift", "pull up", "chin up", "row", "lat pulldown", "pullover",
             "face pull", "t bar row", "seated row", "dumbbell row"],
    "shoulders": ["overhead press", "shoulder press", "lateral raise", "front raise",
                  "rear delt", "arnold press", "upright row", "shrug", "face pull",
                  "push press", "clean and press"],
    "biceps": ["bicep curl", "hammer curl", "preacher curl", "concentration curl",
               "incline curl", "cable curl", "barbell curl"],
    "triceps": ["tricep extension", "tricep pushdown", "skull crusher", "close grip bench",
                "diamond push up", "overhead extension", "kickback"],
    "legs_quads": ["squat", "front squat", "goblet squat", "hack squat", "leg press",
                   "lunge", "bulgarian split squat", "step up", "leg extension",
                   "sissy squat"],
    "legs_posterior": ["deadlift", "romanian deadlift", "stiff leg deadlift", "good morning",
                       "leg curl", "nordic curl", "glute bridge", "hip thrust",
                       "hyperextension", "reverse hyper"],
    "calves": ["calf raise", "seated calf raise", "standing calf raise", "donkey calf raise"],
    "abs": ["crunch", "sit up", "leg raise", "hanging leg raise", "plank", "cable crunch",
            "ab wheel", "pallof press", "russian twist", "hollow hold"],
    "forearms": ["wrist curl", "reverse wrist curl", "farmer walk", "dead hang",
                 "grip crusher", "pinch grip"],
    "full_body": ["clean", "snatch", "clean and jerk", "snatch pull", "clean pull",
                  "thruster", "burpee", "turkish get up", "kettlebell swing"],
}

all_keywords = [kw for kw_list in categories_of_interest.values() for kw in kw_list]

# Also pull muscle categories from wger for mapping
category_map = {}
try:
    cat_url = "https://wger.de/api/v2/exercisecategory/?limit=50"
    cat_req = urllib.request.Request(cat_url, headers={"Accept": "application/json"})
    cat_data = json.loads(urllib.request.urlopen(cat_req).read())
    for cat in cat_data["results"]:
        category_map[cat["id"]] = cat["name"].lower()
except Exception:
    pass

# Equipment mapping
equipment_map = {}

# Map muscle group by wger category
def get_muscle_group(ex):
    cat_id = ex.get("category", {}).get("id", 0)
    cat_name = category_map.get(cat_id, "")
    name = ex.get("name", "").lower()
    description = ex.get("description", "").lower()

    if any(w in name for w in ["chest", "bench", "fly", "push up", "pectoral", "crossover"]):
        return "chest"
    if any(w in name for w in ["squat", "leg press", "lunge", "leg extension", "step up"]):
        return "quads"
    if any(w in name for w in ["deadlift", "romanian", "leg curl", "glute", "hip thrust",
                                "hamstring", "good morning", "hyperextension"]):
        return "glutes"
    if any(w in name for w in ["row", "pull up", "chin up", "lat pulldown", "pulldown",
                                "face pull", "rear delt"]):
        return "back"
    if any(w in name for w in ["shoulder", "press", "lateral raise", "front raise",
                                "arnold", "shrug", "clean and press", "push press"]):
        if "bench" not in name and "leg" not in name:
            return "shoulders"
    if any(w in name for w in ["bicep", "curl"]):
        if "leg" not in name and "wrist" not in name:
            return "biceps"
    if any(w in name for w in ["tricep", "skull", "pushdown", "kickback", "close grip"]):
        return "triceps"
    if any(w in name for w in ["calf"]):
        return "calves"
    if any(w in name for w in ["crunch", "sit up", "leg raise", "plank", "ab", "pallof",
                                "russian twist", "wheel"]):
        return "abs"
    if any(w in name for w in ["wrist", "farmer", "grip", "pinch"]):
        return "forearms"
    if any(w in name for w in ["clean", "snatch", "thruster", "kettlebell", "turkish"]):
        return "full_body"
    if any(w in name for w in ["dip"]):
        if "chest" in name or "tricep" not in name:
            return "chest"
        return "triceps"

    fallback = {
        10: "back",
        8: "chest",
        9: "chest",
        11: "biceps",
        12: "triceps",
        13: "shoulders",
        14: "calves",
        15: "quads",
        16: "glutes",
        17: "abs",
    }
    return fallback.get(cat_id, "other")


def get_equipment(ex):
    name = ex.get("name", "").lower()
    desc = ex.get("description", "").lower()
    if any(w in name for w in ["barbell", "deadlift", "squat", "bench", "row", "press"]):
        return "barbell"
    if any(w in name for w in ["dumbbell", "kettlebell"]):
        return "dumbbell"
    if any(w in name for w in ["cable", "pulldown", "pushdown", "crossover"]):
        return "cable"
    if any(w in name for w in ["machine", "extension", "curl", "leg press", "hack"]):
        return "machine"
    if any(w in name for w in ["push up", "pull up", "chin up", "dip", "plank", "sit up",
                                "crunch", "burpee", "lunge"]):
        return "bodyweight"
    if any(w in name for w in ["band"]):
        return "band"
    if any(w in name for w in ["smith"]):
        return "machine"
    if any(w in name for w in ["ez bar"]):
        return "barbell"
    return "barbell"


selected = []
seen = set()

for ex in data["results"]:
    name = ex.get("name", "").strip().lower()
    if not name:
        continue

    # Check if this exercise matches any keyword
    matches = [kw for kw in all_keywords if kw in name]
    if not matches:
        continue

    # Deduplicate
    canonical = name.replace(" (female)", "").replace(" (male)", "").strip()
    if canonical in seen:
        continue
    seen.add(canonical)

    muscle = get_muscle_group(ex)
    equipment = get_equipment(ex)

    # Map wger's images for display name
    display = name.title()

    selected.append({
        "name": canonical.replace(" ", "_").replace("-", "_"),
        "display_name": display,
        "muscle_group": muscle,
        "equipment": equipment,
    })

# Write to CSV
csv_path = Path(__file__).resolve().parent.parent / "docs" / "exercise_taxonomy.csv"
with open(csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["name", "display_name", "muscle_group", "equipment"])
    writer.writeheader()
    writer.writerows(sorted(selected, key=lambda x: x["name"]))

print(f"Wrote {len(selected)} exercises to {csv_path}")
print(f"\nBy muscle group:")
from collections import Counter
by_group = Counter(e["muscle_group"] for e in selected)
for g, c in sorted(by_group.items()):
    print(f"  {g}: {c}")
print(f"\nBy equipment:")
by_eq = Counter(e["equipment"] for e in selected)
for g, c in sorted(by_eq.items()):
    print(f"  {g}: {c}")
