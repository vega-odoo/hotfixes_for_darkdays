import re
import unicodedata

file_path = "/home/odoo/Downloads/odoo.log.2025-09-24"
output_file_path = "filtered_lines.log"

keywords = ["action_pos_session_closing_control"]

def normalize(text):
    return unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("ASCII").lower()

normalized_keywords = [normalize(k) for k in keywords]

# Read and filter lines with normalized comparison
flexible_matches = []
with open(file_path, "r", encoding="utf-8") as file:
    for line in file:
        normalized_line = normalize(line)
        if any(keyword in normalized_line for keyword in normalized_keywords):
            flexible_matches.append(line.strip())

# Write results to output file
with open(output_file_path, "w", encoding="utf-8") as out_file:
    for match in flexible_matches:
        out_file.write(match + "\n")
        print(match + "\n")

print(f"{len(flexible_matches)} matching lines written to {output_file_path}")
# print(flexible_matches)