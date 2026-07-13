
import os
import re
import uuid
import datetime

from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ============================================================
# In-memory storage
# ============================================================
PROFILES = {}

# Small stopword list used only for comparing bio text
STOPWORDS = {"and", "the", "a", "an", "is", "are", "i", "of", "to", "in", "on", "with", "my", "for", "at"}


# ============================================================
# Helpers
# ============================================================

def normalize_list(items):
    """Accepts a list (['Reading','Cricket']) or a comma-separated string
    ('Reading, Cricket') and returns a clean list of strings."""
    if items is None:
        return []
    if isinstance(items, str):
        items = items.split(",")
    return [str(i).strip() for i in items if str(i).strip()]


def normalize_words(text):
    """Lowercase a bio and split into meaningful words, dropping stopwords."""
    text = (text or "").lower()
    words = re.findall(r"[a-z]+", text)
    return set(w for w in words if w not in STOPWORDS)


def overlap_percent(list_a, list_b):
    """Simple % overlap between two lists: shared items / all unique items combined.
    Used for interests, values, and bio words."""
    set_a = set(str(x).strip().lower() for x in list_a)
    set_b = set(str(x).strip().lower() for x in list_b)
    union = set_a | set_b
    if not union:
        return 0
    shared = set_a & set_b
    return round((len(shared) / len(union)) * 100)


def age_score(age_a, age_b):
    diff = abs(int(age_a) - int(age_b))
    if diff <= 2:
        return 100
    if diff <= 5:
        return 80
    return 50


def city_score(city_a, city_b):
    city_a = (city_a or "").strip().lower()
    city_b = (city_b or "").strip().lower()
    if city_a and city_a == city_b:
        return 100
    return 0


def bio_score(bio_a, bio_b):
    return overlap_percent(normalize_words(bio_a), normalize_words(bio_b))


# Feature weights — must add up to 100%
WEIGHTS = {
    "interest": 0.40,
    "value": 0.25,
    "city": 0.15,
    "age": 0.10,
    "bio": 0.10,
}


def compatibility_score(a, b):
    interest = overlap_percent(a["interests"], b["interests"])
    value = overlap_percent(a["values"], b["values"])
    city = city_score(a["city"], b["city"])
    age = age_score(a["age"], b["age"])
    bio = bio_score(a["bio"], b["bio"])

    final = (
        interest * WEIGHTS["interest"]
        + value * WEIGHTS["value"]
        + city * WEIGHTS["city"]
        + age * WEIGHTS["age"]
        + bio * WEIGHTS["bio"]
    )

    shared_interests = sorted(set(i.lower() for i in a["interests"]) & set(i.lower() for i in b["interests"]))
    shared_values = sorted(set(v.lower() for v in a["values"]) & set(v.lower() for v in b["values"]))

    return {
        "score": round(final),
        "interest_score": interest,
        "value_score": value,
        "city_score": city,
        "age_score": age,
        "bio_score": bio,
        "shared_interests": shared_interests,
        "shared_values": shared_values,
    }


def compatibility_label(score):
    if score >= 85:
        return "Excellent Compatibility"
    if score >= 70:
        return "High Compatibility"
    if score >= 50:
        return "Moderate Compatibility"
    return "Low Compatibility"


def build_reason(detail):
    """Turns the score breakdown into a short human-readable explanation."""
    bullets = []
    if detail["shared_interests"]:
        bullets.append(f"{len(detail['shared_interests'])} shared interests ({', '.join(detail['shared_interests'])})")
    if detail["shared_values"]:
        bullets.append(f"{len(detail['shared_values'])} shared values ({', '.join(detail['shared_values'])})")
    if detail["city_score"] == 100:
        bullets.append("Same city")
    if detail["age_score"] >= 80:
        bullets.append("Similar age")
    if not bullets:
        bullets.append("Limited overlap based on current profile info")
    return {"label": compatibility_label(detail["score"]), "reasons": bullets}


# ============================================================
# Routes
# ============================================================

@app.route("/")
def index():
    return jsonify({
        "app": "Vibe Connect AI Engine (MVP draft)",
        "status": "running",
        "endpoints": [
            "POST /profiles",
            "GET /profiles",
            "GET /profiles/<id>",
            "DELETE /profiles/<id>",
            "GET /profiles/<id>/matches",
        ]
    })


@app.route("/profiles", methods=["POST"])
def create_profile():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    try:
        age = int(data.get("age"))
    except (TypeError, ValueError):
        return jsonify({"error": "age must be a number"}), 400

    profile_id = str(uuid.uuid4())
    profile = {
        "id": profile_id,
        "name": name,
        "age": age,
        "city": str(data.get("city", "")).strip(),
        "bio": str(data.get("bio", "")).strip(),
        "interests": normalize_list(data.get("interests")),
        "values": normalize_list(data.get("values")),
        "created_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    PROFILES[profile_id] = profile
    return jsonify(profile), 201


@app.route("/profiles", methods=["GET"])
def list_profiles():
    return jsonify(list(PROFILES.values()))


@app.route("/profiles/<profile_id>", methods=["GET"])
def get_profile(profile_id):
    profile = PROFILES.get(profile_id)
    if not profile:
        return jsonify({"error": "profile not found"}), 404
    return jsonify(profile)


@app.route("/profiles/<profile_id>", methods=["DELETE"])
def delete_profile(profile_id):
    if profile_id not in PROFILES:
        return jsonify({"error": "profile not found"}), 404
    del PROFILES[profile_id]
    return jsonify({"deleted": True})


@app.route("/profiles/<profile_id>/matches", methods=["GET"])
def get_matches(profile_id):
    source = PROFILES.get(profile_id)
    if not source:
        return jsonify({"error": "profile not found"}), 404

    matches = []
    for other_id, other in PROFILES.items():
        if other_id == profile_id:
            continue
        detail = compatibility_score(source, other)
        reason = build_reason(detail)
        matches.append({
            "id": other_id,
            "name": other["name"],
            "age": other["age"],
            "city": other["city"],
            "score": detail["score"],
            "interest_score": detail["interest_score"],
            "value_score": detail["value_score"],
            "city_score": detail["city_score"],
            "age_score": detail["age_score"],
            "bio_score": detail["bio_score"],
            "compatibility": reason["label"],
            "reasons": reason["reasons"],
        })

    matches.sort(key=lambda m: m["score"], reverse=True)
    return jsonify(matches)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
