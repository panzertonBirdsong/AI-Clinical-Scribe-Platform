import json

INPUT_FILE = "icd10cm_order_2027.txt"
OUTPUT_FILE = "icd10_subset.json"

PREFIXES = [
    "R05", "R06", "R07", "R10", "R11", "R21", "R30", "R50", "R51", "R53",
    "J00", "J01", "J02", "J03", "J04", "J05", "J06",
    "J10", "J11", "J12", "J13", "J14", "J15", "J16", "J17", "J18",
    "J20", "J21", "J22", "J30", "J31", "J32", "J45",
    "I10",
    "E11", "E78",
    "F32", "F33", "F41",
    "K21", "K29", "K59",
    "N30", "N39",
    "M25", "M54", "M79",
    "L20", "L21", "L23", "L24", "L25", "L30",
    "G43", "G44",
]

def add_dot(code):
    if len(code) > 3:
        return code[:3] + "." + code[3:]
    return code

subset = []

with open(INPUT_FILE, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        # Fixed-width columns
        raw_code = line[6:14].strip()
        valid_flag = line[14:15].strip()

        # Long description starts after the short description
        long_description = line[77:].strip()

        if not raw_code or not long_description:
            continue

        # Keep only valid/selectable codes
        if valid_flag != "1":
            continue

        if any(raw_code.startswith(prefix) for prefix in PREFIXES):
            subset.append({
                "code": add_dot(raw_code),
                "description": long_description
            })

subset = subset[:300]

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(subset, f, indent=2)

print(f"Saved {len(subset)} ICD-10 codes to {OUTPUT_FILE}")